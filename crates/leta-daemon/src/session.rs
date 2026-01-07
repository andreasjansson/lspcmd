use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use leta_config::Config;
use leta_fs::{get_language_id, path_to_uri, read_file_content};
use leta_lsp::LspClient;
use leta_servers::{get_server_env, get_server_for_file, get_server_for_language, ServerConfig};
use tokio::sync::RwLock;
use tracing::info;

#[derive(Clone)]
#[allow(dead_code)]
pub struct OpenDocument {
    pub uri: String,
    pub version: i32,
    pub content: String,
    pub language_id: String,
}

pub struct Workspace {
    pub root: PathBuf,
    pub server_config: &'static ServerConfig,
    pub client: Option<Arc<LspClient>>,
    pub open_documents: HashMap<String, OpenDocument>,
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

    pub async fn start_server(&mut self) -> Result<(), String> {
        if self.client.is_some() {
            return Ok(());
        }

        info!("Starting {} for {}", self.server_config.name, self.root.display());

        let env = get_server_env();
        let init_options = self.get_init_options();

        let cmd: Vec<&str> = self.server_config.command.iter().map(|s| *s).collect();

        match LspClient::start(&cmd, &self.root, self.server_config.name, env, init_options).await {
            Ok(client) => {
                client.wait_for_indexing(60).await;
                
                if self.server_config.name == "clangd" {
                    self.ensure_workspace_indexed(&client).await;
                }
                
                self.client = Some(client);
                info!("Server {} initialized and ready", self.server_config.name);
                Ok(())
            }
            Err(e) => {
                Err(format!(
                    "Language server '{}' for {} failed to start in workspace {}: {}",
                    self.server_config.name,
                    self.server_config.languages.join(", "),
                    self.root.display(),
                    e
                ))
            }
        }
    }

    fn get_init_options(&self) -> Option<serde_json::Value> {
        if self.server_config.name == "gopls" {
            Some(serde_json::json!({
                "linksInHover": false,
            }))
        } else {
            None
        }
    }

