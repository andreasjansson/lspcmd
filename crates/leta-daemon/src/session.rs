use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use fastrace::trace;
use leta_config::Config;
use leta_fs::{get_language_id, path_to_uri, read_file_content};
use leta_lsp::LspClient;
use leta_servers::{get_server_env, get_server_for_file, get_server_for_language, ServerConfig};
use serde_json::Value;
use tokio::sync::RwLock;
use tracing::{debug, info};

#[derive(Clone)]
pub struct OpenDocument {
    _uri: String,
    _version: i32,
    pub content: String,
    _language_id: String,
}

pub struct Workspace {
    root: PathBuf,
    server_config: &'static ServerConfig,
    client: Option<Arc<LspClient>>,
    open_documents: HashMap<String, OpenDocument>,
}

impl Workspace {
    pub fn new(root: PathBuf, server_config: &'static ServerConfig) -> Self {
        Self {
            root,
            server_config,
            client: None,
            open_documents: HashMap::new(),
        }
    }

    pub fn client(&self) -> Option<Arc<LspClient>> {
        self.client.clone()
    }

    pub fn server_name(&self) -> &str {
        self.server_config.name
    }

    pub fn open_document_uris(&self) -> Vec<String> {
        self.open_documents.keys().cloned().collect()
    }

    #[trace]
    pub async fn start_server(&mut self) -> Result<leta_types::ServerStartupStats, String> {
        let total_start = std::time::Instant::now();

        if self.client.is_some() {
            return Ok(leta_types::ServerStartupStats {
                server_name: self.server_config.name.to_string(),
                workspace_root: self.root.to_string_lossy().to_string(),
                start_time_ms: 0,
                init_time_ms: 0,
                ready_time_ms: 0,
                total_time_ms: 0,
            });
        }

        info!(
            "Starting {} for {}",
            self.server_config.name,
            self.root.display()
        );

        let env = get_server_env();
        let init_options = self.get_init_options();

        let cmd: Vec<&str> = self.server_config.command.iter().map(|s| *s).collect();

        let start_time = std::time::Instant::now();
        match LspClient::start(&cmd, &self.root, self.server_config.name, env, init_options).await {
            Ok(client) => {
                let init_time = start_time.elapsed();

                let ready_start = std::time::Instant::now();
                client.wait_for_indexing(60).await;
                let ready_time = ready_start.elapsed();

                if self.server_config.name == "clangd" {
                    self.ensure_workspace_indexed(&client).await;
                }

                self.client = Some(client);
                let total_time = total_start.elapsed();

                info!(
                    "Server {} initialized and ready in {:?}",
                    self.server_config.name, total_time
                );

                Ok(leta_types::ServerStartupStats {
                    server_name: self.server_config.name.to_string(),
                    workspace_root: self.root.to_string_lossy().to_string(),
                    start_time_ms: 0,
                    init_time_ms: init_time.as_millis() as u64,
                    ready_time_ms: ready_time.as_millis() as u64,
                    total_time_ms: total_time.as_millis() as u64,
                })
            }
            Err(e) => Err(format!(
                "Language server '{}' for {} failed to start in workspace {}: {}",
                self.server_config.name,
                self.server_config.languages.join(", "),
                self.root.display(),
                e
            )),
        }
    }

    fn get_init_options(&self) -> Option<Value> {
        if self.server_config.name == "gopls" {
            Some(serde_json::json!({
                "linksInHover": false,
            }))
        } else {
            None
        }
    }

    /// Open and close all source files to ensure clangd indexes them.
    ///
    /// clangd does lazy indexing - it only indexes files when they're opened.
    /// This means documentSymbol won't work on files that haven't been opened yet.
    /// We work around this by opening all source files during initialization.
    #[trace]
    async fn ensure_workspace_indexed(&mut self, client: &Arc<LspClient>) {
        let source_extensions = [".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hxx"];
        let exclude_dirs = ["build", ".git", "node_modules"];

        let mut files_to_index = Vec::new();
        for entry in walkdir::WalkDir::new(&self.root)
            .into_iter()
            .filter_entry(|e| {
                !exclude_dirs
                    .iter()
                    .any(|d| e.file_name().to_str() == Some(*d))
            })
            .filter_map(|e| e.ok())
        {
            if entry.file_type().is_file() {
                if let Some(ext) = entry.path().extension().and_then(|e| e.to_str()) {
                    if source_extensions
                        .iter()
                        .any(|s| s.trim_start_matches('.') == ext)
                    {
                        files_to_index.push(entry.path().to_path_buf());
                    }
                }
            }
        }

        if files_to_index.is_empty() {
            return;
        }

        info!("Pre-indexing {} files for clangd", files_to_index.len());

        for file_path in &files_to_index {
            let _ = self.ensure_document_open(file_path).await;
        }

        client.wait_for_indexing(30).await;

        info!(
            "Pre-indexing complete, closing {} documents",
            self.open_documents.len()
        );
        self.close_all_documents().await;
    }

