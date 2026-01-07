use std::sync::Arc;

use leta_cache::LmdbCache;
use leta_config::{get_pid_path, get_socket_path, write_pid, remove_pid};
use leta_types::*;
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::broadcast;
use tracing::{error, info};

use crate::handlers::{
    HandlerContext, handle_grep, handle_show, handle_references, handle_declaration,
    handle_implementations, handle_subtypes, handle_supertypes, handle_calls,
    handle_rename, handle_move_file, handle_files, handle_resolve_symbol,
    handle_describe_session, handle_shutdown, handle_restart_workspace, handle_remove_workspace,
};
use crate::session::Session;

pub struct DaemonServer {
    session: Arc<Session>,
    hover_cache: Arc<LmdbCache>,
    symbol_cache: Arc<LmdbCache>,
    shutdown_tx: broadcast::Sender<()>,
}

impl DaemonServer {
    pub fn new(config: Value, hover_cache: LmdbCache, symbol_cache: LmdbCache) -> Self {
        let (shutdown_tx, _) = broadcast::channel(1);
        Self {
            session: Arc::new(Session::new(config)),
            hover_cache: Arc::new(hover_cache),
            symbol_cache: Arc::new(symbol_cache),
            shutdown_tx,
        }
    }

    pub async fn run(self) -> anyhow::Result<()> {
        let socket_path = get_socket_path();
        let pid_path = get_pid_path();

        if let Some(parent) = socket_path.parent() {
            std::fs::create_dir_all(parent)?;
        }

        if socket_path.exists() {
            std::fs::remove_file(&socket_path)?;
        }

        let listener = UnixListener::bind(&socket_path)?;
        write_pid(&pid_path, std::process::id())?;

        info!("Daemon started, listening on {}", socket_path.display());

        let mut shutdown_rx = self.shutdown_tx.subscribe();
        let server = Arc::new(self);

        loop {
            tokio::select! {
                result = listener.accept() => {
                    match result {
                        Ok((stream, _)) => {
                            let server = Arc::clone(&server);
                            tokio::spawn(async move {
                                if let Err(e) = server.handle_client(stream).await {
                                    error!("Error handling client: {}", e);
                                }
                            });
                        }
                        Err(e) => {
                            error!("Accept error: {}", e);
                        }
                    }
                }
                _ = shutdown_rx.recv() => {
                    info!("Shutdown signal received");
                    break;
                }
                _ = tokio::signal::ctrl_c() => {
                    info!("Ctrl-C received, shutting down");
                    break;
                }
            }
        }

        server.shutdown().await;
        Ok(())
    }

    async fn handle_client(&self, mut stream: UnixStream) -> anyhow::Result<()> {
        let mut data = Vec::new();
        stream.read_to_end(&mut data).await?;

        if data.is_empty() {
            return Ok(());
        }

        let request: Value = serde_json::from_slice(&data)?;
        let method = request.get("method").and_then(|m| m.as_str()).unwrap_or("");
        let params = request.get("params").cloned().unwrap_or(json!({}));

        let ctx = HandlerContext::new(
            Arc::clone(&self.session),
            Arc::clone(&self.hover_cache),
            Arc::clone(&self.symbol_cache),
        );

        let response = self.dispatch(&ctx, method, params).await;

        stream.write_all(serde_json::to_vec(&response)?.as_slice()).await?;
        stream.shutdown().await?;

        Ok(())
    }

    async fn dispatch(&self, ctx: &HandlerContext, method: &str, params: Value) -> Value {
        match method {
            "grep" => self.handle::<GrepParams, GrepResult>(ctx, params, handle_grep).await,
            "show" => self.handle::<ShowParams, _>(ctx, params, handle_show).await,
            "references" => self.handle::<ReferencesParams, ReferencesResult>(ctx, params, handle_references).await,
            "declaration" => self.handle::<DeclarationParams, DeclarationResult>(ctx, params, handle_declaration).await,
            "implementations" => self.handle::<ImplementationsParams, ImplementationsResult>(ctx, params, handle_implementations).await,
            "subtypes" => self.handle::<SubtypesParams, SubtypesResult>(ctx, params, handle_subtypes).await,
            "supertypes" => self.handle::<SupertypesParams, SupertypesResult>(ctx, params, handle_supertypes).await,
            "calls" => self.handle::<CallsParams, CallsResult>(ctx, params, handle_calls).await,
            "rename" => self.handle::<RenameParams, RenameResult>(ctx, params, handle_rename).await,
            "move-file" => self.handle::<MoveFileParams, MoveFileResult>(ctx, params, handle_move_file).await,
            "files" => self.handle::<FilesParams, FilesResult>(ctx, params, handle_files).await,
            "resolve-symbol" => self.handle::<ResolveSymbolParams, ResolveSymbolResult>(ctx, params, handle_resolve_symbol).await,
            "describe-session" => self.handle::<DescribeSessionParams, DescribeSessionResult>(ctx, params, handle_describe_session).await,
            "restart-workspace" => self.handle::<RestartWorkspaceParams, RestartWorkspaceResult>(ctx, params, handle_restart_workspace).await,
            "remove-workspace" => self.handle::<RemoveWorkspaceParams, RemoveWorkspaceResult>(ctx, params, handle_remove_workspace).await,
            "shutdown" => {
                let _ = self.shutdown_tx.send(());
                json!({"result": {"status": "shutting_down"}})
            }
            "raw-lsp-request" => {
                json!({"error": "raw-lsp-request not yet implemented"})
            }
            _ => json!({"error": format!("Unknown method: {}", method)}),
        }
    }

    async fn handle<P, R, F, Fut>(&self, ctx: &HandlerContext, params: Value, handler: F) -> Value
    where
        P: serde::de::DeserializeOwned,
        R: serde::Serialize,
        F: FnOnce(&HandlerContext, P) -> Fut,
        Fut: std::future::Future<Output = Result<R, String>>,
    {
        let typed_params: P = match serde_json::from_value(params) {
            Ok(p) => p,
            Err(e) => return json!({"error": format!("Invalid params: {}", e)}),
        };

        match handler(ctx, typed_params).await {
            Ok(result) => json!({"result": result}),
            Err(e) => json!({"error": e}),
        }
    }

    async fn shutdown(&self) {
        info!("Shutting down daemon");
        self.session.close_all().await;

        let socket_path = get_socket_path();
        if socket_path.exists() {
            let _ = std::fs::remove_file(&socket_path);
        }

        remove_pid(&get_pid_path());
    }
}
