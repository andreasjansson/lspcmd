use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use fastrace::trace;
use leta_fs::uri_to_path;
use leta_lsp::lsp_types::{
    CallHierarchyIncomingCall, CallHierarchyIncomingCallsParams, CallHierarchyItem,
    CallHierarchyOutgoingCall, CallHierarchyOutgoingCallsParams, CallHierarchyPrepareParams,
    Position, TextDocumentIdentifier, TextDocumentPositionParams,
};
use leta_lsp::LspClient;
use leta_types::{CallNode, CallsMode, CallsParams, CallsResult, SymbolKind};

use super::{relative_path, HandlerContext};

#[trace]
pub async fn handle_calls(
    ctx: &HandlerContext,
    params: CallsParams,
) -> Result<CallsResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);

    match params.mode {
        CallsMode::Outgoing => {
            let from_path = params
                .from_path
                .ok_or("from_path required for outgoing mode")?;
            let from_line = params
                .from_line
                .ok_or("from_line required for outgoing mode")?;
            let from_column = params.from_column.unwrap_or(0);

            let file_path = PathBuf::from(&from_path);
            let workspace = ctx
                .session
                .get_or_create_workspace(&file_path, &workspace_root)
                .await
                .map_err(|e| e.to_string())?;

            workspace.ensure_document_open(&file_path).await?;
            let client = workspace.client().await.ok_or("No LSP client")?;

            // Wait for indexing to complete to prevent rust-analyzer "content modified" errors
            client.wait_for_indexing(30).await;

            let items =
                prepare_call_hierarchy(client.clone(), &file_path, from_line, from_column).await?;
            if items.is_empty() {
                return Ok(CallsResult {
                    message: Some("No call hierarchy item found at location".to_string()),
                    root: None,
                    path: None,
                    error: None,
                    truncated: false,
                });
            }

            let item = &items[0];
            let mut visited = HashSet::new();
            let mut ctx = CallTraversalContext {
                client: client.clone(),
                workspace_root: &workspace_root,
                max_depth: params.max_depth,
                include_non_workspace: params.include_non_workspace,
                visited: &mut visited,
            };
            let calls = collect_outgoing_calls(&mut ctx, item, 0).await;

            let root = call_hierarchy_item_to_node(item, &workspace_root);
            Ok(CallsResult {
                root: Some(CallNode {
                    calls: Some(calls),
                    ..root
                }),
                path: None,
                message: None,
                error: None,
                truncated: false,
            })
        }

        CallsMode::Incoming => {
            let to_path = params.to_path.ok_or("to_path required for incoming mode")?;
            let to_line = params.to_line.ok_or("to_line required for incoming mode")?;
            let to_column = params.to_column.unwrap_or(0);

            let file_path = PathBuf::from(&to_path);
            let workspace = ctx
                .session
                .get_or_create_workspace(&file_path, &workspace_root)
                .await
                .map_err(|e| e.to_string())?;

            workspace.ensure_document_open(&file_path).await?;
            let client = workspace.client().await.ok_or("No LSP client")?;

            // Wait for indexing to complete to prevent rust-analyzer "content modified" errors
            client.wait_for_indexing(30).await;

            let items =
                prepare_call_hierarchy(client.clone(), &file_path, to_line, to_column).await?;
            if items.is_empty() {
                return Ok(CallsResult {
                    message: Some("No call hierarchy item found at location".to_string()),
                    root: None,
                    path: None,
                    error: None,
                    truncated: false,
                });
            }

            let item = &items[0];
            let mut visited = HashSet::new();
            let mut ctx = CallTraversalContext {
                client: client.clone(),
                workspace_root: &workspace_root,
                max_depth: params.max_depth,
                include_non_workspace: params.include_non_workspace,
                visited: &mut visited,
            };
            let called_by = collect_incoming_calls(&mut ctx, item, 0).await;

            let root = call_hierarchy_item_to_node(item, &workspace_root);
            Ok(CallsResult {
                root: Some(CallNode {
                    called_by: Some(called_by),
                    ..root
                }),
                path: None,
                message: None,
                error: None,
                truncated: false,
            })
        }

        CallsMode::Path => {
            let from_path = params.from_path.ok_or("from_path required for path mode")?;
            let from_line = params.from_line.ok_or("from_line required for path mode")?;
            let from_column = params.from_column.unwrap_or(0);
            let to_path = params.to_path.ok_or("to_path required for path mode")?;
            let to_line = params.to_line.ok_or("to_line required for path mode")?;
            let to_column = params.to_column.unwrap_or(0);

            let from_file = PathBuf::from(&from_path);
            let to_file = PathBuf::from(&to_path);

            let workspace = ctx
                .session
                .get_or_create_workspace(&from_file, &workspace_root)
                .await
                .map_err(|e| e.to_string())?;

            workspace.ensure_document_open(&from_file).await?;
            workspace.ensure_document_open(&to_file).await?;
            let client = workspace.client().await.ok_or("No LSP client")?;

            // Wait for indexing to complete to prevent rust-analyzer "content modified" errors
            client.wait_for_indexing(30).await;

            let from_items =
                prepare_call_hierarchy(client.clone(), &from_file, from_line, from_column).await?;
            let to_items =
                prepare_call_hierarchy(client.clone(), &to_file, to_line, to_column).await?;

            if from_items.is_empty() || to_items.is_empty() {
                return Ok(CallsResult {
                    message: Some("Could not find call hierarchy items".to_string()),
                    root: None,
                    path: None,
                    error: None,
                    truncated: false,
                });
            }

            let target_key = item_key(&to_items[0]);
            let mut visited = HashSet::new();

            let path = find_call_path(
                client.clone(),
                &from_items[0],
                &target_key,
                &workspace_root,
                0,
                params.max_depth,
                params.include_non_workspace,
                &mut visited,
            )
            .await;

            match path {
                Some(p) => Ok(CallsResult {
                    path: Some(p),
                    root: None,
                    message: None,
                    error: None,
                    truncated: false,
                }),
                None => Ok(CallsResult {
                    message: Some(format!(
                        "No call path found from '{}' to '{}' within depth {}",
                        params.from_symbol.unwrap_or_default(),
                        params.to_symbol.unwrap_or_default(),
                        params.max_depth
                    )),
                    root: None,
                    path: None,
                    error: None,
                    truncated: false,
                }),
            }
        }
    }
}

