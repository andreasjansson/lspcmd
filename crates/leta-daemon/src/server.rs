use std::sync::Arc;

use leta_cache::LMDBCache;
use leta_config::{get_pid_path, get_socket_path, Config};
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::broadcast;
use tracing::{error, info};

use crate::handlers::{HandlerContext, handle_request};
use crate::pidfile::{remove_pid, write_pid};
use crate::session::Session;

pub struct DaemonServer {
    session: Arc<Session>,
    hover_cache: Arc<LMDBCache>,
    symbol_cache: Arc<LMDBCache>,
    shutdown_tx: broadcast::Sender<()>,
}

impl DaemonServer {
    pub fn new(config: Config, hover_cache: LMDBCache, symbol_cache: LMDBCache) -> Self {
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

        let ctx = HandlerContext {
            session: Arc::clone(&self.session),
            hover_cache: Arc::clone(&self.hover_cache),
            symbol_cache: Arc::clone(&self.symbol_cache),
            shutdown_tx: self.shutdown_tx.clone(),
        };

        let response = handle_request(&ctx, method, params).await;

        stream.write_all(serde_json::to_vec(&response)?.as_slice()).await?;
        stream.shutdown().await?;

        Ok(())
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
