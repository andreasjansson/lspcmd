#[tokio::main]
async fn main() -> anyhow::Result<()> {
    leta_daemon::run().await
}