#[trace]
async fn prepare_call_hierarchy(
    client: Arc<LspClient>,
    file_path: &Path,
    line: u32,
    column: u32,
) -> Result<Vec<CallHierarchyItem>, String> {
    if !client.supports_call_hierarchy().await {
        return Err(format!(
            "textDocument/prepareCallHierarchy is not supported by {}",
            client.server_name()
        ));
    }

    let uri = leta_fs::path_to_uri(file_path);

    let response: Option<Vec<CallHierarchyItem>> = client
        .send_request(
            "textDocument/prepareCallHierarchy",
            CallHierarchyPrepareParams {
                text_document_position_params: TextDocumentPositionParams {
                    text_document: TextDocumentIdentifier {
                        uri: uri.parse().unwrap(),
                    },
                    position: Position {
                        line: line - 1,
                        character: column,
                    },
                },
                work_done_progress_params: Default::default(),
            },
        )
        .await
        .map_err(|e| format!("{}", e))?;

    Ok(response.unwrap_or_default())
}

fn item_key(item: &CallHierarchyItem) -> String {
    format!(
        "{}:{}:{}",
        item.uri.as_str(),
        item.range.start.line,
        item.name
    )
}

/// Check if a URI path is within the workspace (not external like stdlib).
/// This is more robust than pattern matching specific stdlib paths.
fn is_path_in_workspace(uri: &str, workspace_root: &Path) -> bool {
    let file_path = leta_fs::uri_to_path(uri);

    match file_path.strip_prefix(workspace_root) {
        Ok(rel_path) => {
            let excluded_dirs = [
                ".venv",
                "venv",
                "node_modules",
                "vendor",
                ".git",
                "__pycache__",
                "target",
                "build",
                "dist",
            ];
            !rel_path
                .iter()
                .any(|part| excluded_dirs.iter().any(|d| part.to_str() == Some(*d)))
        }
        Err(_) => false,
    }
}

struct CallTraversalContext<'a> {
    client: Arc<LspClient>,
    workspace_root: &'a Path,
    max_depth: u32,
    include_non_workspace: bool,
    visited: &'a mut HashSet<String>,
}

