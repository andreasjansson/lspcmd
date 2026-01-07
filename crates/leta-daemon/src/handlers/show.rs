use std::path::PathBuf;

use leta_fs::{path_to_uri, read_file_content};
use leta_lsp::lsp_types::{DocumentSymbol, DocumentSymbolResponse, SymbolInformation};
use serde_json::{json, Value};

use super::{relative_path, HandlerContext};

pub async fn handle_show(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
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
    let context = params.get("context")
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32;
    let head = params.get("head")
        .and_then(|v| v.as_u64())
        .unwrap_or(200) as u32;
    let symbol_name = params.get("symbol")
        .and_then(|v| v.as_str())
        .map(String::from);
    let symbol_kind = params.get("kind")
        .and_then(|v| v.as_str())
        .map(String::from);
    let range_start_line = params.get("range_start_line")
        .and_then(|v| v.as_u64())
        .map(|v| v as u32);
    let range_end_line = params.get("range_end_line")
        .and_then(|v| v.as_u64())
        .map(|v| v as u32);
    let _direct_location = params.get("direct_location")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    let path = path.canonicalize().unwrap_or(path);
    let rel_path = relative_path(&path, &workspace_root);

    let content = read_file_content(&path).map_err(|e| format!("Failed to read file: {}", e))?;
    let lines: Vec<&str> = content.lines().collect();

    let (start, end) = if let (Some(range_start), Some(range_end)) = (range_start_line, range_end_line) {
        let start = (range_start as usize).saturating_sub(1);
        let mut end = (range_end as usize).saturating_sub(1);

        if start == end {
            if let Some(ref kind) = symbol_kind {
                if kind == "Constant" || kind == "Variable" {
                    end = expand_variable_range(&lines, start);
                }
            }
        }

        (start, end)
    } else {
        ctx.session.get_or_create_workspace(&path, &workspace_root).await?;
        let client = ctx.session.get_workspace_client(&path, &workspace_root).await
            .ok_or("Failed to get LSP client")?;

        let uri = path_to_uri(&path);
        let symbol_params = json!({
            "textDocument": {"uri": uri}
        });

        let result: Result<DocumentSymbolResponse, _> = client
            .send_request("textDocument/documentSymbol", symbol_params)
            .await;

        match result {
            Ok(response) => {
                if let Some((s, e)) = find_symbol_range(&response, (line as usize).saturating_sub(1)) {
                    (s, e)
                } else {
                    let l = (line as usize).saturating_sub(1);
                    (l, l)
                }
            }
            Err(_) => {
                let l = (line as usize).saturating_sub(1);
                (l, l)
            }
        }
    };

    let (start, end) = if context > 0 {
        let start = start.saturating_sub(context as usize);
        let end = (end + context as usize).min(lines.len().saturating_sub(1));
        (start, end)
    } else {
        (start, end)
    };

    let total_lines = (end - start + 1) as u32;
    let truncated = total_lines > head;
    let end = if truncated {
        start + (head as usize) - 1
    } else {
        end
    };

    let content_slice: Vec<&str> = lines[start..=end.min(lines.len().saturating_sub(1))].to_vec();

    Ok(json!({
        "path": rel_path,
        "start_line": start + 1,
        "end_line": end + 1,
        "content": content_slice.join("\n"),
        "truncated": truncated,
        "total_lines": total_lines,
        "symbol": symbol_name,
    }))
}

fn find_symbol_range(response: &DocumentSymbolResponse, target_line: usize) -> Option<(usize, usize)> {
    match response {
        DocumentSymbolResponse::Nested(symbols) => find_in_document_symbols(symbols, target_line),
        DocumentSymbolResponse::Flat(symbols) => find_in_symbol_information(symbols, target_line),
    }
}

fn find_in_document_symbols(symbols: &[DocumentSymbol], target_line: usize) -> Option<(usize, usize)> {
    for sym in symbols {
        let start = sym.range.start.line as usize;
        let end = sym.range.end.line as usize;

        if start <= target_line && target_line <= end {
            if !sym.children.is_empty() {
                if let Some(child_range) = find_in_document_symbols(&sym.children, target_line) {
                    return Some(child_range);
                }
            }
            return Some((start, end));
        }
    }
    None
}

fn find_in_symbol_information(symbols: &[SymbolInformation], target_line: usize) -> Option<(usize, usize)> {
    for sym in symbols {
        let line = sym.location.range.start.line as usize;
        if line == target_line {
            return Some((line, sym.location.range.end.line as usize));
        }
    }
    None
}

fn expand_variable_range(lines: &[&str], start_line: usize) -> usize {
    if start_line >= lines.len() {
        return start_line;
    }

    let first_line = lines[start_line];

    let mut open_parens = first_line.matches('(').count() as i32 - first_line.matches(')').count() as i32;
    let mut open_brackets = first_line.matches('[').count() as i32 - first_line.matches(']').count() as i32;
    let mut open_braces = first_line.matches('{').count() as i32 - first_line.matches('}').count() as i32;

    let triple_double = first_line.matches("\"\"\"").count();
    let triple_single = first_line.matches("'''").count();
    let mut in_multiline_string = triple_double % 2 == 1 || triple_single % 2 == 1;

    if open_parens == 0 && open_brackets == 0 && open_braces == 0 && !in_multiline_string {
        return start_line;
    }

    for i in (start_line + 1)..lines.len() {
        let line = lines[i];

        if in_multiline_string {
            if line.contains("\"\"\"") || line.contains("'''") {
                in_multiline_string = false;
                if open_parens == 0 && open_brackets == 0 && open_braces == 0 {
                    return i;
                }
            }
            continue;
        }

        open_parens += line.matches('(').count() as i32 - line.matches(')').count() as i32;
        open_brackets += line.matches('[').count() as i32 - line.matches(']').count() as i32;
        open_braces += line.matches('{').count() as i32 - line.matches('}').count() as i32;

        let triple_double = line.matches("\"\"\"").count();
        let triple_single = line.matches("'''").count();
        if triple_double % 2 == 1 || triple_single % 2 == 1 {
            in_multiline_string = true;
            continue;
        }

        if open_parens <= 0 && open_brackets <= 0 && open_braces <= 0 {
            return i;
        }
    }

    start_line
}
