use fastrace::trace;
use std::collections::HashMap;
use std::path::PathBuf;

use leta_config::Config;
use leta_types::{
    CacheInfo, DescribeSessionParams, DescribeSessionResult, RemoveWorkspaceParams,
    RemoveWorkspaceResult, RestartWorkspaceParams, RestartWorkspaceResult, WorkspaceInfo,
};

use super::HandlerContext;

#[trace]
pub async fn handle_describe_session(
    ctx: &HandlerContext,
    _params: DescribeSessionParams,
) -> Result<DescribeSessionResult, String> {
    let mut caches = HashMap::new();
    
    let (hover_bytes, hover_entries) = ctx.hover_cache.stats();
    caches.insert("hover_cache".to_string(), CacheInfo {
        current_bytes: hover_bytes,
        max_bytes: ctx.hover_cache.max_bytes(),
        entries: hover_entries,
    });

    let (symbol_bytes, symbol_entries) = ctx.symbol_cache.stats();
    caches.insert("symbol_cache".to_string(), CacheInfo {
        current_bytes: symbol_bytes,
        max_bytes: ctx.symbol_cache.max_bytes(),
        entries: symbol_entries,
    });

    let workspaces = ctx.session.list_workspaces().await
        .into_iter()
        .map(|(root, language, server_pid, open_docs)| WorkspaceInfo {
            root,
            language,
            server_pid,
            open_documents: open_docs,
        })
        .collect();

    Ok(DescribeSessionResult {
        daemon_pid: std::process::id(),
        caches,
        workspaces,
    })
}

#[trace]
pub async fn handle_restart_workspace(
    ctx: &HandlerContext,
    params: RestartWorkspaceParams,
) -> Result<RestartWorkspaceResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let restarted = ctx.session.restart_workspace(&workspace_root).await?;
    
    Ok(RestartWorkspaceResult { restarted })
}

#[trace]
pub async fn handle_remove_workspace(
    ctx: &HandlerContext,
    params: RemoveWorkspaceParams,
) -> Result<RemoveWorkspaceResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    
    let mut config = Config::load().map_err(|e| e.to_string())?;
    config.remove_workspace_root(&workspace_root).map_err(|e| e.to_string())?;
    
    let servers_stopped = ctx.session.remove_workspace(&workspace_root).await?;
    
    Ok(RemoveWorkspaceResult { servers_stopped })
}