#[trace]
async fn collect_outgoing_calls(
    ctx: &mut CallTraversalContext<'_>,
    item: &CallHierarchyItem,
    current_depth: u32,
) -> Vec<CallNode> {
    if current_depth >= ctx.max_depth {
        return vec![];
    }

    let key = item_key(item);
    if ctx.visited.contains(&key) {
        return vec![];
    }
    ctx.visited.insert(key);

    let response: Result<Option<Vec<CallHierarchyOutgoingCall>>, _> = ctx
        .client
        .send_request(
            "callHierarchy/outgoingCalls",
            CallHierarchyOutgoingCallsParams {
                item: item.clone(),
                work_done_progress_params: Default::default(),
                partial_result_params: Default::default(),
            },
        )
        .await;

    let calls = match response {
        Ok(Some(calls)) => calls,
        _ => return vec![],
    };

    let mut result = Vec::new();
    for call in calls {
        let call_item = &call.to;

        if !ctx.include_non_workspace
            && !is_path_in_workspace(call_item.uri.as_str(), ctx.workspace_root)
        {
            continue;
        }

        let mut node = call_hierarchy_item_to_node(call_item, ctx.workspace_root);

        let children = Box::pin(collect_outgoing_calls(ctx, call_item, current_depth + 1)).await;

        if !children.is_empty() {
            node.calls = Some(children);
        }

        result.push(node);
    }

    result
}

#[trace]
async fn collect_incoming_calls(
    ctx: &mut CallTraversalContext<'_>,
    item: &CallHierarchyItem,
    current_depth: u32,
) -> Vec<CallNode> {
    if current_depth >= ctx.max_depth {
        return vec![];
    }

    let key = item_key(item);
    if ctx.visited.contains(&key) {
        return vec![];
    }
    ctx.visited.insert(key);

    let response: Result<Option<Vec<CallHierarchyIncomingCall>>, _> = ctx
        .client
        .send_request(
            "callHierarchy/incomingCalls",
            CallHierarchyIncomingCallsParams {
                item: item.clone(),
                work_done_progress_params: Default::default(),
                partial_result_params: Default::default(),
            },
        )
        .await;

    let calls = match response {
        Ok(Some(calls)) => calls,
        _ => return vec![],
    };

    let mut result = Vec::new();
    for call in calls {
        let call_item = &call.from;

        if !ctx.include_non_workspace
            && !is_path_in_workspace(call_item.uri.as_str(), ctx.workspace_root)
        {
            continue;
        }

        let mut node = call_hierarchy_item_to_node(call_item, ctx.workspace_root);

        let children = Box::pin(collect_incoming_calls(ctx, call_item, current_depth + 1)).await;

        if !children.is_empty() {
            node.called_by = Some(children);
        }

        result.push(node);
    }

    result
}

struct FindCallPathContext<'a> {
    client: Arc<LspClient>,
    workspace_root: &'a Path,
    target_key: &'a str,
    max_depth: u32,
    include_non_workspace: bool,
    visited: &'a mut HashSet<String>,
}

#[trace]
async fn find_call_path(
    ctx: &mut FindCallPathContext<'_>,
    item: &CallHierarchyItem,
    current_depth: u32,
) -> Option<Vec<CallNode>> {
    if current_depth >= ctx.max_depth {
        return None;
    }

    let key = item_key(item);
    if ctx.visited.contains(&key) {
        return None;
    }
    ctx.visited.insert(key.clone());

    let current_node = call_hierarchy_item_to_node(item, ctx.workspace_root);

    if key == ctx.target_key {
        return Some(vec![current_node]);
    }

    let response: Result<Option<Vec<CallHierarchyOutgoingCall>>, _> = ctx
        .client
        .send_request(
            "callHierarchy/outgoingCalls",
            CallHierarchyOutgoingCallsParams {
                item: item.clone(),
                work_done_progress_params: Default::default(),
                partial_result_params: Default::default(),
            },
        )
        .await;

    let calls = match response {
        Ok(Some(calls)) => calls,
        _ => return None,
    };

    for call in calls {
        let call_item = &call.to;

        if !ctx.include_non_workspace
            && !is_path_in_workspace(call_item.uri.as_str(), ctx.workspace_root)
        {
            continue;
        }

        if let Some(mut path) = Box::pin(find_call_path(ctx, call_item, current_depth + 1)).await {
            path.insert(0, current_node);
            return Some(path);
        }
    }

    None
}

fn call_hierarchy_item_to_node(item: &CallHierarchyItem, workspace_root: &Path) -> CallNode {
    let file_path = uri_to_path(item.uri.as_str());
    let rel_path = relative_path(&file_path, workspace_root);
    let kind = SymbolKind::from_lsp(item.kind);

    CallNode {
        name: item.name.clone(),
        kind: Some(kind.to_string()),
        detail: item.detail.clone(),
        path: Some(rel_path),
        line: Some(item.selection_range.start.line + 1),
        column: Some(item.selection_range.start.character),
        calls: None,
        called_by: None,
    }
}
