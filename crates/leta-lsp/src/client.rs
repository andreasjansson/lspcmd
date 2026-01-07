use std::collections::HashSet;
use std::path::Path;
use std::process::Stdio;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use lsp_types::{
    ClientCapabilities, InitializeParams, InitializeResult, InitializedParams,
    NumberOrString, ProgressParams, ProgressParamsValue, ServerCapabilities, Uri,
    WorkDoneProgress, WorkspaceFolder,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStderr, ChildStdin, ChildStdout};
use tokio::sync::{oneshot, Mutex, RwLock};
use tracing::{debug, error, info, warn};

use crate::capabilities::get_client_capabilities;
use crate::protocol::{encode_message, read_message, LspProtocolError, LspResponseError};

#[derive(Debug, Clone, Serialize)]
struct JsonRpcRequest<P> {
    jsonrpc: &'static str,
    id: u64,
    method: &'static str,
    params: P,
}

#[derive(Debug, Clone, Serialize)]
struct JsonRpcNotification<P> {
    jsonrpc: &'static str,
    method: &'static str,
    params: P,
}

#[derive(Debug, Clone, Serialize)]
struct JsonRpcResponse {
    jsonrpc: &'static str,
    id: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<JsonRpcError>,
}

#[derive(Debug, Clone, Serialize)]
struct JsonRpcError {
    code: i32,
    message: String,
}

#[derive(Debug, Deserialize)]
struct IncomingMessage {
    id: Option<Value>,
    method: Option<String>,
    result: Option<Value>,
    error: Option<IncomingError>,
    params: Option<Value>,
}

#[derive(Debug, Deserialize)]
struct IncomingError {
    code: i64,
    message: String,
    data: Option<Value>,
}

#[derive(Debug, Deserialize)]
struct LanguageStatusParams {
    #[serde(rename = "type")]
    status_type: String,
}

#[derive(Debug, Deserialize)]
struct ServerStatusParams {
    quiescent: Option<bool>,
    health: Option<String>,
}

const REQUEST_TIMEOUT_SECS: u64 = 30;

async fn drain_stderr(stderr: ChildStderr, server_name: &str) {
    let mut reader = BufReader::new(stderr);
    let mut line = String::new();
    
    loop {
        line.clear();
        match reader.read_line(&mut line).await {
            Ok(0) => break,
            Ok(_) => {
                debug!("[{}] stderr: {}", server_name, line.trim_end());
            }
            Err(_) => break,
        }
    }
}

pub struct LspClient {
    process: Child,
    stdin: Mutex<ChildStdin>,
    pending_requests: DashMap<u64, oneshot::Sender<Result<Value, LspResponseError>>>,
    request_id: AtomicU64,
    server_name: String,
    workspace_root: String,
    capabilities: RwLock<ServerCapabilities>,
    // Store raw JSON capabilities for fields not in lsp-types ServerCapabilities struct
    // (e.g. typeHierarchyProvider was added in LSP 3.17 but lsp-types 0.97.0 doesn't have it)
    raw_capabilities: RwLock<Value>,
    initialized: RwLock<bool>,
    service_ready: RwLock<bool>,
    indexing_done: RwLock<bool>,
    active_progress_tokens: Mutex<HashSet<String>>,
}

impl LspClient {
    pub async fn start(
        command: &[&str],
        workspace_root: &Path,
        server_name: &str,
        env: std::collections::HashMap<String, String>,
        init_options: Option<Value>,
    ) -> Result<Arc<Self>, LspProtocolError> {
        let mut cmd = tokio::process::Command::new(command[0]);
        cmd.args(&command[1..])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .current_dir(workspace_root)
            .envs(env);

        let mut process = cmd.spawn()?;

        let stdin = process.stdin.take().expect("Failed to get stdin");
        let stdout = process.stdout.take().expect("Failed to get stdout");
        let stderr = process.stderr.take();

        let workspace_uri: Uri = format!("file://{}", workspace_root.display())
            .parse()
            .map_err(|_| LspProtocolError::InvalidHeader("Invalid workspace path".to_string()))?;

        let client = Arc::new(Self {
            process,
            stdin: Mutex::new(stdin),
            pending_requests: DashMap::new(),
            request_id: AtomicU64::new(0),
            server_name: server_name.to_string(),
            workspace_root: workspace_uri.to_string(),
            capabilities: RwLock::new(ServerCapabilities::default()),
            raw_capabilities: RwLock::new(Value::Null),
            initialized: RwLock::new(false),
            service_ready: RwLock::new(server_name != "jdtls"),
            indexing_done: RwLock::new(server_name != "rust-analyzer"),
            active_progress_tokens: Mutex::new(HashSet::new()),
        });

        let reader_client = Arc::clone(&client);
        tokio::spawn(async move {
            reader_client.read_loop(stdout).await;
        });

        if let Some(stderr) = stderr {
            let name = server_name.to_string();
            tokio::spawn(async move {
                drain_stderr(stderr, &name).await;
            });
        }

        client.initialize(workspace_root, &workspace_uri, init_options).await?;

        Ok(client)
    }

