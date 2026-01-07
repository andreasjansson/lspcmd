use std::path::PathBuf;

use leta_fs::path_to_uri;
use leta_lsp::{Location, TypeHierarchyItem};
use serde_json::{json, Value};

use super::{format_locations, format_type_hierarchy_items, relative_path, HandlerContext};

pub async fn handle_references(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    let workspace_root = PathBuf::from(
        params.get("workspace_root")
            .and_then(|v| v.as_str())
            .ok_or("Missing workspace_root")?
    );
    let path = PathBuf::from(
        params.get("path")
            .and_then(|v| v.as_str())
            .ok_or("Missing path")?
    );
    let line = params.get("line")
        .and_then(|v| v.as_u64())
        .ok_or("Missing line")? as u32;
    let column = params.get("column")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;
    let context = params.get("context")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;

    ctx.session.get_or_create_workspace(&path, &workspace_root).await?;
    let _ = ctx.session.ensure_document_open(&path, &workspace_root).await?;
    let client = ctx.session.get_workspace_client(&path, &workspace_root).await
        .ok_or("Failed to get LSP client")?;

    let uri = path_to_uri(&path);
    let request_params = json!({
        "textDocument": {"uri": uri},
        "position": {"line": line - 1, "character": column},
        "context": {"includeDeclaration": true}
    });

    let result: Result<Vec<Location>, _> = client
        .send_request("textDocument/references", request_params)
        .await;

    let locations = match result {
        Ok(locs) => format_locations(&locs, &workspace_root, context),
        Err(e) => return Err(format!("LSP error: {}", e)),
    };

    Ok(json!({"locations": locations}))
}

pub async fn handle_declaration(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    let workspace_root = PathBuf::from(
        params.get("workspace_root")
            .and_then(|v| v.as_str())
            .ok_or("Missing workspace_root")?
    );
    let path = PathBuf::from(
        params.get("path")
            .and_then(|v| v.as_str())
            .ok_or("Missing path")?
    );
    let line = params.get("line")
        .and_then(|v| v.as_u64())
        .ok_or("Missing line")? as u32;
    let column = params.get("column")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;
    let context = params.get("context")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;

    ctx.session.get_or_create_workspace(&path, &workspace_root).await?;
    let _ = ctx.session.ensure_document_open(&path, &workspace_root).await?;
    let client = ctx.session.get_workspace_client(&path, &workspace_root).await
        .ok_or("Failed to get LSP client")?;

    let uri = path_to_uri(&path);
    let request_params = json!({
        "textDocument": {"uri": uri},
        "position": {"line": line - 1, "character": column}
    });

    let result: Result<Value, _> = client
        .send_request("textDocument/declaration", request_params)
        .await;

    match result {
        Ok(value) => {
            let locations = parse_definition_response(&value, &workspace_root, context);
            Ok(json!({"locations": locations}))
        }
        Err(e) => {
            let msg = e.to_string();
            if msg.contains("-32601") || msg.contains("not supported") {
                Err("Declaration not supported by this language server".to_string())
            } else {
                Err(format!("LSP error: {}", e))
            }
        }
    }
}

pub async fn handle_implementations(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    let workspace_root = PathBuf::from(
        params.get("workspace_root")
            .and_then(|v| v.as_str())
            .ok_or("Missing workspace_root")?
    );
    let path = PathBuf::from(
        params.get("path")
            .and_then(|v| v.as_str())
            .ok_or("Missing path")?
    );
    let line = params.get("line")
        .and_then(|v| v.as_u64())
        .ok_or("Missing line")? as u32;
    let column = params.get("column")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;
    let context = params.get("context")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;

    ctx.session.get_or_create_workspace(&path, &workspace_root).await?;
    let _ = ctx.session.ensure_document_open(&path, &workspace_root).await?;
    let client = ctx.session.get_workspace_client(&path, &workspace_root).await
        .ok_or("Failed to get LSP client")?;

    let uri = path_to_uri(&path);
    let request_params = json!({
        "textDocument": {"uri": uri},
        "position": {"line": line - 1, "character": column}
    });

    let result: Result<Value, _> = client
        .send_request("textDocument/implementation", request_params)
        .await;

    match result {
        Ok(value) => {
            let locations = parse_definition_response(&value, &workspace_root, context);
            Ok(json!({"locations": locations}))
        }
        Err(e) => {
            let msg = e.to_string();
            if msg.contains("-32601") || msg.contains("not supported") {
                Ok(json!({"locations": [], "error": "Implementations not supported by this language server"}))
            } else {
                Err(format!("LSP error: {}", e))
            }
        }
    }
}

