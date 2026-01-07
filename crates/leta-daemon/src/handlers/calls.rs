use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::Arc;

use leta_fs::uri_to_path;
use leta_lsp::lsp_types::{
    CallHierarchyIncomingCall, CallHierarchyIncomingCallsParams, CallHierarchyItem,
    CallHierarchyOutgoingCall, CallHierarchyOutgoingCallsParams, CallHierarchyPrepareParams,
    Position, TextDocumentIdentifier, TextDocumentPositionParams,
};
use leta_lsp::LspClient;
use leta_types::{CallNode, CallsMode, CallsParams, CallsResult, SymbolKind};

use super::{relative_path, HandlerContext};

pub async fn handle_calls(
    ctx: &HandlerContext,
    params: CallsParams,
) -> Result<CallsResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);

    match params.mode {
        CallsMode::Outgoing => {
            let from_path = params.from_path.ok_or("from_path required for outgoing mode")?;
            let from_line = params.from_line.ok_or("from_line required for outgoing mode")?;
            let from_column = params.from_column.unwrap_or(0);

            let file_path = PathBuf::from(&from_path);
            let workspace = ctx.session.get_or_create_workspace(&file_path, &workspace_root).await
                .map_err(|e| e.to_string())?;
            
            workspace.ensure_document_open(&file_path).await?;
            let client = workspace.client().await.ok_or("No LSP client")?;

            let items = prepare_call_hierarchy(client.clone(), &file_path, from_line, from_column).await?;
            if items.is_empty() {
                return Ok(CallsResult {
                    message: Some("No call hierarchy item found at location".to_string()),
                    root: None,
                    path: None,
                    error: None,
                });
            }

            let item = &items[0];
            let mut visited = HashSet::new();
            let calls = collect_outgoing_calls(
                client.clone(),
                item,
                &workspace_root,
                0,
                params.max_depth,
                params.include_non_workspace,
                &mut visited,
            ).await;

            let root = call_hierarchy_item_to_node(item, &workspace_root);
            Ok(CallsResult {
                root: Some(CallNode {
                    calls: Some(calls),
                    ..root
                }),
                path: None,
                message: None,
                error: None,
            })
        }

        CallsMode::Incoming => {
            let to_path = params.to_path.ok_or("to_path required for incoming mode")?;
            let to_line = params.to_line.ok_or("to_line required for incoming mode")?;
            let to_column = params.to_column.unwrap_or(0);

            let file_path = PathBuf::from(&to_path);
            let workspace = ctx.session.get_or_create_workspace(&file_path, &workspace_root).await
                .map_err(|e| e.to_string())?;
            
            workspace.ensure_document_open(&file_path).await?;
            let client = workspace.client().await.ok_or("No LSP client")?;

            let items = prepare_call_hierarchy(client.clone(), &file_path, to_line, to_column).await?;
            if items.is_empty() {
                return Ok(CallsResult {
                    message: Some("No call hierarchy item found at location".to_string()),
                    root: None,
                    path: None,
                    error: None,
                });
            }

            let item = &items[0];
            let mut visited = HashSet::new();
            let called_by = collect_incoming_calls(
                client.clone(),
                item,
                &workspace_root,
                0,
                params.max_depth,
                params.include_non_workspace,
                &mut visited,
            ).await;

            let root = call_hierarchy_item_to_node(item, &workspace_root);
            Ok(CallsResult {
                root: Some(CallNode {
                    called_by: Some(called_by),
                    ..root
                }),
                path: None,
                message: None,
                error: None,
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

            let workspace = ctx.session.get_or_create_workspace(&from_file, &workspace_root).await
                .map_err(|e| e.to_string())?;
            
            workspace.ensure_document_open(&from_file).await?;
            workspace.ensure_document_open(&to_file).await?;
            let client = workspace.client().await.ok_or("No LSP client")?;

            let from_items = prepare_call_hierarchy(client.clone(), &from_file, from_line, from_column).await?;
            let to_items = prepare_call_hierarchy(client.clone(), &to_file, to_line, to_column).await?;

            if from_items.is_empty() || to_items.is_empty() {
                return Ok(CallsResult {
                    message: Some("Could not find call hierarchy items".to_string()),
                    root: None,
                    path: None,
                    error: None,
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
            ).await;

            match path {
                Some(p) => Ok(CallsResult {
                    path: Some(p),
                    root: None,
                    message: None,
                    error: None,
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
                }),
            }
        }
    }
}

async fn prepare_call_hierarchy(
    client: Arc<LspClient>,
    file_path: &PathBuf,
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
                    text_document: TextDocumentIdentifier { uri: uri.parse().unwrap() },
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
    format!("{}:{}:{}", item.uri.as_str(), item.range.start.line, item.name)
}

fn is_stdlib_path(uri: &str) -> bool {
    uri.contains("/typeshed-fallback/stdlib/")
        || uri.contains("/typeshed/stdlib/")
        || (uri.contains("/libexec/src/") && !uri.contains("/mod/"))
        || (uri.ends_with(".d.ts") && uri.split('/').last().map(|f| f.starts_with("lib.")).unwrap_or(false))
        || uri.contains("/rustlib/src/rust/library/")
}

async fn collect_outgoing_calls(
    client: Arc<LspClient>,
    item: &CallHierarchyItem,
    workspace_root: &PathBuf,
    current_depth: u32,
    max_depth: u32,
    include_non_workspace: bool,
    visited: &mut HashSet<String>,
) -> Vec<CallNode> {
    if current_depth >= max_depth {
        return vec![];
    }

    let key = item_key(item);
    if visited.contains(&key) {
        return vec![];
    }
    visited.insert(key);

    let response: Result<Option<Vec<CallHierarchyOutgoingCall>>, _> = client
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
        
        if !include_non_workspace && is_stdlib_path(call_item.uri.as_str()) {
            continue;
        }

        let mut node = call_hierarchy_item_to_node(call_item, workspace_root);
        
        let children = Box::pin(collect_outgoing_calls(
            client.clone(),
            call_item,
            workspace_root,
            current_depth + 1,
            max_depth,
            include_non_workspace,
            visited,
        )).await;

        if !children.is_empty() {
            node.calls = Some(children);
        }

        result.push(node);
    }

    result
}

async fn collect_incoming_calls(
    client: Arc<LspClient>,
    item: &CallHierarchyItem,
    workspace_root: &PathBuf,
    current_depth: u32,
    max_depth: u32,
    include_non_workspace: bool,
    visited: &mut HashSet<String>,
) -> Vec<CallNode> {
    if current_depth >= max_depth {
        return vec![];
    }

    let key = item_key(item);
    if visited.contains(&key) {
        return vec![];
    }
    visited.insert(key);

    let response: Result<Option<Vec<CallHierarchyIncomingCall>>, _> = client
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
        
        if !include_non_workspace && is_stdlib_path(call_item.uri.as_str()) {
            continue;
        }

        let mut node = call_hierarchy_item_to_node(call_item, workspace_root);
        
        let children = Box::pin(collect_incoming_calls(
            client.clone(),
            call_item,
            workspace_root,
            current_depth + 1,
            max_depth,
            include_non_workspace,
            visited,
        )).await;

        if !children.is_empty() {
            node.called_by = Some(children);
        }

        result.push(node);
    }

    result
}

async fn find_call_path(
    client: Arc<LspClient>,
    item: &CallHierarchyItem,
    target_key: &str,
    workspace_root: &PathBuf,
    current_depth: u32,
    max_depth: u32,
    include_non_workspace: bool,
    visited: &mut HashSet<String>,
) -> Option<Vec<CallNode>> {
    if current_depth >= max_depth {
        return None;
    }

    let key = item_key(item);
    if visited.contains(&key) {
        return None;
    }
    visited.insert(key.clone());

    let current_node = call_hierarchy_item_to_node(item, workspace_root);

    if key == target_key {
        return Some(vec![current_node]);
    }

    let response: Result<Option<Vec<CallHierarchyOutgoingCall>>, _> = client
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
        
        if !include_non_workspace && is_stdlib_path(call_item.uri.as_str()) {
            continue;
        }

        if let Some(mut path) = Box::pin(find_call_path(
            client.clone(),
            call_item,
            target_key,
            workspace_root,
            current_depth + 1,
            max_depth,
            include_non_workspace,
            visited,
        )).await {
            path.insert(0, current_node);
            return Some(path);
        }
    }

    None
}

fn call_hierarchy_item_to_node(item: &CallHierarchyItem, workspace_root: &PathBuf) -> CallNode {
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
