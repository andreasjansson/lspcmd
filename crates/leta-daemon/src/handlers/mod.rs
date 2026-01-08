mod grep;
mod show;
mod refs;
mod calls;
mod rename;
mod files;
mod resolve;
mod session;
mod index;

use std::path::Path;
use std::sync::Arc;

use leta_fs::{get_lines_around, read_file_content, uri_to_path};
use leta_lsp::lsp_types::{DocumentSymbol, DocumentSymbolResponse, Location, SymbolInformation, TypeHierarchyItem};
use leta_types::{LocationInfo, SymbolInfo, SymbolKind};

pub use grep::{handle_grep, get_file_symbols};
pub use index::handle_add_workspace;
pub use show::handle_show;
pub use refs::{handle_references, handle_declaration, handle_implementations, handle_subtypes, handle_supertypes};
pub use calls::handle_calls;
pub use rename::{handle_rename, handle_move_file};
pub use files::handle_files;
pub use resolve::handle_resolve_symbol;
pub use session::{handle_describe_session, handle_restart_workspace, handle_remove_workspace};

use crate::session::Session;
use leta_cache::LmdbCache;

pub struct HandlerContext {
    pub session: Arc<Session>,
    pub hover_cache: Arc<LmdbCache>,
    pub symbol_cache: Arc<LmdbCache>,
}

impl HandlerContext {
    pub fn new(session: Arc<Session>, hover_cache: Arc<LmdbCache>, symbol_cache: Arc<LmdbCache>) -> Self {
        Self {
            session,
            hover_cache,
            symbol_cache,
        }
    }
}

pub fn relative_path(path: &Path, workspace_root: &Path) -> String {
    path.strip_prefix(workspace_root)
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|_| path.to_string_lossy().to_string())
}

pub fn find_source_files_with_extension(workspace_root: &Path, extension: &str) -> Vec<std::path::PathBuf> {
    let mut files = Vec::new();
    let walker = ignore::WalkBuilder::new(workspace_root)
        .hidden(true)
        .git_ignore(true)
        .build();
    
    for entry in walker.flatten() {
        let path = entry.path();
        if path.is_file() {
            if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
                if ext == extension {
                    files.push(path.to_path_buf());
                }
            }
        }
    }
    files
}

pub fn flatten_document_symbols(
    symbols: &DocumentSymbolResponse,
    file_path: &str,
) -> Vec<SymbolInfo> {
    let mut result = Vec::new();
    match symbols {
        DocumentSymbolResponse::Flat(syms) => {
            for sym in syms {
                result.push(symbol_info_from_symbol_information(sym, file_path));
            }
        }
        DocumentSymbolResponse::Nested(syms) => {
            flatten_nested_symbols(syms, file_path, None, &mut result);
        }
    }
    result
}

fn flatten_nested_symbols(
    symbols: &[DocumentSymbol],
    file_path: &str,
    container: Option<&str>,
    output: &mut Vec<SymbolInfo>,
) {
    for sym in symbols {
        let kind = SymbolKind::from_lsp(sym.kind);
        let mut info = SymbolInfo::new(
            sym.name.clone(),
            kind,
            file_path.to_string(),
            sym.selection_range.start.line + 1,
        );
        info.column = sym.selection_range.start.character;
        info.container = container.map(String::from);
        info.detail = sym.detail.clone();
        info.range_start_line = Some(sym.range.start.line + 1);
        info.range_end_line = Some(sym.range.end.line + 1);
        output.push(info);

        if let Some(children) = &sym.children {
            flatten_nested_symbols(children, file_path, Some(&sym.name), output);
        }
    }
}

fn symbol_info_from_symbol_information(sym: &SymbolInformation, file_path: &str) -> SymbolInfo {
    let kind = SymbolKind::from_lsp(sym.kind);
    let mut info = SymbolInfo::new(
        sym.name.clone(),
        kind,
        file_path.to_string(),
        sym.location.range.start.line + 1,
    );
    info.column = sym.location.range.start.character;
    info.container = sym.container_name.clone();
    info.range_start_line = Some(sym.location.range.start.line + 1);
    info.range_end_line = Some(sym.location.range.end.line + 1);
    info
}

pub fn format_locations(
    locations: &[Location],
    workspace_root: &Path,
    context: u32,
) -> Vec<LocationInfo> {
    let mut result = Vec::new();

    for loc in locations {
        let file_path = uri_to_path(loc.uri.as_str());
        let rel_path = relative_path(&file_path, workspace_root);
        let line = loc.range.start.line + 1;

        let mut info = LocationInfo::new(rel_path, line);
        info.column = loc.range.start.character;

        if context > 0 && file_path.exists() {
            if let Ok(content) = read_file_content(&file_path) {
                let (lines, start, _) = get_lines_around(&content, loc.range.start.line as usize, context as usize);
                info.context_lines = Some(lines);
                info.context_start = Some(start as u32 + 1);
            }
        }

        result.push(info);
    }

    result.sort_by(|a, b| (&a.path, a.line).cmp(&(&b.path, b.line)));
    result
}

