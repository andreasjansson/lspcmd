use std::path::PathBuf;

use leta_fs::read_file_content;
use leta_lsp::lsp_types::{DocumentSymbol, DocumentSymbolParams, DocumentSymbolResponse, SymbolInformation, TextDocumentIdentifier};
use leta_types::ShowParams;

use super::{relative_path, HandlerContext};

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ShowResult {
    pub path: String,
    pub start_line: u32,
    pub end_line: u32,
    pub content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub symbol: Option<String>,
    #[serde(default)]
    pub truncated: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_lines: Option<u32>,
}

pub async fn handle_show(ctx: &HandlerContext, params: ShowParams) -> Result<ShowResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let file_path = PathBuf::from(&params.path);
    let head = params.head.unwrap_or(200);

    let content = read_file_content(&file_path).map_err(|e| format!("Failed to read file: {}", e))?;
    let lines: Vec<&str> = content.lines().collect();
    let rel_path = relative_path(&file_path, &workspace_root);

    let (mut start, mut end) = if let (Some(range_start), Some(range_end)) = (params.range_start_line, params.range_end_line) {
        let start = (range_start - 1) as usize;
        let mut end = (range_end - 1) as usize;

        if start == end && matches!(params.symbol_kind.as_deref(), Some("Constant") | Some("Variable")) {
            end = expand_variable_range(&lines, start);
        }

        (start, end)
    } else {
        let target_line = (params.line - 1) as usize;
        
        let workspace = ctx.session.get_or_create_workspace(&file_path, &workspace_root).await
            .map_err(|e| e.to_string())?;
        
        workspace.ensure_document_open(&file_path).await?;
        let client = workspace.client().await.ok_or("No LSP client")?;
        let uri = leta_fs::path_to_uri(&file_path);

        let response: Option<DocumentSymbolResponse> = client
            .send_request(
                "textDocument/documentSymbol",
                DocumentSymbolParams {
                    text_document: TextDocumentIdentifier { uri: uri.parse().unwrap() },
                    work_done_progress_params: Default::default(),
                    partial_result_params: Default::default(),
                },
            )
            .await
            .map_err(|e| e.to_string())?;

        match response.and_then(|r| find_symbol_range(&r, target_line)) {
            Some((s, e)) => (s, e),
            None => (target_line, target_line),
        }
    };

    if params.context > 0 {
        start = start.saturating_sub(params.context as usize);
        end = (end + params.context as usize).min(lines.len().saturating_sub(1));
    }

    let total_lines = (end - start + 1) as u32;
    let truncated = total_lines > head;
    if truncated {
        end = start + (head as usize) - 1;
    }

    let content = lines[start..=end.min(lines.len() - 1)].join("\n");

    Ok(ShowResult {
        path: rel_path,
        start_line: (start + 1) as u32,
        end_line: (end + 1) as u32,
        content,
        symbol: params.symbol_name,
        truncated,
        total_lines: if truncated { Some(total_lines) } else { None },
    })
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
            if let Some(children) = &sym.children {
                if let Some(child_range) = find_in_document_symbols(children, target_line) {
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
            let end = sym.location.range.end.line as usize;
            return Some((line, end));
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
    let mut in_multiline_string = first_line.matches("\"\"\"").count() % 2 == 1 
        || first_line.matches("'''").count() % 2 == 1;

    if open_parens == 0 && open_brackets == 0 && open_braces == 0 && !in_multiline_string {
        return start_line;
    }

    for (i, line) in lines.iter().enumerate().skip(start_line + 1) {
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

        if line.matches("\"\"\"").count() % 2 == 1 || line.matches("'''").count() % 2 == 1 {
            in_multiline_string = true;
            continue;
        }

        if open_parens <= 0 && open_brackets <= 0 && open_braces <= 0 {
            return i;
        }
    }

    start_line
}
