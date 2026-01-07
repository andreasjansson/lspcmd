use std::collections::HashSet;
use std::path::PathBuf;

use leta_fs::uri_to_path;
use leta_lsp::lsp_types::{
    DocumentChanges, FileRename, Position, RenameFilesParams, RenameParams as LspRenameParams,
    TextDocumentIdentifier, TextEdit, WorkspaceEdit,
};
use leta_types::{MoveFileParams, MoveFileResult, RenameParams, RenameResult};

use super::{relative_path, HandlerContext};

pub async fn handle_rename(
    ctx: &HandlerContext,
    params: RenameParams,
) -> Result<RenameResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let file_path = PathBuf::from(&params.path);

    let workspace = ctx.session.get_or_create_workspace(&file_path, &workspace_root).await
        .map_err(|e| e.to_string())?;
    
    workspace.ensure_document_open(&file_path).await?;
    let client = workspace.client().ok_or("No LSP client")?;
    let uri = leta_fs::path_to_uri(&file_path);

    let response: Option<WorkspaceEdit> = client
        .send_request(
            "textDocument/rename",
            LspRenameParams {
                text_document_position: leta_lsp::lsp_types::TextDocumentPositionParams {
                    text_document: TextDocumentIdentifier { uri: uri.parse().unwrap() },
                    position: Position {
                        line: params.line - 1,
                        character: params.column,
                    },
                },
                new_name: params.new_name.clone(),
                work_done_progress_params: Default::default(),
            },
        )
        .await
        .map_err(|e| e.to_string())?;

    let edit = response.ok_or("Rename not supported or no changes")?;
    let files_changed = apply_workspace_edit(&edit, &workspace_root)?;

    // ruby-lsp has issues refreshing its index after renames, restart to force reindex
    if workspace.server_name() == "ruby-lsp" {
        tracing::info!("ruby-lsp: restarting server to refresh index after rename");
        let _ = ctx.session.restart_workspace(&workspace_root).await;
    }

    Ok(RenameResult { files_changed })
}

pub async fn handle_move_file(
    ctx: &HandlerContext,
    params: MoveFileParams,
) -> Result<MoveFileResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let old_path = PathBuf::from(&params.old_path);
    let new_path = PathBuf::from(&params.new_path);

    if !old_path.exists() {
        return Err(format!("Source file does not exist: {}", old_path.display()));
    }
    if new_path.exists() {
        return Err(format!("Destination already exists: {}", new_path.display()));
    }

    let workspace = ctx.session.get_or_create_workspace(&old_path, &workspace_root).await
        .map_err(|e| e.to_string())?;
    
    let client = workspace.client().ok_or("No LSP client")?;
    let server_name = workspace.server_name();
    
    let caps = client.capabilities().await;
    let supports_will_rename = caps.workspace.as_ref()
        .and_then(|w| w.file_operations.as_ref())
        .and_then(|fo| fo.will_rename.as_ref())
        .is_some();

    if !supports_will_rename {
        return Err(format!("move-file is not supported by {}", server_name));
    }

    let old_uri = leta_fs::path_to_uri(&old_path);
    let new_uri = leta_fs::path_to_uri(&new_path);

    let response: Option<WorkspaceEdit> = client
        .send_request(
            "workspace/willRenameFiles",
            RenameFilesParams {
                files: vec![FileRename {
                    old_uri: old_uri.clone(),
                    new_uri: new_uri.clone(),
                }],
            },
        )
        .await
        .ok()
        .flatten();

    if let Some(parent) = new_path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("Failed to create directory: {}", e))?;
    }
    std::fs::rename(&old_path, &new_path).map_err(|e| format!("Failed to move file: {}", e))?;

    let (files_changed, imports_updated) = if let Some(edit) = response {
        let files = apply_workspace_edit(&edit, &workspace_root)?;
        let imports_updated = !files.is_empty();
        (files, imports_updated)
    } else {
        (vec![relative_path(&new_path, &workspace_root)], false)
    };

    Ok(MoveFileResult {
        files_changed,
        imports_updated,
    })
}

