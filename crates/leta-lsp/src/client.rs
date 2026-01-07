use std::collections::HashSet;
use std::path::Path;
use std::process::Stdio;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use lsp_types::{
    ClientCapabilities, InitializeParams, InitializeResult, InitializedParams,
    ServerCapabilities, Uri, WorkspaceFolder,
};
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStderr, ChildStdin, ChildStdout};
use tokio::sync::{oneshot, Mutex, RwLock};
use tracing::{debug, error, info, warn};

use crate::capabilities::get_client_capabilities;
use crate::protocol::{encode_message, read_message, LspProtocolError, LspResponseError};

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

        let result: InitializeResult = self.send_request("initialize", params).await?;
        *self.capabilities.write().await = result.capabilities;

        self.send_notification("initialized", InitializedParams {}).await?;
        *self.initialized.write().await = true;

        Ok(())
    }

    pub async fn send_request<P: serde::Serialize, R: serde::de::DeserializeOwned>(
        &self,
        method: &str,
        params: P,
    ) -> Result<R, LspProtocolError> {
        let id = self.request_id.fetch_add(1, Ordering::SeqCst);

        let message = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params,
        });

        let (tx, rx) = oneshot::channel();
        self.pending_requests.insert(id, tx);

        let encoded = encode_message(&message);
        if method != "initialize" {
            debug!("LSP REQUEST [{}] {} params={}", id, method, serde_json::to_string(&message.get("params")).unwrap_or_default());
        } else {
            debug!("LSP REQUEST [{}] {}", id, method);
        }

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
            Ok(value) => {
                serde_json::from_value(value).map_err(LspProtocolError::Json)
            }
            Err(e) => Err(LspProtocolError::Response(e)),
        }
    }

    pub async fn send_request_raw(
        &self,
        method: &str,
        params: Value,
    ) -> Result<Value, LspProtocolError> {
        let id = self.request_id.fetch_add(1, Ordering::SeqCst);

        let message = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params,
        });

        let (tx, rx) = oneshot::channel();
        self.pending_requests.insert(id, tx);

        let encoded = encode_message(&message);
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
        method: &str,
        params: P,
    ) -> Result<(), LspProtocolError> {
        let message = json!({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        });

        let encoded = encode_message(&message);
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

    async fn handle_message(&self, message: Value) {
        if let Some(id) = message.get("id") {
            if message.get("method").is_some() {
                self.handle_server_request(message).await;
            } else {
                let id_num = id.as_u64().unwrap_or_else(|| {
                    if let Some(id_str) = id.as_str() {
                        id_str.parse().unwrap_or(0)
                    } else {
                        0
                    }
                });
                debug!("Processing response for id={}", id_num);
                self.handle_response(id_num, message).await;
            }
        } else {
            self.handle_notification(message).await;
        }
    }

    async fn handle_response(&self, id: u64, message: Value) {
        if let Some((_, tx)) = self.pending_requests.remove(&id) {
            if let Some(error) = message.get("error") {
                let code = error.get("code").and_then(|c| c.as_i64()).unwrap_or(-1) as i32;
                let msg = error
                    .get("message")
                    .and_then(|m| m.as_str())
                    .unwrap_or("Unknown error")
                    .to_string();
                let data = error.get("data").cloned();
                debug!("LSP RESPONSE [{}] ERROR: {}", id, msg);
                let _ = tx.send(Err(LspResponseError {
                    code,
                    message: msg,
                    data,
                }));
            } else {
                let result = message.get("result").cloned().unwrap_or(Value::Null);
                debug!("LSP RESPONSE [{}]: {:?}", id, result.as_str().unwrap_or("..."));
                let _ = tx.send(Ok(result));
            }
        } else {
            warn!("Received response for unknown request: {}", id);
        }
    }

    async fn handle_server_request(&self, message: Value) {
        let method = message
            .get("method")
            .and_then(|m| m.as_str())
            .unwrap_or("");
        let id = message.get("id").cloned().unwrap_or(Value::Null);

        debug!("Received server request: {} (id={:?})", method, id);

        let (result, error): (Option<Value>, Option<Value>) = match method {
            "workspace/configuration" => {
                let items_count = message
                    .get("params")
                    .and_then(|p| p.get("items"))
                    .and_then(|i| i.as_array())
                    .map(|a| a.len())
                    .unwrap_or(0);
                (Some(json!(vec![json!({}); items_count])), None)
            }
            "window/workDoneProgress/create" => (Some(Value::Null), None),
            "client/registerCapability" => (Some(Value::Null), None),
            "workspace/applyEdit" => (Some(json!({"applied": true})), None),
            _ => (
                None,
                Some(json!({
                    "code": -32601,
                    "message": format!("Method not found: {}", method)
                })),
            ),
        };

        let response = if let Some(err) = error {
            json!({
                "jsonrpc": "2.0",
                "id": id,
                "error": err
            })
        } else {
            json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": result.unwrap_or(Value::Null)
            })
        };

        let encoded = encode_message(&response);
        let mut stdin = self.stdin.lock().await;
        if let Err(e) = stdin.write_all(&encoded).await {
            error!("Failed to send server request response: {}", e);
        }
        let _ = stdin.flush().await;
    }

    async fn handle_notification(&self, message: Value) {
        let method = message
            .get("method")
            .and_then(|m| m.as_str())
            .unwrap_or("");
        let params = message.get("params");

        debug!("Received notification: {}", method);

        match method {
            "language/status" => {
                if let Some(params) = params {
                    if params.get("type").and_then(|t| t.as_str()) == Some("ServiceReady") {
                        info!("Server {} is now ServiceReady", self.server_name);
                        *self.service_ready.write().await = true;
                    }
                }
            }
            "experimental/serverStatus" => {
                if let Some(params) = params {
                    let quiescent = params.get("quiescent").and_then(|q| q.as_bool()).unwrap_or(false);
                    let health = params.get("health").and_then(|h| h.as_str()).unwrap_or("ok");
                    
                    if quiescent && health != "error" {
                        *self.indexing_done.write().await = true;
                        info!("Server {} is quiescent (ready)", self.server_name);
                    } else {
                        *self.indexing_done.write().await = false;
                        debug!("Server {} is busy (not quiescent)", self.server_name);
                    }
                }
            }
            "$/progress" => {
                if let Some(params) = params {
                    self.handle_progress(params).await;
                }
            }
            _ => {}
        }
    }

    async fn handle_progress(&self, params: &Value) {
        let token = params
            .get("token")
            .and_then(|t| t.as_str().map(String::from).or_else(|| t.as_u64().map(|n| n.to_string())));
        let kind = params
            .get("value")
            .and_then(|v| v.get("kind"))
            .and_then(|k| k.as_str());

        if let (Some(token), Some(kind)) = (token, kind) {
            let mut tokens = self.active_progress_tokens.lock().await;
            match kind {
                "begin" => {
                    tokens.insert(token.clone());
                    *self.indexing_done.write().await = false;
                    debug!("Progress begin: {}", token);
                }
                "end" => {
                    tokens.remove(&token);
                    if tokens.is_empty() {
                        *self.indexing_done.write().await = true;
                        debug!("All progress complete, server ready");
                    } else {
                        debug!("Progress end: {}, {} remaining", token, tokens.len());
                    }
                }
                _ => {}
            }
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

    pub fn pid(&self) -> Option<u32> {
        self.process.id()
    }
}
