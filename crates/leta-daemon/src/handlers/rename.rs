use std::collections::HashSet;
use std::path::{Path, PathBuf};

use leta_fs::uri_to_path;
use leta_lsp::lsp_types::{
    DocumentChanges, FileRename, Position, RenameFilesParams, RenameParams as LspRenameParams,
    TextDocumentIdentifier, TextEdit, WorkspaceEdit, FileChangeType,
};
use leta_types::{MoveFileParams, MoveFileResult, RenameParams, RenameResult};

use super::{relative_path, HandlerContext};

fn get_files_from_workspace_edit(edit: &WorkspaceEdit, workspace_root: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    
    if let Some(changes) = &edit.changes {
        for uri in changes.keys() {
            files.push(uri_to_path(uri.as_str()));
        }
    }
    
    if let Some(document_changes) = &edit.document_changes {
        match document_changes {
            DocumentChanges::Edits(edits) => {
                for edit in edits {
                    files.push(uri_to_path(edit.text_document.uri.as_str()));
                }
            }
            DocumentChanges::Operations(ops) => {
                for op in ops {
                    match op {
                        leta_lsp::lsp_types::DocumentChangeOperation::Edit(edit) => {
                            files.push(uri_to_path(edit.text_document.uri.as_str()));
                        }
                        leta_lsp::lsp_types::DocumentChangeOperation::Op(resource_op) => {
                            match resource_op {
                                leta_lsp::lsp_types::ResourceOp::Rename(rename) => {
                                    files.push(uri_to_path(rename.old_uri.as_str()));
                                }
                                leta_lsp::lsp_types::ResourceOp::Delete(delete) => {
                                    files.push(uri_to_path(delete.uri.as_str()));
                                }
                                leta_lsp::lsp_types::ResourceOp::Create(_) => {}
                            }
                        }
                    }
                }
            }
        }
    }
    
    files
}

