use std::collections::HashSet;
use std::path::PathBuf;

use leta_fs::{path_to_uri, uri_to_path};
use leta_lsp::{DocumentChange, WorkspaceEdit};
use serde_json::{json, Value};

use super::{relative_path, HandlerContext};

pub async fn handle_rename(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
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
    let new_name = params.get("new_name")
        .and_then(|v| v.as_str())
        .ok_or("Missing new_name")?;

    ctx.session.get_or_create_workspace(&path, &workspace_root).await?;
    let _ = ctx.session.ensure_document_open(&path, &workspace_root).await?;
    let client = ctx.session.get_workspace_client(&path, &workspace_root).await
        .ok_or("Failed to get LSP client")?;

    let uri = path_to_uri(&path);
    let request_params = json!({
        "textDocument": {"uri": uri},
        "position": {"line": line - 1, "character": column},
        "newName": new_name
    });

    let result: Result<WorkspaceEdit, _> = client
        .send_request("textDocument/rename", request_params)
        .await;

    let workspace_edit = match result {
        Ok(edit) => edit,
        Err(e) => {
            let msg = e.to_string();
            if msg.contains("-32601") || msg.contains("not supported") {
                return Err("Rename not supported by this language server".to_string());
            }
            return Err(format!("LSP error: {}", e));
        }
    };

    let files_changed = apply_workspace_edit(&workspace_edit, &workspace_root)?;

    Ok(json!({"files_changed": files_changed}))
}

pub async fn handle_move_file(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    let workspace_root = PathBuf::from(
        params.get("workspace_root")
            .and_then(|v| v.as_str())
            .ok_or("Missing workspace_root")?
    );
    let old_path = PathBuf::from(
        params.get("old_path")
            .and_then(|v| v.as_str())
            .ok_or("Missing old_path")?
    );
    let new_path = PathBuf::from(
        params.get("new_path")
            .and_then(|v| v.as_str())
            .ok_or("Missing new_path")?
    );

    ctx.session.get_or_create_workspace(&old_path, &workspace_root).await?;
    let client = ctx.session.get_workspace_client(&old_path, &workspace_root).await
        .ok_or("Failed to get LSP client")?;

    let old_uri = path_to_uri(&old_path);
    let new_uri = path_to_uri(&new_path);

    let request_params = json!({
        "files": [{
            "oldUri": old_uri,
            "newUri": new_uri
        }]
    });

    let result: Result<WorkspaceEdit, _> = client
        .send_request("workspace/willRenameFiles", request_params)
        .await;

    let (files_changed, imports_updated) = match result {
        Ok(edit) => {
            let changed = apply_workspace_edit(&edit, &workspace_root)?;
            (changed, true)
        }
        Err(e) => {
            let msg = e.to_string();
            if msg.contains("-32601") || msg.contains("not supported") {
                (vec![], false)
            } else {
                return Err(format!("LSP error: {}", e));
            }
        }
    };

    if let Some(parent) = new_path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("Failed to create directory: {}", e))?;
    }
    std::fs::rename(&old_path, &new_path).map_err(|e| format!("Failed to move file: {}", e))?;

    let rel_new_path = relative_path(&new_path, &workspace_root);
    let mut all_changed: Vec<String> = files_changed;
    if !all_changed.contains(&rel_new_path) {
        all_changed.push(rel_new_path);
    }
    all_changed.sort();

    Ok(json!({
        "files_changed": all_changed,
        "imports_updated": imports_updated
    }))
}