    async fn ensure_workspace_indexed(&mut self, client: &Arc<LspClient>) {
        let source_extensions = [".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hxx"];
        let exclude_dirs = ["build", ".git", "node_modules"];

        let mut files_to_index = Vec::new();
        for entry in walkdir::WalkDir::new(&self.root)
            .into_iter()
            .filter_entry(|e| {
                !exclude_dirs.iter().any(|d| e.file_name().to_str() == Some(*d))
            })
            .filter_map(|e| e.ok())
        {
            if entry.file_type().is_file() {
                if let Some(ext) = entry.path().extension().and_then(|e| e.to_str()) {
                    if source_extensions.iter().any(|s| s.trim_start_matches('.') == ext) {
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

        info!("Pre-indexing complete, closing {} documents", self.open_documents.len());
        self.close_all_documents().await;
    }

    pub async fn stop_server(&mut self) {
        if let Some(client) = self.client.take() {
            info!("Stopping {}", self.server_config.name);
            let _ = client.stop().await;
        }
        self.open_documents.clear();
    }

    pub async fn ensure_document_open(&mut self, path: &Path) -> Result<OpenDocument, String> {
        let uri = path_to_uri(path);

        if let Some(doc) = self.open_documents.get(&uri) {
            let current_content = read_file_content(path).map_err(|e| e.to_string())?;
            if current_content != doc.content {
                self.close_document(path).await;
            } else {
                return Ok(doc.clone());
            }
        }

        let content = read_file_content(path).map_err(|e| e.to_string())?;
        let language_id = get_language_id(path).to_string();
        
        let doc = OpenDocument {
            uri: uri.clone(),
            version: 1,
            content: content.clone(),
            language_id: language_id.clone(),
        };
        
        self.open_documents.insert(uri.clone(), doc.clone());

        if let Some(client) = &self.client {
            let params = serde_json::json!({
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": 1,
                    "text": content,
                }
            });
            let _ = client.send_notification("textDocument/didOpen", params).await;

            if client.server_name() == "ruby-lsp" {
                let symbol_params = serde_json::json!({
                    "textDocument": {"uri": uri}
                });
                let _ = client.send_request_raw("textDocument/documentSymbol", symbol_params).await;
            }
        }

        Ok(doc)
    }

    pub async fn close_document(&mut self, path: &Path) {
        let uri = path_to_uri(path);
        if self.open_documents.remove(&uri).is_none() {
            return;
        }

        if let Some(client) = &self.client {
            let params = serde_json::json!({
                "textDocument": {"uri": uri}
            });
            let _ = client.send_notification("textDocument/didClose", params).await;
        }
    }

    pub async fn close_all_documents(&mut self) {
        if let Some(client) = &self.client {
            for uri in self.open_documents.keys() {
                let params = serde_json::json!({
                    "textDocument": {"uri": uri}
                });
                let _ = client.send_notification("textDocument/didClose", params).await;
            }
        }
        self.open_documents.clear();
    }
}

pub struct Session {
    pub workspaces: RwLock<HashMap<PathBuf, HashMap<String, Workspace>>>,
    pub config: RwLock<Config>,
}

impl Session {
    pub fn new(config: Config) -> Self {
        Self {
            workspaces: RwLock::new(HashMap::new()),
            config: RwLock::new(config),
        }
    }

    pub async fn get_or_create_workspace(
        &self,
        file_path: &Path,
        workspace_root: &Path,
    ) -> Result<(), String> {
        let config = self.config.read().await;
        let server_config = get_server_for_file(file_path, Some(&*config))
            .ok_or_else(|| format!("No language server found for {}", file_path.display()))?;

        self.get_or_create_workspace_for_server(workspace_root, server_config).await
    }

    pub async fn get_or_create_workspace_for_language(
        &self,
        language_id: &str,
        workspace_root: &Path,
    ) -> Result<(), String> {
        let config = self.config.read().await;
        let server_config = get_server_for_language(language_id, Some(&*config))
            .ok_or_else(|| format!("No language server found for language {}", language_id))?;

        self.get_or_create_workspace_for_server(workspace_root, server_config).await
    }

    async fn get_or_create_workspace_for_server(
        &self,
        workspace_root: &Path,
        server_config: &'static ServerConfig,
    ) -> Result<(), String> {
        let workspace_root = workspace_root.canonicalize().unwrap_or_else(|_| workspace_root.to_path_buf());

        let mut workspaces = self.workspaces.write().await;
        let servers = workspaces.entry(workspace_root.clone()).or_insert_with(HashMap::new);

        if let Some(ws) = servers.get_mut(server_config.name) {
            if ws.client.is_none() {
                ws.start_server().await?;
            }
            return Ok(());
        }

        let mut workspace = Workspace::new(workspace_root.clone(), server_config);
        workspace.start_server().await?;
        servers.insert(server_config.name.to_string(), workspace);

        Ok(())
    }

    pub async fn get_workspace_client(
        &self,
        file_path: &Path,
        workspace_root: &Path,
    ) -> Option<Arc<LspClient>> {
        let config = self.config.read().await;
        let server_config = get_server_for_file(file_path, Some(&*config))?;
        let workspace_root = workspace_root.canonicalize().unwrap_or_else(|_| workspace_root.to_path_buf());

        let workspaces = self.workspaces.read().await;
        let servers = workspaces.get(&workspace_root)?;
        let workspace = servers.get(server_config.name)?;
        workspace.client.clone()
    }

    pub async fn get_workspace_client_for_language(
        &self,
        language_id: &str,
        workspace_root: &Path,
    ) -> Option<Arc<LspClient>> {
        let config = self.config.read().await;
        let server_config = get_server_for_language(language_id, Some(&*config))?;
        let workspace_root = workspace_root.canonicalize().unwrap_or_else(|_| workspace_root.to_path_buf());

        let workspaces = self.workspaces.read().await;
        let servers = workspaces.get(&workspace_root)?;
        let workspace = servers.get(server_config.name)?;
        workspace.client.clone()
    }

    pub async fn ensure_document_open(
        &self,
        file_path: &Path,
        workspace_root: &Path,
    ) -> Result<OpenDocument, String> {
        let config = self.config.read().await;
        let server_config = get_server_for_file(file_path, Some(&*config))
            .ok_or_else(|| format!("No language server found for {}", file_path.display()))?;
        let workspace_root = workspace_root.canonicalize().unwrap_or_else(|_| workspace_root.to_path_buf());

        let mut workspaces = self.workspaces.write().await;
        let servers = workspaces.get_mut(&workspace_root)
            .ok_or_else(|| format!("Workspace not found: {}", workspace_root.display()))?;
        let workspace = servers.get_mut(server_config.name)
            .ok_or_else(|| format!("Server {} not found in workspace", server_config.name))?;

        workspace.ensure_document_open(file_path).await
    }

    pub async fn close_document(&self, file_path: &Path, workspace_root: &Path) {
        let config = self.config.read().await;
        let Some(server_config) = get_server_for_file(file_path, Some(&*config)) else {
            return;
        };
        let workspace_root = workspace_root.canonicalize().unwrap_or_else(|_| workspace_root.to_path_buf());

        let mut workspaces = self.workspaces.write().await;
        if let Some(servers) = workspaces.get_mut(&workspace_root) {
            if let Some(workspace) = servers.get_mut(server_config.name) {
                workspace.close_document(file_path).await;
            }
        }
    }

    pub async fn close_workspace(&self, root: &Path) -> Vec<String> {
        let root = root.canonicalize().unwrap_or_else(|_| root.to_path_buf());
        let mut workspaces = self.workspaces.write().await;
        
        let mut stopped = Vec::new();
        if let Some(mut servers) = workspaces.remove(&root) {
            for (name, mut workspace) in servers.drain() {
                workspace.stop_server().await;
                stopped.push(name);
            }
        }
        stopped
    }

    pub async fn restart_workspace(&self, root: &Path) -> Vec<String> {
        let root = root.canonicalize().unwrap_or_else(|_| root.to_path_buf());
        let mut workspaces = self.workspaces.write().await;
        
        let mut restarted = Vec::new();
        if let Some(servers) = workspaces.get_mut(&root) {
            for (name, workspace) in servers.iter_mut() {
                workspace.stop_server().await;
                if workspace.start_server().await.is_ok() {
                    restarted.push(name.clone());
                }
            }
        }
        restarted
    }

    pub async fn close_all(&self) {
        let mut workspaces = self.workspaces.write().await;
        for (_, mut servers) in workspaces.drain() {
            for (_, mut workspace) in servers.drain() {
                workspace.stop_server().await;
            }
        }
    }

    pub async fn describe(&self) -> serde_json::Value {
        let workspaces = self.workspaces.read().await;
        let mut ws_list = Vec::new();

        for (root, servers) in workspaces.iter() {
            for (name, ws) in servers.iter() {
                let server_pid = ws.client.as_ref().and_then(|c| c.pid());
                ws_list.push(serde_json::json!({
                    "root": root.to_string_lossy(),
                    "language": name,
                    "server_pid": server_pid,
                    "open_documents": ws.open_documents.keys().collect::<Vec<_>>(),
                }));
            }
        }

        serde_json::json!({"workspaces": ws_list})
    }
}