pub async fn handle_rename(
    ctx: &HandlerContext,
    params: RenameParams,
) -> Result<RenameResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let file_path = PathBuf::from(&params.path);

    let workspace = ctx.session.get_or_create_workspace(&file_path, &workspace_root).await
        .map_err(|e| e.to_string())?;
    
    workspace.ensure_document_open(&file_path).await?;
    let client = workspace.client().await.ok_or("No LSP client")?;
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

    let edit = response.ok_or("Rename not supported or failed")?;
    
    // Close ALL documents that will be modified BEFORE applying edits
    // This is critical for servers that won't reindex files if the document is still open
    let files_to_modify = get_files_from_workspace_edit(&edit, &workspace_root);
    tracing::info!("Closing {} documents before rename: {:?}", files_to_modify.len(), files_to_modify);
    for file_path in &files_to_modify {
        let _ = workspace.close_document(file_path).await;
    }
    
    let (files_changed, renamed_files) = apply_workspace_edit(&edit, &workspace_root)?;
    
    // Build list of file changes for didChangeWatchedFiles notification
    // For modified files, we send DELETE first to remove old index entries,
    // then CREATE to add new ones
    let mut file_changes: Vec<(PathBuf, FileChangeType)> = Vec::new();
    for (old_path, new_path) in &renamed_files {
        file_changes.push((old_path.clone(), FileChangeType::DELETED));
        file_changes.push((new_path.clone(), FileChangeType::CREATED));
    }
    let renamed_new_paths: HashSet<_> = renamed_files.iter().map(|(_, new)| new.clone()).collect();
    for rel_path in &files_changed {
        let abs_path = workspace_root.join(rel_path);
        if abs_path.exists() && !renamed_new_paths.contains(&abs_path) {
            file_changes.push((abs_path.clone(), FileChangeType::DELETED));
            file_changes.push((abs_path, FileChangeType::CREATED));
        }
    }
    
    // Notify LSP about file changes
    if !file_changes.is_empty() {
        tracing::info!("Notifying LSP about {} file changes", file_changes.len());
        let _ = workspace.notify_files_changed(&file_changes).await;
    }

    // WORKAROUND: Restart ruby-lsp after rename to force a full reindex.
    //
    // ruby-lsp has a bug where the index doesn't properly update after rename operations.
    // When we rename a symbol (e.g., Storage → StorageInterface), the old name remains
    // in the index even after we send didChangeWatchedFiles notifications. This causes
    // "The new name is already in use by X" errors on consecutive renames.
    //
    // The root cause is in how ruby-lsp processes didChangeWatchedFiles:
    // https://github.com/Shopify/ruby-lsp/blob/main/lib/ruby_lsp/server.rb
    //
    // In workspace_did_change_watched_files(), ruby-lsp calls handle_ruby_file_change()
    // which should update the index via index.delete() and index.index_single().
    // However, the index entries for the OLD symbol name are not being deleted.
    //
    // We've tried several approaches that didn't work:
    // - Sending DELETED + CREATED file change notifications
    // - Sending CHANGED notifications  
    // - Reopening documents and triggering documentSymbol
    // - Adding delays between operations
    //
    // The only reliable fix is to restart ruby-lsp, which forces a complete reindex
    // from disk. This is slower but guarantees correct behavior.
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
    
    let client = workspace.client().await.ok_or("No LSP client")?;
    let server_name = workspace.server_name();
    
    let caps = client.capabilities().await;
    let supports_will_rename = caps.workspace.as_ref()
        .and_then(|w| w.file_operations.as_ref())
        .and_then(|fo| fo.will_rename.as_ref())
        .is_some();

    if !supports_will_rename {
        return Err(format!("move-file is not supported by {}", server_name));
    }

    // Open all source files so LSP can compute import updates
    // This is needed for servers like basedpyright that only update imports
    // for files they know about
    let extension = old_path.extension().and_then(|e| e.to_str()).unwrap_or("");
    let source_files = super::find_source_files_with_extension(&workspace_root, extension);
    let mut opened_for_indexing = Vec::new();
    for file_path in source_files {
        if file_path != old_path && !workspace.is_document_open(&file_path).await {
            workspace.ensure_document_open(&file_path).await?;
            opened_for_indexing.push(file_path);
        }
    }
    
    // Wait for LSP to index the opened files
    if !opened_for_indexing.is_empty() {
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }

    let old_uri = leta_fs::path_to_uri(&old_path);
    let new_uri = leta_fs::path_to_uri(&new_path);

    tracing::info!("mv: old_path={:?} new_path={:?}", old_path, new_path);
    tracing::info!("mv: old_uri={} new_uri={}", old_uri, new_uri);

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
    
    tracing::info!("workspace/willRenameFiles response: {:?}", response);
    
    // Close the documents we opened for indexing
    for file_path in opened_for_indexing {
        let _ = workspace.close_document(&file_path).await;
    }

    let mut files_changed = Vec::new();
    let mut file_moved_by_edit = false;

    // Apply workspace edit FIRST (it may contain the rename operation)
    if let Some(ref edit) = response {
        let (files, was_moved) = apply_workspace_edit_for_move(edit, &workspace_root, &old_path, &new_path)?;
        files_changed = files;
        file_moved_by_edit = was_moved;
    }

    // Only manually move if the edit didn't already move it
    if !file_moved_by_edit {
        if let Some(parent) = new_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| format!("Failed to create directory: {}", e))?;
        }
        std::fs::rename(&old_path, &new_path).map_err(|e| format!("Failed to move file: {}", e))?;
        files_changed.push(relative_path(&new_path, &workspace_root));
    }

    // Deduplicate
    let mut seen = HashSet::new();
    files_changed.retain(|f| seen.insert(f.clone()));
    files_changed.sort();

    let imports_updated = files_changed.iter().any(|f| {
        f != &relative_path(&new_path, &workspace_root)
    });

    Ok(MoveFileResult {
        files_changed,
        imports_updated,
    })
}