    #[trace]
    pub async fn stop_server(&mut self) {
        if let Some(client) = self.client.take() {
            info!("Stopping {}", self.server_config.name);
            let _ = client.stop().await;
        }
        self.open_documents.clear();
    }

    #[trace]
    pub async fn ensure_document_open(&mut self, path: &Path) -> Result<(), String> {
        let uri = path_to_uri(path);

        if let Some(doc) = self.open_documents.get(&uri) {
            let current_content = read_file_content(path).map_err(|e| e.to_string())?;
            if current_content != doc.content {
                self.close_document(path).await;
            } else {
                return Ok(());
            }
        }

        let content = read_file_content(path).map_err(|e| e.to_string())?;
        let language_id = get_language_id(path).to_string();

        let doc = OpenDocument {
            _uri: uri.clone(),
            _version: 1,
            content: content.clone(),
            _language_id: language_id.clone(),
        };

        self.open_documents.insert(uri.clone(), doc);

        if let Some(client) = &self.client {
            let params = serde_json::json!({
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": 1,
                    "text": content,
                }
            });
            let _ = client
                .send_notification("textDocument/didOpen", params)
                .await;

            // ruby-lsp processes messages asynchronously in a queue, so we need to ensure
            // the didOpen is fully processed before subsequent operations can succeed.
            // We do this by sending a simple request and waiting for its response.
            if client.server_name() == "ruby-lsp" {
                let symbol_params = serde_json::json!({
                    "textDocument": {"uri": uri}
                });
                let _ = client
                    .send_request_raw("textDocument/documentSymbol", symbol_params)
                    .await;
            }
        }

        Ok(())
    }

    #[trace]
    pub async fn close_document(&mut self, path: &Path) {
        let uri = path_to_uri(path);
        if self.open_documents.remove(&uri).is_none() {
            return;
        }

        if let Some(client) = &self.client {
            let params = serde_json::json!({
                "textDocument": {"uri": uri}
            });
            let _ = client
                .send_notification("textDocument/didClose", params)
                .await;
        }
    }

    #[trace]
    pub async fn close_all_documents(&mut self) {
        if let Some(client) = &self.client {
            for uri in self.open_documents.keys() {
                let params = serde_json::json!({
                    "textDocument": {"uri": uri}
                });
                let _ = client
                    .send_notification("textDocument/didClose", params)
                    .await;
            }
        }
        self.open_documents.clear();
    }
}

pub struct Session {
    workspaces: RwLock<HashMap<PathBuf, HashMap<String, Workspace>>>,
    config: RwLock<Config>,
    indexing_stats: RwLock<Vec<leta_types::IndexingStats>>,
}

impl Session {
    pub fn new(config: Config) -> Self {
        Self {
            workspaces: RwLock::new(HashMap::new()),
            config: RwLock::new(config),
            indexing_stats: RwLock::new(Vec::new()),
        }
    }

    pub async fn add_indexing_stats(&self, stats: leta_types::IndexingStats) {
        let mut indexing_stats = self.indexing_stats.write().await;
        indexing_stats.retain(|s| s.workspace_root != stats.workspace_root);
        indexing_stats.push(stats);
    }

    pub async fn get_indexing_stats(&self) -> Vec<leta_types::IndexingStats> {
        self.indexing_stats.read().await.clone()
    }

    #[trace]
    pub async fn config(&self) -> Config {
        self.config.read().await.clone()
    }

    #[trace]
    pub async fn get_or_create_workspace(
        &self,
        file_path: &Path,
        workspace_root: &Path,
    ) -> Result<WorkspaceHandle<'_>, String> {
        let server_config = {
            let config = self.config.read().await;
            get_server_for_file(file_path, Some(&config))
                .ok_or_else(|| format!("No language server found for {}", file_path.display()))?
        };
        // config lock dropped here before acquiring workspace lock

