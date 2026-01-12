use fastrace::trace;
use leta_config::{get_cache_dir, get_log_dir, Config, DaemonLock};
use tracing::info;
use tracing_subscriber::EnvFilter;

mod handlers;
mod profiling;
mod server;
mod session;

#[tokio::main]
#[trace]
async fn main() -> anyhow::Result<()> {
    let log_dir = get_log_dir();
    std::fs::create_dir_all(&log_dir)?;

    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("daemon.log"))?;

    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));

    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_writer(log_file)
        .with_ansi(false)
        .init();

    let _lock = match DaemonLock::acquire() {
        Some(lock) => lock,
        None => {
            info!("Another daemon instance is already running, exiting");
            return Ok(());
        }
    };

    let mut config = Config::load()?;
    let removed = config.cleanup_stale_workspace_roots();
    if !removed.is_empty() {
        info!("Cleaned up {} stale workspace roots", removed.len());
    }

    let cache_dir = get_cache_dir();
    std::fs::create_dir_all(&cache_dir)?;

    let hover_cache_size = config.daemon.hover_cache_size;
    let symbol_cache_size = config.daemon.symbol_cache_size;

    let hover_cache =
        leta_cache::LmdbCache::new(&cache_dir.join("hover_cache.lmdb"), hover_cache_size)?;
    let symbol_cache =
        leta_cache::LmdbCache::new(&cache_dir.join("symbol_cache.lmdb"), symbol_cache_size)?;

    let daemon = server::DaemonServer::new(config, hover_cache, symbol_cache);

    info!("Starting leta daemon");
    daemon.run().await?;

    Ok(())
}