pub fn format_type_hierarchy_items(
    items: &[TypeHierarchyItem],
    workspace_root: &Path,
    context: u32,
) -> Vec<LocationInfo> {
    let mut result = Vec::new();
    let mut seen = std::collections::HashSet::new();

    for item in items {
        let file_path = uri_to_path(item.uri.as_str());
        let rel_path = relative_path(&file_path, workspace_root);
        let line = item.selection_range.start.line + 1;

        let key = (rel_path.clone(), line);
        if seen.contains(&key) {
            continue;
        }
        seen.insert(key);

        let mut info = LocationInfo::new(rel_path, line);
        info.column = item.selection_range.start.character;
        info.name = Some(item.name.clone());
        info.kind = Some(SymbolKind::from_lsp(item.kind).to_string());
        info.detail = item.detail.clone();

        if context > 0 && file_path.exists() {
            if let Ok(content) = read_file_content(&file_path) {
                let (lines, start, _) = get_lines_around(&content, item.selection_range.start.line as usize, context as usize);
                info.context_lines = Some(lines);
                info.context_start = Some(start as u32 + 1);
            }
        }

        result.push(info);
    }

    result.sort_by(|a, b| (&a.path, a.line).cmp(&(&b.path, b.line)));
    result
}

pub fn format_type_hierarchy_items_from_json(
    items: &[serde_json::Value],
    workspace_root: &Path,
    context: u32,
) -> Vec<LocationInfo> {
    let mut result = Vec::new();
    let mut seen = std::collections::HashSet::new();

    for item in items {
        let uri = match item.get("uri").and_then(|v| v.as_str()) {
            Some(u) => u,
            None => continue,
        };
        let name = match item.get("name").and_then(|v| v.as_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        let kind_num = item.get("kind").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
        let selection_range = match item.get("selectionRange") {
            Some(r) => r,
            None => continue,
        };
        let start_line = selection_range
            .get("start")
            .and_then(|s| s.get("line"))
            .and_then(|l| l.as_u64())
            .unwrap_or(0) as u32;
        let start_char = selection_range
            .get("start")
            .and_then(|s| s.get("character"))
            .and_then(|c| c.as_u64())
            .unwrap_or(0) as u32;
        let detail = item.get("detail").and_then(|v| v.as_str()).map(String::from);

        let file_path = uri_to_path(uri);
        let rel_path = relative_path(&file_path, workspace_root);
        let line = start_line + 1;

        let key = (rel_path.clone(), line);
        if seen.contains(&key) {
            continue;
        }
        seen.insert(key);

        let lsp_kind = match kind_num {
            1 => leta_lsp::lsp_types::SymbolKind::FILE,
            2 => leta_lsp::lsp_types::SymbolKind::MODULE,
            3 => leta_lsp::lsp_types::SymbolKind::NAMESPACE,
            4 => leta_lsp::lsp_types::SymbolKind::PACKAGE,
            5 => leta_lsp::lsp_types::SymbolKind::CLASS,
            6 => leta_lsp::lsp_types::SymbolKind::METHOD,
            7 => leta_lsp::lsp_types::SymbolKind::PROPERTY,
            8 => leta_lsp::lsp_types::SymbolKind::FIELD,
            9 => leta_lsp::lsp_types::SymbolKind::CONSTRUCTOR,
            10 => leta_lsp::lsp_types::SymbolKind::ENUM,
            11 => leta_lsp::lsp_types::SymbolKind::INTERFACE,
            12 => leta_lsp::lsp_types::SymbolKind::FUNCTION,
            13 => leta_lsp::lsp_types::SymbolKind::VARIABLE,
            14 => leta_lsp::lsp_types::SymbolKind::CONSTANT,
            15 => leta_lsp::lsp_types::SymbolKind::STRING,
            16 => leta_lsp::lsp_types::SymbolKind::NUMBER,
            17 => leta_lsp::lsp_types::SymbolKind::BOOLEAN,
            18 => leta_lsp::lsp_types::SymbolKind::ARRAY,
            19 => leta_lsp::lsp_types::SymbolKind::OBJECT,
            20 => leta_lsp::lsp_types::SymbolKind::KEY,
            21 => leta_lsp::lsp_types::SymbolKind::NULL,
            22 => leta_lsp::lsp_types::SymbolKind::ENUM_MEMBER,
            23 => leta_lsp::lsp_types::SymbolKind::STRUCT,
            24 => leta_lsp::lsp_types::SymbolKind::EVENT,
            25 => leta_lsp::lsp_types::SymbolKind::OPERATOR,
            26 => leta_lsp::lsp_types::SymbolKind::TYPE_PARAMETER,
            _ => leta_lsp::lsp_types::SymbolKind::VARIABLE,
        };
        let mut info = LocationInfo::new(rel_path, line);
        info.column = start_char;
        info.name = Some(name);
        info.kind = Some(SymbolKind::from_lsp(lsp_kind).to_string());
        info.detail = detail;

        if context > 0 && file_path.exists() {
            if let Ok(content) = read_file_content(&file_path) {
                let (lines, start, _) = get_lines_around(&content, start_line as usize, context as usize);
                info.context_lines = Some(lines);
                info.context_start = Some(start as u32 + 1);
            }
        }

        result.push(info);
    }

    result.sort_by(|a, b| (&a.path, a.line).cmp(&(&b.path, b.line)));
    result
}