        self.get_or_create_workspace_for_server(workspace_root, server_config)
            .await
    }

    #[trace]
    pub async fn get_or_create_workspace_for_language(
        &self,
        language_id: &str,
        workspace_root: &Path,
    ) -> Result<WorkspaceHandle<'_>, String> {
        let server_config = {
            let config = self.config.read().await;
            get_server_for_language(language_id, Some(&config))
                .ok_or_else(|| format!("No language server found for language {}", language_id))?
        };
        // config lock dropped here before acquiring workspace lock

        self.get_or_create_workspace_for_server(workspace_root, server_config)
            .await
    }

    #[trace]
    async fn get_or_create_workspace_for_server(
        &self,
        workspace_root: &Path,
        server_config: &'static ServerConfig,
    ) -> Result<WorkspaceHandle<'_>, String> {
        let workspace_root = workspace_root
            .canonicalize()
            .unwrap_or_else(|_| workspace_root.to_path_buf());

        debug!(
            "get_or_create_workspace_for_server: {} for {} - acquiring read lock",
            server_config.name,
            workspace_root.display()
        );

        // Check if workspace exists (read lock only)
        let needs_create = {
            let workspaces = self.workspaces.read().await;
            debug!("get_or_create_workspace_for_server: got read lock");
            if let Some(servers) = workspaces.get(&workspace_root) {
                if let Some(ws) = servers.get(server_config.name) {
                    ws.client.is_none() // needs restart
                } else {
                    true // needs create
                }
            } else {
                true // needs create
            }
        };
        debug!(
            "get_or_create_workspace_for_server: released read lock, needs_create={}",
            needs_create
        );

        if needs_create {
            debug!(
                "get_or_create_workspace_for_server: starting server {}",
                server_config.name
            );
            // Start server outside of lock to avoid blocking other operations
            let mut new_workspace = Workspace::new(workspace_root.clone(), server_config);
            new_workspace.start_server().await?;
            debug!("get_or_create_workspace_for_server: server started, acquiring write lock");

            // Now insert with write lock (quick operation)
            let mut workspaces = self.workspaces.write().await;
            debug!("get_or_create_workspace_for_server: got write lock");
            let servers = workspaces
                .entry(workspace_root.clone())
                .or_insert_with(HashMap::new);

            // Check again in case another task created it while we were starting
            if !servers.contains_key(server_config.name)
                || servers
                    .get(server_config.name)
                    .map(|w| w.client.is_none())
                    .unwrap_or(false)
            {
                servers.insert(server_config.name.to_string(), new_workspace);
            }
            debug!("get_or_create_workspace_for_server: releasing write lock");
        }

        Ok(WorkspaceHandle {
            session: self,
            workspace_root,
            server_name: server_config.name.to_string(),
        })
    }

    #[allow(dead_code)]
    #[trace]
    pub async fn get_workspace_for_file(&self, file_path: &Path) -> Option<WorkspaceHandle<'_>> {
        let file_path = file_path
            .canonicalize()
            .unwrap_or_else(|_| file_path.to_path_buf());
        let config = self.config.read().await;
        let server_config = get_server_for_file(&file_path, Some(&config))?;

        let workspaces = self.workspaces.read().await;
        for (root, servers) in workspaces.iter() {
            if file_path.starts_with(root) && servers.contains_key(server_config.name) {
                return Some(WorkspaceHandle {
                    session: self,
                    workspace_root: root.clone(),
                    server_name: server_config.name.to_string(),
                });
            }
        }
        None
    }

    #[trace]
    pub async fn list_workspaces(&self) -> Vec<(String, String, Option<u32>, Vec<String>)> {
        let workspaces = self.workspaces.read().await;
        let mut result = Vec::new();

        for (root, servers) in workspaces.iter() {
            for (_, ws) in servers.iter() {
                let server_pid = ws.client.as_ref().and_then(|c| c.pid());
                result.push((
                    root.to_string_lossy().to_string(),
                    ws.server_name().to_string(),
                    server_pid,
                    ws.open_document_uris(),
                ));
            }
        }

        result
    }

    #[trace]
    pub async fn restart_workspace(&self, root: &Path) -> Result<Vec<String>, String> {
        let root = root.canonicalize().unwrap_or_else(|_| root.to_path_buf());
        let mut workspaces = self.workspaces.write().await;

        let mut restarted = Vec::new();
        if let Some(servers) = workspaces.get_mut(&root) {
            for (name, workspace) in servers.iter_mut() {
                workspace.stop_server().await;
                workspace.start_server().await?;
                restarted.push(name.clone());
            }
        }
        Ok(restarted)
    }

    #[trace]
    pub async fn remove_workspace(&self, root: &Path) -> Result<Vec<String>, String> {
        let root = root.canonicalize().unwrap_or_else(|_| root.to_path_buf());
        let mut workspaces = self.workspaces.write().await;

        let mut stopped = Vec::new();
        if let Some(mut servers) = workspaces.remove(&root) {
            for (name, mut workspace) in servers.drain() {
                workspace.stop_server().await;
                stopped.push(name);
            }
        }
        Ok(stopped)
    }

    #[trace]
    pub async fn close_all(&self) {
        let mut workspaces = self.workspaces.write().await;
        for (_, mut servers) in workspaces.drain() {
            for (_, mut workspace) in servers.drain() {
                workspace.stop_server().await;
            }
        }
    }
}