fn apply_workspace_edit(edit: &WorkspaceEdit, workspace_root: &PathBuf) -> Result<Vec<String>, String> {
    let mut changed_files = HashSet::new();

    if let Some(changes) = &edit.changes {
        for (uri, edits) in changes {
            let file_path = uri_to_path(uri);
            let content = std::fs::read_to_string(&file_path)
                .map_err(|e| format!("Failed to read {}: {}", file_path.display(), e))?;

            let mut lines: Vec<String> = content.lines().map(String::from).collect();

            let mut sorted_edits = edits.clone();
            sorted_edits.sort_by(|a, b| {
                let line_cmp = b.range.start.line.cmp(&a.range.start.line);
                if line_cmp == std::cmp::Ordering::Equal {
                    b.range.start.character.cmp(&a.range.start.character)
                } else {
                    line_cmp
                }
            });

            for text_edit in sorted_edits {
                let start_line = text_edit.range.start.line as usize;
                let end_line = text_edit.range.end.line as usize;
                let start_char = text_edit.range.start.character as usize;
                let end_char = text_edit.range.end.character as usize;

                if start_line >= lines.len() {
                    while lines.len() <= start_line {
                        lines.push(String::new());
                    }
                }

                if start_line == end_line {
                    let line = &mut lines[start_line];
                    let before = if start_char <= line.len() { &line[..start_char] } else { line.as_str() };
                    let after = if end_char <= line.len() { &line[end_char..] } else { "" };
                    *line = format!("{}{}{}", before, text_edit.new_text, after);
                } else {
                    let first_line = &lines[start_line];
                    let last_line = if end_line < lines.len() { &lines[end_line] } else { "" };
                    
                    let before = if start_char <= first_line.len() { &first_line[..start_char] } else { first_line };
                    let after = if end_char <= last_line.len() { &last_line[end_char..] } else { "" };
                    
                    let new_content = format!("{}{}{}", before, text_edit.new_text, after);
                    let new_lines: Vec<String> = new_content.lines().map(String::from).collect();
                    
                    let end = (end_line + 1).min(lines.len());
                    lines.splice(start_line..end, new_lines);
                }
            }

            let new_content = lines.join("\n");
            std::fs::write(&file_path, new_content)
                .map_err(|e| format!("Failed to write {}: {}", file_path.display(), e))?;

            changed_files.insert(relative_path(&file_path, workspace_root));
        }
    }

    if let Some(document_changes) = &edit.document_changes {
        for change in document_changes {
            match change {
                DocumentChange::Edit(text_doc_edit) => {
                    let file_path = uri_to_path(&text_doc_edit.text_document.uri);
                    let content = std::fs::read_to_string(&file_path)
                        .map_err(|e| format!("Failed to read {}: {}", file_path.display(), e))?;

                    let mut lines: Vec<String> = content.lines().map(String::from).collect();

                    let mut sorted_edits = text_doc_edit.edits.clone();
                    sorted_edits.sort_by(|a, b| {
                        let line_cmp = b.range.start.line.cmp(&a.range.start.line);
                        if line_cmp == std::cmp::Ordering::Equal {
                            b.range.start.character.cmp(&a.range.start.character)
                        } else {
                            line_cmp
                        }
                    });

                    for text_edit in sorted_edits {
                        let start_line = text_edit.range.start.line as usize;
                        let end_line = text_edit.range.end.line as usize;
                        let start_char = text_edit.range.start.character as usize;
                        let end_char = text_edit.range.end.character as usize;

                        if start_line >= lines.len() {
                            while lines.len() <= start_line {
                                lines.push(String::new());
                            }
                        }

                        if start_line == end_line {
                            let line = &mut lines[start_line];
                            let before = if start_char <= line.len() { &line[..start_char] } else { line.as_str() };
                            let after = if end_char <= line.len() { &line[end_char..] } else { "" };
                            *line = format!("{}{}{}", before, text_edit.new_text, after);
                        } else {
                            let first_line = &lines[start_line];
                            let last_line = if end_line < lines.len() { &lines[end_line] } else { "" };
                            
                            let before = if start_char <= first_line.len() { &first_line[..start_char] } else { first_line };
                            let after = if end_char <= last_line.len() { &last_line[end_char..] } else { "" };
                            
                            let new_content = format!("{}{}{}", before, text_edit.new_text, after);
                            let new_lines: Vec<String> = new_content.lines().map(String::from).collect();
                            
                            let end = (end_line + 1).min(lines.len());
                            lines.splice(start_line..end, new_lines);
                        }
                    }

                    let new_content = lines.join("\n");
                    std::fs::write(&file_path, new_content)
                        .map_err(|e| format!("Failed to write {}: {}", file_path.display(), e))?;

                    changed_files.insert(relative_path(&file_path, workspace_root));
                }
                DocumentChange::Rename(rename) => {
                    let old_path = uri_to_path(&rename.old_uri);
                    let new_path = uri_to_path(&rename.new_uri);
                    
                    if let Some(parent) = new_path.parent() {
                        std::fs::create_dir_all(parent).ok();
                    }
                    std::fs::rename(&old_path, &new_path).ok();
                    
                    changed_files.insert(relative_path(&new_path, workspace_root));
                }
                DocumentChange::Create(create) => {
                    let path = uri_to_path(&create.uri);
                    if let Some(parent) = path.parent() {
                        std::fs::create_dir_all(parent).ok();
                    }
                    std::fs::write(&path, "").ok();
                    changed_files.insert(relative_path(&path, workspace_root));
                }
                DocumentChange::Delete(delete) => {
                    let path = uri_to_path(&delete.uri);
                    std::fs::remove_file(&path).ok();
                }
            }
        }
    }

    let mut result: Vec<String> = changed_files.into_iter().collect();
    result.sort();
    Ok(result)
}