    async fn initialize(&self, workspace_root: &Path, workspace_uri: &Uri, init_options: Option<Value>) -> Result<(), LspProtocolError> {
        let caps: ClientCapabilities = serde_json::from_value(get_client_capabilities())
            .map_err(LspProtocolError::Json)?;

        let workspace_name = workspace_root
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("workspace")
            .to_string();

        #[allow(deprecated)] // root_uri and root_path needed for older LSP servers
        let params = InitializeParams {
            process_id: Some(std::process::id()),
            root_uri: Some(workspace_uri.clone()),
            root_path: Some(workspace_root.display().to_string()),
            capabilities: caps,
            workspace_folders: Some(vec![WorkspaceFolder {
                uri: workspace_uri.clone(),
                name: workspace_name,
            }]),
            initialization_options: init_options,
            ..Default::default()
        };

        // Use raw request to preserve all capability fields including ones not in lsp-types
        let raw_result = self.send_request_raw("initialize", serde_json::to_value(params).unwrap()).await?;
        
        // Store raw capabilities for fields not in lsp-types ServerCapabilities struct
        // (e.g. typeHierarchyProvider was added in LSP 3.17 but lsp-types 0.97.0 omits it)
        if let Some(caps) = raw_result.get("capabilities") {
            *self.raw_capabilities.write().await = caps.clone();
        }
        
        let result: InitializeResult = serde_json::from_value(raw_result)
            .map_err(LspProtocolError::Json)?;
        *self.capabilities.write().await = result.capabilities;

        self.send_notification("initialized", InitializedParams {}).await?;
        *self.initialized.write().await = true;

        Ok(())
    }

    pub async fn send_request<P: serde::Serialize, R: serde::de::DeserializeOwned>(
        &self,
        method: &'static str,
        params: P,
    ) -> Result<R, LspProtocolError> {
        let id = self.request_id.fetch_add(1, Ordering::SeqCst);

        let request = JsonRpcRequest {
            jsonrpc: "2.0",
            id,
            method,
            params,
        };

        let (tx, rx) = oneshot::channel();
        self.pending_requests.insert(id, tx);

        let encoded = encode_message(&request);
        debug!("LSP REQUEST [{}] {}", id, method);

        {
            let mut stdin = self.stdin.lock().await;
            stdin.write_all(&encoded).await?;
            stdin.flush().await?;
        }

        let result = tokio::time::timeout(Duration::from_secs(REQUEST_TIMEOUT_SECS), rx)
            .await
            .map_err(|_| {
                self.pending_requests.remove(&id);
                LspProtocolError::Timeout(format!(
                    "Request {} timed out after {}s",
                    method, REQUEST_TIMEOUT_SECS
                ))
            })?
            .map_err(|_| LspProtocolError::ConnectionClosed)?;

        match result {
            Ok(value) => serde_json::from_value(value).map_err(LspProtocolError::Json),
            Err(e) => Err(LspProtocolError::Response(e)),
        }
    }

    pub async fn send_request_raw(
        &self,
        method: &'static str,
        params: Value,
    ) -> Result<Value, LspProtocolError> {
        let id = self.request_id.fetch_add(1, Ordering::SeqCst);

        let request = JsonRpcRequest {
            jsonrpc: "2.0",
            id,
            method,
            params,
        };

        let (tx, rx) = oneshot::channel();
        self.pending_requests.insert(id, tx);

        let encoded = encode_message(&request);
        debug!("LSP REQUEST [{}] {}", id, method);

        {
            let mut stdin = self.stdin.lock().await;
            stdin.write_all(&encoded).await?;
            stdin.flush().await?;
        }

        let result = tokio::time::timeout(Duration::from_secs(REQUEST_TIMEOUT_SECS), rx)
            .await
            .map_err(|_| {
                self.pending_requests.remove(&id);
                LspProtocolError::Timeout(format!(
                    "Request {} timed out after {}s",
                    method, REQUEST_TIMEOUT_SECS
                ))
            })?
            .map_err(|_| LspProtocolError::ConnectionClosed)?;

        result.map_err(LspProtocolError::Response)
    }