pub struct WorkspaceHandle<'a> {
    session: &'a Session,
    workspace_root: PathBuf,
    server_name: String,
}

impl<'a> WorkspaceHandle<'a> {
    #[trace]
    pub async fn client(&self) -> Option<Arc<LspClient>> {
        let workspaces = self.session.workspaces.read().await;
        workspaces
            .get(&self.workspace_root)
            .and_then(|servers| servers.get(&self.server_name))
            .and_then(|ws| ws.client())
    }

    pub fn server_name(&self) -> &str {
        &self.server_name
    }

    #[trace]
    pub async fn wait_for_ready(&self, timeout_secs: u64) -> bool {
        if let Some(client) = self.client().await {
            client.wait_for_indexing(timeout_secs).await
        } else {
            false
        }
    }

    #[trace]
    pub async fn ensure_document_open(&self, path: &Path) -> Result<(), String> {
        let uri = path_to_uri(path);

        // First check if document needs updating (read lock only)
        let (needs_open, needs_reopen, client) = {
            let workspaces = self.session.workspaces.read().await;
            let workspace = workspaces
                .get(&self.workspace_root)
                .and_then(|servers| servers.get(&self.server_name))
                .ok_or_else(|| "Workspace not found".to_string())?;

            let client = workspace.client();

            if let Some(doc) = workspace.open_documents.get(&uri) {
                let current_content = read_file_content(path).map_err(|e| e.to_string())?;
                if current_content != doc.content {
                    (false, true, client) // needs reopen (close then open)
                } else {
                    (false, false, client) // already open with same content
                }
            } else {
                (true, false, client) // needs open
            }
        };

        if !needs_open && !needs_reopen {
            return Ok(());
        }

        // Close first if needed
        if needs_reopen {
            self.close_document(path).await;
        }

        // Read file content
        let content = read_file_content(path).map_err(|e| e.to_string())?;
        let language_id = get_language_id(path).to_string();

        // Insert document record (write lock, but no LSP call)
        {
            let mut workspaces = self.session.workspaces.write().await;
            let workspace = workspaces
                .get_mut(&self.workspace_root)
                .and_then(|servers| servers.get_mut(&self.server_name))
                .ok_or_else(|| "Workspace not found".to_string())?;

            let doc = OpenDocument {
                _uri: uri.clone(),
                _version: 1,
                content: content.clone(),
                _language_id: language_id.clone(),
            };
            workspace.open_documents.insert(uri.clone(), doc);
        }

        // Send LSP notification OUTSIDE the lock
        if let Some(client) = client {
            let params = serde_json::json!({
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": 1,
                    "text": content,
                }
            });
            let _ = client
                .send_notification("textDocument/didOpen", params)
                .await;

            // ruby-lsp processes messages asynchronously in a queue
            if client.server_name() == "ruby-lsp" {
                let symbol_params = serde_json::json!({
                    "textDocument": {"uri": uri}
                });
                let _ = client
                    .send_request_raw("textDocument/documentSymbol", symbol_params)
                    .await;
            }
        }

        Ok(())
    }

    #[trace]
    pub async fn close_document(&self, path: &Path) {
        tracing::trace!("WorkspaceHandle::close_document acquiring write lock");
        let mut workspaces = self.session.workspaces.write().await;
        if let Some(servers) = workspaces.get_mut(&self.workspace_root) {
            if let Some(workspace) = servers.get_mut(&self.server_name) {
                workspace.close_document(path).await;
            }
        }
        tracing::trace!("WorkspaceHandle::close_document releasing write lock");
    }

    #[trace]
    pub async fn is_document_open(&self, path: &Path) -> bool {
        let uri = path_to_uri(path);
        let workspaces = self.session.workspaces.read().await;
        if let Some(servers) = workspaces.get(&self.workspace_root) {
            if let Some(workspace) = servers.get(&self.server_name) {
                return workspace.open_documents.contains_key(&uri);
            }
        }
        false
    }

    #[trace]
    pub async fn notify_files_changed(
        &self,
        changes: &[(PathBuf, leta_lsp::lsp_types::FileChangeType)],
    ) {
        let client = match self.client().await {
            Some(c) => c,
            None => return,
        };

        let file_events: Vec<leta_lsp::lsp_types::FileEvent> = changes
            .iter()
            .map(|(path, change_type)| leta_lsp::lsp_types::FileEvent {
                uri: path_to_uri(path).parse().unwrap(),
                typ: *change_type,
            })
            .collect();

        let params = leta_lsp::lsp_types::DidChangeWatchedFilesParams {
            changes: file_events,
        };

        let _ = client
            .send_notification("workspace/didChangeWatchedFiles", params)
            .await;
    }
}