/// Apply a workspace edit for a move operation, returning (changed_files, file_was_moved).
/// This tracks whether the file was moved by the edit so we don't move it twice.
fn apply_workspace_edit_for_move(
    edit: &WorkspaceEdit,
    workspace_root: &PathBuf,
    move_old_path: &PathBuf,
    move_new_path: &PathBuf,
) -> Result<(Vec<String>, bool), String> {
    let mut changed_files = Vec::new();
    let mut file_moved = false;

    // edit.changes uses URI as key with array of text edits
    if let Some(changes) = &edit.changes {
        for (uri, edits) in changes {
            // Only add to changed files if there are actual edits
            if edits.is_empty() {
                continue;
            }
            let file_path = uri_to_path(uri.as_str());
            apply_text_edits(&file_path, edits)?;
            changed_files.push(relative_path(&file_path, workspace_root));
        }
    }

    if let Some(document_changes) = &edit.document_changes {
        match document_changes {
            DocumentChanges::Edits(edits) => {
                for edit in edits {
                    let text_edits: Vec<_> = edit.edits.iter().map(|e| match e {
                        leta_lsp::lsp_types::OneOf::Left(te) => te.clone(),
                        leta_lsp::lsp_types::OneOf::Right(ate) => ate.text_edit.clone(),
                    }).collect();
                    
                    // Only add to changed files if there are actual edits
                    if text_edits.is_empty() {
                        continue;
                    }
                    
                    let mut file_path = uri_to_path(edit.text_document.uri.as_str());
                    // If this edit targets the old path, apply to new path instead
                    if file_path == *move_old_path {
                        file_path = move_new_path.clone();
                    }
                    apply_text_edits(&file_path, &text_edits)?;
                    changed_files.push(relative_path(&file_path, workspace_root));
                }
            }
            DocumentChanges::Operations(ops) => {
                for op in ops {
                    match op {
                        leta_lsp::lsp_types::DocumentChangeOperation::Edit(edit) => {
                            let text_edits: Vec<_> = edit.edits.iter().map(|e| match e {
                                leta_lsp::lsp_types::OneOf::Left(te) => te.clone(),
                                leta_lsp::lsp_types::OneOf::Right(ate) => ate.text_edit.clone(),
                            }).collect();
                            
                            // Only add to changed files if there are actual edits
                            if text_edits.is_empty() {
                                continue;
                            }
                            
                            let mut file_path = uri_to_path(edit.text_document.uri.as_str());
                            if file_path == *move_old_path {
                                file_path = move_new_path.clone();
                            }
                            apply_text_edits(&file_path, &text_edits)?;
                            changed_files.push(relative_path(&file_path, workspace_root));
                        }
                        leta_lsp::lsp_types::DocumentChangeOperation::Op(resource_op) => {
                            match resource_op {
                                leta_lsp::lsp_types::ResourceOp::Create(create) => {
                                    let path = uri_to_path(create.uri.as_str());
                                    if let Some(parent) = path.parent() {
                                        let _ = std::fs::create_dir_all(parent);
                                    }
                                    let _ = std::fs::write(&path, "");
                                    changed_files.push(relative_path(&path, workspace_root));
                                }
                                leta_lsp::lsp_types::ResourceOp::Rename(rename) => {
                                    let old_path = uri_to_path(rename.old_uri.as_str());
                                    let new_path = uri_to_path(rename.new_uri.as_str());
                                    
                                    // Check if this is the file we're trying to move
                                    if old_path == *move_old_path && new_path == *move_new_path {
                                        file_moved = true;
                                    }
                                    
                                    if let Some(parent) = new_path.parent() {
                                        let _ = std::fs::create_dir_all(parent);
                                    }
                                    if old_path.exists() {
                                        let _ = std::fs::rename(&old_path, &new_path);
                                    }
                                    changed_files.push(relative_path(&new_path, workspace_root));
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

    Ok((changed_files, file_moved))
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