    pub async fn send_notification<P: serde::Serialize>(
        &self,
        method: &'static str,
        params: P,
    ) -> Result<(), LspProtocolError> {
        let notification = JsonRpcNotification {
            jsonrpc: "2.0",
            method,
            params,
        };

        let encoded = encode_message(&notification);
        debug!("LSP NOTIFICATION {}", method);

        let mut stdin = self.stdin.lock().await;
        stdin.write_all(&encoded).await?;
        stdin.flush().await?;

        Ok(())
    }

    async fn read_loop(&self, stdout: ChildStdout) {
        let mut reader = BufReader::new(stdout);

        loop {
            match read_message(&mut reader).await {
                Ok(message) => {
                    self.handle_message(message).await;
                }
                Err(LspProtocolError::ConnectionClosed) => {
                    debug!("LSP connection closed");
                    break;
                }
                Err(e) => {
                    error!("LSP read error: {}", e);
                    break;
                }
            }
        }

        let keys: Vec<u64> = self.pending_requests.iter().map(|e| *e.key()).collect();
        for key in keys {
            if let Some((_, tx)) = self.pending_requests.remove(&key) {
                let _ = tx.send(Err(LspResponseError {
                    code: -1,
                    message: "Connection closed".to_string(),
                    data: None,
                }));
            }
        }
    }

    async fn handle_message(&self, raw: Value) {
        let msg: IncomingMessage = match serde_json::from_value(raw) {
            Ok(m) => m,
            Err(e) => {
                warn!("Failed to parse incoming message: {}", e);
                return;
            }
        };

        match (&msg.id, &msg.method) {
            (Some(id), Some(method)) => {
                self.handle_server_request(id.clone(), method, msg.params).await;
            }
            (Some(id), None) => {
                let id_num = id.as_u64().unwrap_or_else(|| {
                    id.as_str().and_then(|s| s.parse().ok()).unwrap_or(0)
                });
                self.handle_response(id_num, msg.result, msg.error).await;
            }
            (None, Some(method)) => {
                self.handle_notification(method, msg.params).await;
            }
            (None, None) => {
                warn!("Received message with no id or method");
            }
        }
    }

    async fn handle_response(&self, id: u64, result: Option<Value>, error: Option<IncomingError>) {
        if let Some((_, tx)) = self.pending_requests.remove(&id) {
            if let Some(err) = error {
                debug!("LSP RESPONSE [{}] ERROR: {}", id, err.message);
                let _ = tx.send(Err(LspResponseError {
                    code: err.code as i32,
                    message: err.message,
                    data: err.data,
                }));
            } else {
                debug!("LSP RESPONSE [{}]: ok", id);
                let _ = tx.send(Ok(result.unwrap_or(Value::Null)));
            }
        } else {
            warn!("Received response for unknown request: {}", id);
        }
    }

    async fn handle_server_request(&self, id: Value, method: &str, params: Option<Value>) {
        debug!("Received server request: {} (id={:?})", method, id);

        let response = match method {
            "workspace/configuration" => {
                let items_count = params
                    .as_ref()
                    .and_then(|p| p.get("items"))
                    .and_then(|i| i.as_array())
                    .map(|a| a.len())
                    .unwrap_or(0);
                JsonRpcResponse {
                    jsonrpc: "2.0",
                    id,
                    result: Some(serde_json::to_value(vec![Value::Object(Default::default()); items_count]).unwrap()),
                    error: None,
                }
            }
            "window/workDoneProgress/create" | "client/registerCapability" => {
                JsonRpcResponse { jsonrpc: "2.0", id, result: Some(Value::Null), error: None }
            }
            "workspace/applyEdit" => {
                JsonRpcResponse {
                    jsonrpc: "2.0",
                    id,
                    result: Some(serde_json::json!({"applied": true})),
                    error: None,
                }
            }
            _ => {
                JsonRpcResponse {
                    jsonrpc: "2.0",
                    id,
                    result: None,
                    error: Some(JsonRpcError { code: -32601, message: format!("Method not found: {}", method) }),
                }
            }
        };

        let encoded = encode_message(&response);
        let mut stdin = self.stdin.lock().await;
        if let Err(e) = stdin.write_all(&encoded).await {
            error!("Failed to send server request response: {}", e);
        }
        let _ = stdin.flush().await;
    }

