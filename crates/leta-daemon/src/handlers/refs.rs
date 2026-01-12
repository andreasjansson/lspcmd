use std::path::PathBuf;

use fastrace::trace;
use leta_lsp::lsp_types::{
    GotoDefinitionParams, GotoDefinitionResponse, Location, Position, ReferenceContext,
    ReferenceParams, TextDocumentIdentifier, TextDocumentPositionParams,
    TypeHierarchyPrepareParams,
};
use leta_types::{
    DeclarationParams, DeclarationResult, ImplementationsParams, ImplementationsResult,
    LocationInfo, ReferencesParams, ReferencesResult, SubtypesParams, SubtypesResult,
    SupertypesParams, SupertypesResult,
};

use super::{format_locations, format_type_hierarchy_items_from_json, HandlerContext};

#[trace]
pub async fn handle_references(
    ctx: &HandlerContext,
    params: ReferencesParams,
) -> Result<ReferencesResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let file_path = PathBuf::from(&params.path);

    let workspace = ctx
        .session
        .get_or_create_workspace(&file_path, &workspace_root)
        .await
        .map_err(|e| e.to_string())?;

    workspace.ensure_document_open(&file_path).await?;
    let client = workspace.client().await.ok_or("No LSP client")?;
    let uri = leta_fs::path_to_uri(&file_path);

    let response: Option<Vec<Location>> = client
        .send_request(
            "textDocument/references",
            ReferenceParams {
                text_document_position: TextDocumentPositionParams {
                    text_document: TextDocumentIdentifier {
                        uri: uri.parse().unwrap(),
                    },
                    position: Position {
                        line: params.line - 1,
                        character: params.column,
                    },
                },
                work_done_progress_params: Default::default(),
                partial_result_params: Default::default(),
                context: ReferenceContext {
                    include_declaration: true,
                },
            },
        )
        .await
        .map_err(|e| e.to_string())?;

    let all_locations = response.unwrap_or_default();
    let total_count = all_locations.len() as u32;
    let truncated = total_count > params.head;
    let limited_locations: Vec<_> = all_locations
        .into_iter()
        .take(params.head as usize)
        .collect();
    let locations = format_locations(&limited_locations, &workspace_root, params.context);

    Ok(ReferencesResult {
        locations,
        truncated,
        total_count: if truncated { Some(total_count) } else { None },
    })
}

#[trace]
pub async fn handle_declaration(
    ctx: &HandlerContext,
    params: DeclarationParams,
) -> Result<DeclarationResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let file_path = PathBuf::from(&params.path);

    let workspace = ctx
        .session
        .get_or_create_workspace(&file_path, &workspace_root)
        .await
        .map_err(|e| e.to_string())?;

    workspace.ensure_document_open(&file_path).await?;
    let client = workspace.client().await.ok_or("No LSP client")?;

    if !client.supports_declaration().await {
        return Err(format!(
            "textDocument/declaration is not supported by {}",
            workspace.server_name()
        ));
    }

    let uri = leta_fs::path_to_uri(&file_path);

    let response: Option<GotoDefinitionResponse> = client
        .send_request(
            "textDocument/declaration",
            GotoDefinitionParams {
                text_document_position_params: TextDocumentPositionParams {
                    text_document: TextDocumentIdentifier {
                        uri: uri.parse().unwrap(),
                    },
                    position: Position {
                        line: params.line - 1,
                        character: params.column,
                    },
                },
                work_done_progress_params: Default::default(),
                partial_result_params: Default::default(),
            },
        )
        .await
        .map_err(|e| format!("{}", e))?;

    let locations = response
        .map(|resp| definition_response_to_locations(&resp, &workspace_root, params.context))
        .unwrap_or_default();

    Ok(DeclarationResult { locations })
}

#[trace]
pub async fn handle_implementations(
    ctx: &HandlerContext,
    params: ImplementationsParams,
) -> Result<ImplementationsResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let file_path = PathBuf::from(&params.path);

    let workspace = ctx
        .session
        .get_or_create_workspace(&file_path, &workspace_root)
        .await
        .map_err(|e| e.to_string())?;

    workspace.ensure_document_open(&file_path).await?;
    let client = workspace.client().await.ok_or("No LSP client")?;

    let supports = client.supports_implementation().await;
    tracing::debug!(
        "handle_implementations: server={} supports_implementation={}",
        workspace.server_name(),
        supports
    );

    if !supports {
        return Err(format!(
            "Server '{}' does not support implementations (may require a license)",
            workspace.server_name()
        ));
    }

    let uri = leta_fs::path_to_uri(&file_path);

    let response: Option<GotoDefinitionResponse> = client
        .send_request(
            "textDocument/implementation",
            GotoDefinitionParams {
                text_document_position_params: TextDocumentPositionParams {
                    text_document: TextDocumentIdentifier {
                        uri: uri.parse().unwrap(),
                    },
                    position: Position {
                        line: params.line - 1,
                        character: params.column,
                    },
                },
                work_done_progress_params: Default::default(),
                partial_result_params: Default::default(),
            },
        )
        .await
        .map_err(|e| format!("{}", e))?;

    let locations = response
        .map(|resp| definition_response_to_locations(&resp, &workspace_root, params.context))
        .unwrap_or_default();

    Ok(ImplementationsResult {
        locations,
        error: None,
    })
}