pub async fn handle_subtypes(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    handle_type_hierarchy(ctx, params, "typeHierarchy/subtypes").await
}

pub async fn handle_supertypes(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    handle_type_hierarchy(ctx, params, "typeHierarchy/supertypes").await
}

async fn handle_type_hierarchy(ctx: &HandlerContext, params: Value, method: &str) -> Result<Value, String> {
    let workspace_root = PathBuf::from(
        params.get("workspace_root")
            .and_then(|v| v.as_str())
            .ok_or("Missing workspace_root")?
    );
    let path = PathBuf::from(
        params.get("path")
            .and_then(|v| v.as_str())
            .ok_or("Missing path")?
    );
    let line = params.get("line")
        .and_then(|v| v.as_u64())
        .ok_or("Missing line")? as u32;
    let column = params.get("column")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;
    let context = params.get("context")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;

    ctx.session.get_or_create_workspace(&path, &workspace_root).await?;
    let _ = ctx.session.ensure_document_open(&path, &workspace_root).await?;
    let client = ctx.session.get_workspace_client(&path, &workspace_root).await
        .ok_or("Failed to get LSP client")?;

    let uri = path_to_uri(&path);
    let prepare_params = json!({
        "textDocument": {"uri": uri},
        "position": {"line": line - 1, "character": column}
    });

    let prepare_result: Result<Vec<TypeHierarchyItem>, _> = client
        .send_request("textDocument/prepareTypeHierarchy", prepare_params)
        .await;

    let items = match prepare_result {
        Ok(items) if !items.is_empty() => items,
        Ok(_) => return Ok(json!({"locations": []})),
        Err(e) => {
            let msg = e.to_string();
            if msg.contains("-32601") || msg.contains("not supported") {
                let kind = if method.contains("subtypes") { "Subtypes" } else { "Supertypes" };
                return Err(format!("{} not supported by this language server", kind));
            }
            return Err(format!("LSP error: {}", e));
        }
    };

    let hierarchy_params = json!({"item": items[0]});
    let result: Result<Vec<TypeHierarchyItem>, _> = client
        .send_request(method, hierarchy_params)
        .await;

    let locations = match result {
        Ok(items) => format_type_hierarchy_items(&items, &workspace_root, context),
        Err(e) => return Err(format!("LSP error: {}", e)),
    };

    Ok(json!({"locations": locations}))
}

fn parse_definition_response(value: &Value, workspace_root: &PathBuf, context: u32) -> Vec<Value> {
    if value.is_null() {
        return vec![];
    }

    if let Some(array) = value.as_array() {
        if array.is_empty() {
            return vec![];
        }

        if array[0].get("targetUri").is_some() {
            let locations: Vec<Location> = array.iter().filter_map(|item| {
                let uri = item.get("targetUri")?.as_str()?;
                let range = item.get("targetSelectionRange")?;
                Some(Location {
                    uri: uri.to_string(),
                    range: serde_json::from_value(range.clone()).ok()?,
                })
            }).collect();
            return format_locations(&locations, workspace_root, context);
        }

        let locations: Vec<Location> = array.iter().filter_map(|item| {
            serde_json::from_value(item.clone()).ok()
        }).collect();
        return format_locations(&locations, workspace_root, context);
    }

    if let Ok(loc) = serde_json::from_value::<Location>(value.clone()) {
        return format_locations(&[loc], workspace_root, context);
    }

    vec![]
}
