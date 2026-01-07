use leta_config::{get_cache_dir, get_log_dir, Config};
use tracing::info;
use tracing_subscriber::EnvFilter;

mod handlers;
mod server;
mod session;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let log_dir = get_log_dir();
    std::fs::create_dir_all(&log_dir)?;

    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("daemon.log"))?;

    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env().add_directive("info".parse().unwrap()))
        .with_writer(log_file)
        .with_ansi(false)
        .init();

    let config = Config::load()?;

    let cache_dir = get_cache_dir();
    std::fs::create_dir_all(&cache_dir)?;

    let hover_cache_size = config.daemon.hover_cache_size;
    let symbol_cache_size = config.daemon.symbol_cache_size;

    let hover_cache = leta_cache::LmdbCache::new(&cache_dir.join("hover_cache.lmdb"), hover_cache_size)?;
    let symbol_cache = leta_cache::LmdbCache::new(&cache_dir.join("symbol_cache.lmdb"), symbol_cache_size)?;

    let daemon = server::DaemonServer::new(config, hover_cache, symbol_cache);
    
    info!("Starting leta daemon");
    daemon.run().await?;

    Ok(())
}