    async fn handle_notification(&self, method: &str, params: Option<Value>) {
        match method {
            "language/status" => {
                if let Some(p) = params.and_then(|v| serde_json::from_value::<LanguageStatusParams>(v).ok()) {
                    if p.status_type == "ServiceReady" {
                        info!("Server {} is now ServiceReady", self.server_name);
                        *self.service_ready.write().await = true;
                    }
                }
            }
            "experimental/serverStatus" => {
                if let Some(p) = params.and_then(|v| serde_json::from_value::<ServerStatusParams>(v).ok()) {
                    let quiescent = p.quiescent.unwrap_or(false);
                    let health = p.health.as_deref().unwrap_or("ok");
                    
                    if quiescent && health != "error" {
                        *self.indexing_done.write().await = true;
                        info!("Server {} is quiescent (ready)", self.server_name);
                    } else {
                        *self.indexing_done.write().await = false;
                    }
                }
            }
            "$/progress" => {
                if let Some(p) = params.and_then(|v| serde_json::from_value::<ProgressParams>(v).ok()) {
                    self.handle_progress(p).await;
                }
            }
            _ => {}
        }
    }

    async fn handle_progress(&self, params: ProgressParams) {
        let token = match &params.token {
            NumberOrString::Number(n) => n.to_string(),
            NumberOrString::String(s) => s.clone(),
        };

        let progress = match params.value {
            ProgressParamsValue::WorkDone(wd) => wd,
        };

        let mut tokens = self.active_progress_tokens.lock().await;
        match progress {
            WorkDoneProgress::Begin(_) => {
                tokens.insert(token);
                *self.indexing_done.write().await = false;
            }
            WorkDoneProgress::End(_) => {
                tokens.remove(&token);
                if tokens.is_empty() {
                    *self.indexing_done.write().await = true;
                }
            }
            WorkDoneProgress::Report(_) => {}
        }
    }

    pub async fn wait_for_indexing(&self, timeout_secs: u64) -> bool {
        let start = std::time::Instant::now();
        let timeout = Duration::from_secs(timeout_secs);

        loop {
            if *self.indexing_done.read().await {
                return true;
            }
            if start.elapsed() >= timeout {
                warn!(
                    "Timeout waiting for {} to finish indexing",
                    self.server_name
                );
                return false;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }

    pub async fn wait_for_service_ready(&self, timeout_secs: u64) -> bool {
        let start = std::time::Instant::now();
        let timeout = Duration::from_secs(timeout_secs);

        loop {
            if *self.service_ready.read().await {
                return true;
            }
            if start.elapsed() >= timeout {
                warn!(
                    "Timeout waiting for {} to become ServiceReady",
                    self.server_name
                );
                return false;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }

    pub async fn stop(&self) -> Result<(), LspProtocolError> {
        if *self.initialized.read().await {
            let _ = tokio::time::timeout(
                Duration::from_secs(5),
                self.send_request::<_, Value>("shutdown", ()),
            )
            .await;
            let _ = self.send_notification("exit", ()).await;
        }
        Ok(())
    }

    pub fn server_name(&self) -> &str {
        &self.server_name
    }

    pub fn workspace_root(&self) -> &str {
        &self.workspace_root
    }

    pub async fn capabilities(&self) -> ServerCapabilities {
        self.capabilities.read().await.clone()
    }

    pub async fn supports_call_hierarchy(&self) -> bool {
        let caps = self.capabilities.read().await;
        caps.call_hierarchy_provider.is_some()
    }

    pub async fn supports_type_hierarchy(&self) -> bool {
        // type_hierarchy_provider is not in lsp-types 0.97.0 ServerCapabilities struct,
        // but servers do advertise it. Check the raw_capabilities JSON.
        self.raw_capabilities.read().await
            .get("typeHierarchyProvider")
            .map(|v| !v.is_null())
            .unwrap_or(false)
    }

    pub async fn supports_declaration(&self) -> bool {
        let caps = self.capabilities.read().await;
        caps.declaration_provider.is_some()
    }

    pub async fn supports_implementation(&self) -> bool {
        let caps = self.capabilities.read().await;
        caps.implementation_provider.is_some()
    }

    pub async fn supports_references(&self) -> bool {
        let caps = self.capabilities.read().await;
        caps.references_provider.is_some()
    }

    pub async fn supports_rename(&self) -> bool {
        let caps = self.capabilities.read().await;
        caps.rename_provider.is_some()
    }

    pub fn pid(&self) -> Option<u32> {
        self.process.id()
    }
}