#[trace]
pub async fn handle_subtypes(
    ctx: &HandlerContext,
    params: SubtypesParams,
) -> Result<SubtypesResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let file_path = PathBuf::from(&params.path);

    let workspace = ctx
        .session
        .get_or_create_workspace(&file_path, &workspace_root)
        .await
        .map_err(|e| e.to_string())?;

    workspace.ensure_document_open(&file_path).await?;
    let client = workspace.client().await.ok_or("No LSP client")?;

    if !client.supports_type_hierarchy().await {
        return Err(format!(
            "textDocument/prepareTypeHierarchy is not supported by {}",
            workspace.server_name()
        ));
    }

    let uri = leta_fs::path_to_uri(&file_path);

    // Use serde_json::Value for prepareTypeHierarchy to work around lsp-types bug
    // where tags is incorrectly typed as Option<SymbolTag> instead of Option<Vec<SymbolTag>>
    let prepare_response: Option<Vec<serde_json::Value>> = client
        .send_request(
            "textDocument/prepareTypeHierarchy",
            TypeHierarchyPrepareParams {
                text_document_position_params: TextDocumentPositionParams {
                    text_document: TextDocumentIdentifier {
                        uri: uri.parse().unwrap(),
                    },
                    position: Position {
                        line: params.line - 1,
                        character: params.column,
                    },
                },
                work_done_progress_params: Default::default(),
            },
        )
        .await
        .map_err(|e| format!("{}", e))?;

    let items = match prepare_response {
        Some(items) if !items.is_empty() => items,
        _ => return Ok(SubtypesResult { locations: vec![] }),
    };

    // Send subtypes request with just the item field (no extra params that jdtls doesn't expect)
    let subtypes_response: Option<Vec<serde_json::Value>> = client
        .send_request(
            "typeHierarchy/subtypes",
            serde_json::json!({ "item": items[0] }),
        )
        .await
        .map_err(|e| format!("{}", e))?;

    let locations = subtypes_response
        .map(|items| format_type_hierarchy_items_from_json(&items, &workspace_root, params.context))
        .unwrap_or_default();

    Ok(SubtypesResult { locations })
}

#[trace]
pub async fn handle_supertypes(
    ctx: &HandlerContext,
    params: SupertypesParams,
) -> Result<SupertypesResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let file_path = PathBuf::from(&params.path);

    let workspace = ctx
        .session
        .get_or_create_workspace(&file_path, &workspace_root)
        .await
        .map_err(|e| e.to_string())?;

    workspace.ensure_document_open(&file_path).await?;
    let client = workspace.client().await.ok_or("No LSP client")?;

    if !client.supports_type_hierarchy().await {
        return Err(format!(
            "textDocument/prepareTypeHierarchy is not supported by {}",
            workspace.server_name()
        ));
    }

    let uri = leta_fs::path_to_uri(&file_path);

    // Use serde_json::Value to work around lsp-types bug with tags field
    let prepare_response: Option<Vec<serde_json::Value>> = client
        .send_request(
            "textDocument/prepareTypeHierarchy",
            TypeHierarchyPrepareParams {
                text_document_position_params: TextDocumentPositionParams {
                    text_document: TextDocumentIdentifier {
                        uri: uri.parse().unwrap(),
                    },
                    position: Position {
                        line: params.line - 1,
                        character: params.column,
                    },
                },
                work_done_progress_params: Default::default(),
            },
        )
        .await
        .map_err(|e| format!("{}", e))?;

    let items = match prepare_response {
        Some(items) if !items.is_empty() => items,
        _ => return Ok(SupertypesResult { locations: vec![] }),
    };

    // Send supertypes request with just the item field
    let supertypes_response: Option<Vec<serde_json::Value>> = client
        .send_request(
            "typeHierarchy/supertypes",
            serde_json::json!({ "item": items[0] }),
        )
        .await
        .map_err(|e| format!("{}", e))?;

    let locations = supertypes_response
        .map(|items| format_type_hierarchy_items_from_json(&items, &workspace_root, params.context))
        .unwrap_or_default();

    Ok(SupertypesResult { locations })
}

fn definition_response_to_locations(
    response: &GotoDefinitionResponse,
    workspace_root: &PathBuf,
    context: u32,
) -> Vec<LocationInfo> {
    let locations: Vec<Location> = match response {
        GotoDefinitionResponse::Scalar(loc) => vec![loc.clone()],
        GotoDefinitionResponse::Array(locs) => locs.clone(),
        GotoDefinitionResponse::Link(links) => links
            .iter()
            .map(|link| Location {
                uri: link.target_uri.clone(),
                range: link.target_selection_range,
            })
            .collect(),
    };
    format_locations(&locations, workspace_root, context)
}
