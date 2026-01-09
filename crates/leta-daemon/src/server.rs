use fastrace::trace;
use std::sync::Arc;

use fastrace::collector::Config as FastraceConfig;
use fastrace::prelude::*;
use leta_cache::LmdbCache;
use leta_config::{get_pid_path, get_socket_path, remove_pid, write_pid, Config};
use leta_types::*;
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::broadcast;
use tracing::{error, info};

use crate::handlers::{
    handle_add_workspace, handle_calls, handle_declaration, handle_describe_session, handle_files,
    handle_grep, handle_implementations, handle_move_file, handle_references,
    handle_remove_workspace, handle_rename, handle_resolve_symbol, handle_restart_workspace,
    handle_show, handle_subtypes, handle_supertypes, HandlerContext,
};
use crate::profiling::CollectingReporter;
use crate::session::Session;

pub struct DaemonServer {
    session: Arc<Session>,
    hover_cache: Arc<LmdbCache>,
    symbol_cache: Arc<LmdbCache>,
    shutdown_tx: broadcast::Sender<()>,
}

impl DaemonServer {
    pub fn new(config: Config, hover_cache: LmdbCache, symbol_cache: LmdbCache) -> Self {
        let (shutdown_tx, _) = broadcast::channel(1);
        Self {
            session: Arc::new(Session::new(config)),
            hover_cache: Arc::new(hover_cache),
            symbol_cache: Arc::new(symbol_cache),
            shutdown_tx,
        }
    }

    #[trace]
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

    #[trace]
    async fn handle_client(&self, mut stream: UnixStream) -> anyhow::Result<()> {
        let start = std::time::Instant::now();
        let mut data = Vec::new();
        stream.read_to_end(&mut data).await?;
        tracing::info!("read_to_end took {:?}", start.elapsed());

        if data.is_empty() {
            return Ok(());
        }

        let request: Value = serde_json::from_slice(&data)?;
        let method = request.get("method").and_then(|m| m.as_str()).unwrap_or("");
        let params = request.get("params").cloned().unwrap_or(json!({}));
        let profile = request
            .get("profile")
            .and_then(|p| p.as_bool())
            .unwrap_or(false);

        let ctx = HandlerContext::new(
            Arc::clone(&self.session),
            Arc::clone(&self.hover_cache),
            Arc::clone(&self.symbol_cache),
        );

        tracing::info!("Starting dispatch for {} at {:?}", method, start.elapsed());
        let response = if profile {
            self.dispatch_with_profiling(&ctx, method, params).await
        } else {
            self.dispatch(&ctx, method, params).await
        };
        tracing::info!("Dispatch for {} completed at {:?}", method, start.elapsed());

        stream
            .write_all(serde_json::to_vec(&response)?.as_slice())
            .await?;
        stream.shutdown().await?;
        tracing::info!("Response written at {:?}", start.elapsed());

        Ok(())
    }

    #[trace]
    async fn dispatch_with_profiling(
        &self,
        ctx: &HandlerContext,
        method: &str,
        params: Value,
    ) -> Value {
        let (reporter, collector) = CollectingReporter::new();
        fastrace::set_reporter(reporter, FastraceConfig::default());

        ctx.cache_stats.reset();

        let method_owned: &'static str = Box::leak(method.to_string().into_boxed_str());
        let root = Span::root(method_owned, SpanContext::random());

        let mut response = self.dispatch(ctx, method, params).in_span(root).await;

        fastrace::flush();

        let functions = collector.collect_and_aggregate();
        let cache = ctx.cache_stats.to_cache_stats();

        if let Some(obj) = response.as_object_mut() {
            if obj.contains_key("result") {
                let profiling = leta_types::ProfilingData { functions, cache };
                obj.insert(
                    "profiling".to_string(),
                    serde_json::to_value(&profiling).unwrap(),
                );
            }
        }

        response
    }

    #[trace]
    async fn dispatch(&self, ctx: &HandlerContext, method: &str, params: Value) -> Value {
        macro_rules! handle {
            ($params_ty:ty, $handler:expr) => {{
                match serde_json::from_value::<$params_ty>(params) {
                    Ok(p) => match $handler(ctx, p).await {
                        Ok(result) => json!({"result": result}),
                        Err(e) => json!({"error": e}),
                    },
                    Err(e) => json!({"error": format!("Invalid params: {}", e)}),
                }
            }};
        }

        match method {
            "grep" => handle!(GrepParams, handle_grep),
            "show" => handle!(ShowParams, handle_show),
            "references" => handle!(ReferencesParams, handle_references),
            "declaration" => handle!(DeclarationParams, handle_declaration),
            "implementations" => handle!(ImplementationsParams, handle_implementations),
            "subtypes" => handle!(SubtypesParams, handle_subtypes),
            "supertypes" => handle!(SupertypesParams, handle_supertypes),
            "calls" => handle!(CallsParams, handle_calls),
            "rename" => handle!(RenameParams, handle_rename),
            "move-file" => handle!(MoveFileParams, handle_move_file),
            "files" => handle!(FilesParams, handle_files),
            "resolve-symbol" => handle!(ResolveSymbolParams, handle_resolve_symbol),
            "describe-session" => handle!(DescribeSessionParams, handle_describe_session),
            "restart-workspace" => handle!(RestartWorkspaceParams, handle_restart_workspace),
            "remove-workspace" => handle!(RemoveWorkspaceParams, handle_remove_workspace),
            "add-workspace" => handle!(AddWorkspaceParams, handle_add_workspace),
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

    #[trace]
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