fn apply_workspace_edit(edit: &WorkspaceEdit, workspace_root: &PathBuf) -> Result<Vec<String>, String> {
    let mut changed_files = HashSet::new();

    if let Some(changes) = &edit.changes {
        for (uri, edits) in changes {
            let file_path = uri_to_path(uri.as_str());
            apply_text_edits(&file_path, edits)?;
            changed_files.insert(relative_path(&file_path, workspace_root));
        }
    }

    if let Some(document_changes) = &edit.document_changes {
        match document_changes {
            DocumentChanges::Edits(edits) => {
                for edit in edits {
                    let file_path = uri_to_path(edit.text_document.uri.as_str());
                    apply_text_edits(&file_path, &edit.edits.iter().map(|e| match e {
                        leta_lsp::lsp_types::OneOf::Left(te) => te.clone(),
                        leta_lsp::lsp_types::OneOf::Right(ate) => ate.text_edit.clone(),
                    }).collect::<Vec<_>>())?;
                    changed_files.insert(relative_path(&file_path, workspace_root));
                }
            }
            DocumentChanges::Operations(ops) => {
                for op in ops {
                    match op {
                        leta_lsp::lsp_types::DocumentChangeOperation::Edit(edit) => {
                            let file_path = uri_to_path(edit.text_document.uri.as_str());
                            apply_text_edits(&file_path, &edit.edits.iter().map(|e| match e {
                                leta_lsp::lsp_types::OneOf::Left(te) => te.clone(),
                                leta_lsp::lsp_types::OneOf::Right(ate) => ate.text_edit.clone(),
                            }).collect::<Vec<_>>())?;
                            changed_files.insert(relative_path(&file_path, workspace_root));
                        }
                        leta_lsp::lsp_types::DocumentChangeOperation::Op(resource_op) => {
                            match resource_op {
                                leta_lsp::lsp_types::ResourceOp::Create(create) => {
                                    let path = uri_to_path(create.uri.as_str());
                                    if let Some(parent) = path.parent() {
                                        let _ = std::fs::create_dir_all(parent);
                                    }
                                    let _ = std::fs::write(&path, "");
                                    changed_files.insert(relative_path(&path, workspace_root));
                                }
                                leta_lsp::lsp_types::ResourceOp::Rename(rename) => {
                                    let old_path = uri_to_path(rename.old_uri.as_str());
                                    let new_path = uri_to_path(rename.new_uri.as_str());
                                    if let Some(parent) = new_path.parent() {
                                        let _ = std::fs::create_dir_all(parent);
                                    }
                                    let _ = std::fs::rename(&old_path, &new_path);
                                    changed_files.insert(relative_path(&new_path, workspace_root));
                                }
                                leta_lsp::lsp_types::ResourceOp::Delete(delete) => {
                                    let path = uri_to_path(delete.uri.as_str());
                                    let _ = std::fs::remove_file(&path);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    let mut result: Vec<String> = changed_files.into_iter().collect();
    result.sort();
    Ok(result)
}

fn apply_text_edits(file_path: &PathBuf, edits: &[TextEdit]) -> Result<(), String> {
    let content = std::fs::read_to_string(file_path)
        .map_err(|e| format!("Failed to read {}: {}", file_path.display(), e))?;
    
    let lines: Vec<&str> = content.lines().collect();
    
    let mut sorted_edits: Vec<&TextEdit> = edits.iter().collect();
    sorted_edits.sort_by(|a, b| {
        let a_start = (a.range.start.line, a.range.start.character);
        let b_start = (b.range.start.line, b.range.start.character);
        b_start.cmp(&a_start)
    });

    let mut result_lines: Vec<String> = lines.iter().map(|s| s.to_string()).collect();

    for edit in sorted_edits {
        let start_line = edit.range.start.line as usize;
        let start_char = edit.range.start.character as usize;
        let end_line = edit.range.end.line as usize;
        let end_char = edit.range.end.character as usize;

        if start_line >= result_lines.len() {
            while result_lines.len() <= start_line {
                result_lines.push(String::new());
            }
        }

        let prefix = if start_char <= result_lines[start_line].len() {
            result_lines[start_line][..start_char].to_string()
        } else {
            result_lines[start_line].clone()
        };

        let suffix = if end_line < result_lines.len() && end_char <= result_lines[end_line].len() {
            result_lines[end_line][end_char..].to_string()
        } else if end_line < result_lines.len() {
            String::new()
        } else {
            String::new()
        };

        let new_text_lines: Vec<&str> = edit.new_text.lines().collect();
        
        for _ in start_line..=end_line.min(result_lines.len().saturating_sub(1)) {
            if start_line < result_lines.len() {
                result_lines.remove(start_line);
            }
        }

        if new_text_lines.is_empty() {
            result_lines.insert(start_line, format!("{}{}", prefix, suffix));
        } else {
            for (i, line) in new_text_lines.iter().enumerate() {
                let new_line = if i == 0 && i == new_text_lines.len() - 1 {
                    format!("{}{}{}", prefix, line, suffix)
                } else if i == 0 {
                    format!("{}{}", prefix, line)
                } else if i == new_text_lines.len() - 1 {
                    format!("{}{}", line, suffix)
                } else {
                    line.to_string()
                };
                result_lines.insert(start_line + i, new_line);
            }
        }
    }

    let new_content = result_lines.join("\n");
    std::fs::write(file_path, new_content)
        .map_err(|e| format!("Failed to write {}: {}", file_path.display(), e))?;

    Ok(())
}
