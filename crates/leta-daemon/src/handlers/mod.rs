use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use globset::Glob;
use leta_cache::LMDBCache;
use leta_fs::{get_language_id, path_to_uri, read_file_content, uri_to_path};
use leta_lsp::{DocumentSymbol, DocumentSymbolResponse, Location, TypeHierarchyItem};
use leta_servers::get_server_for_language;
use leta_types::{SymbolInfo, SymbolKind};
use serde_json::{json, Value};
use tokio::sync::broadcast;
use tracing::{debug, warn};
use walkdir::WalkDir;

use crate::session::Session;

mod grep;
mod show;
mod refs;
mod calls;
mod rename;
mod resolve_symbol;

pub use grep::handle_grep;
pub use show::handle_show;
pub use refs::{handle_references, handle_declaration, handle_implementations, handle_subtypes, handle_supertypes};
pub use calls::handle_calls;
pub use rename::{handle_rename, handle_move_file};
pub use resolve_symbol::handle_resolve_symbol;

pub struct HandlerContext {
    pub session: Arc<Session>,
    pub hover_cache: Arc<LMDBCache>,
    pub symbol_cache: Arc<LMDBCache>,
    pub shutdown_tx: broadcast::Sender<()>,
}

pub async fn handle_request(ctx: &HandlerContext, method: &str, params: Value) -> Value {
    let result = match method {
        "shutdown" => handle_shutdown(ctx).await,
        "describe-session" => handle_describe_session(ctx).await,
        "grep" => handle_grep(ctx, params).await,
        "files" => handle_files(ctx, params).await,
        "show" => handle_show(ctx, params).await,
        "references" => handle_references(ctx, params).await,
        "declaration" => handle_declaration(ctx, params).await,
        "implementations" => handle_implementations(ctx, params).await,
        "subtypes" => handle_subtypes(ctx, params).await,
        "supertypes" => handle_supertypes(ctx, params).await,
        "calls" => handle_calls(ctx, params).await,
        "rename" => handle_rename(ctx, params).await,
        "move-file" => handle_move_file(ctx, params).await,
        "resolve-symbol" => handle_resolve_symbol(ctx, params).await,
        "restart-workspace" => handle_restart_workspace(ctx, params).await,
        "remove-workspace" => handle_remove_workspace(ctx, params).await,
        "raw-lsp-request" => handle_raw_lsp_request(ctx, params).await,
        _ => Err(format!("Unknown method: {}", method)),
    };

    match result {
        Ok(value) => json!({"result": value}),
        Err(e) => json!({"error": e}),
    }
}

async fn handle_shutdown(ctx: &HandlerContext) -> Result<Value, String> {
    let _ = ctx.shutdown_tx.send(());
    Ok(json!({"status": "shutting_down"}))
}

async fn handle_describe_session(ctx: &HandlerContext) -> Result<Value, String> {
    let session_info = ctx.session.describe().await;
    let hover_info = ctx.hover_cache.info();
    let symbol_info = ctx.symbol_cache.info();

    Ok(json!({
        "daemon_pid": std::process::id(),
        "caches": {
            "hover_cache": {
                "current_bytes": hover_info.current_bytes,
                "max_bytes": hover_info.max_bytes,
                "entries": hover_info.entries,
            },
            "symbol_cache": {
                "current_bytes": symbol_info.current_bytes,
                "max_bytes": symbol_info.max_bytes,
                "entries": symbol_info.entries,
            }
        },
        "workspaces": session_info.get("workspaces").unwrap_or(&json!([]))
    }))
}

async fn handle_files(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    let workspace_root = PathBuf::from(
        params.get("workspace_root")
            .and_then(|v| v.as_str())
            .ok_or("Missing workspace_root")?
    );
    let subpath = params.get("subpath").and_then(|v| v.as_str()).map(PathBuf::from);
    let exclude_patterns: Vec<String> = params.get("exclude_patterns")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();
    let include_patterns: Vec<String> = params.get("include_patterns")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();

    let target = subpath.unwrap_or_else(|| workspace_root.clone());
    
    let default_excludes: std::collections::HashSet<&str> = [
        ".git", "__pycache__", "node_modules", ".venv", "venv", "target",
        "build", "dist", ".tox", ".mypy_cache", ".pytest_cache", ".eggs",
        ".cache", ".coverage", ".hypothesis", ".nox", ".ruff_cache",
        "__pypackages__", ".pants.d", ".pyre", ".pytype", "vendor",
        "third_party", ".bundle", ".next", ".nuxt", ".svelte-kit",
        ".turbo", ".parcel-cache", "coverage", ".nyc_output", ".zig-cache",
    ].into_iter().collect();

    let include_set: std::collections::HashSet<&str> = include_patterns.iter().map(|s| s.as_str()).collect();
    
    let mut files_map: HashMap<String, Value> = HashMap::new();
    let mut total_bytes: u64 = 0;
    let mut total_lines: u32 = 0;

    for entry in WalkDir::new(&target)
        .into_iter()
        .filter_entry(|e| {
            let name = e.file_name().to_str().unwrap_or("");
            if e.file_type().is_dir() {
                if include_set.contains(name) {
                    return true;
                }
                if default_excludes.contains(name) {
                    return false;
                }
                if name.ends_with(".egg-info") {
                    return false;
                }
            }
            !name.starts_with('.')
        })
        .filter_map(|e| e.ok())
    {
        if !entry.file_type().is_file() {
            continue;
        }

        let path = entry.path();
        let rel_path = path.strip_prefix(&workspace_root)
            .unwrap_or(path)
            .to_string_lossy()
            .to_string();

        if is_excluded(&rel_path, &exclude_patterns) {
            continue;
        }

        let metadata = std::fs::metadata(path).ok();
        let bytes = metadata.as_ref().map(|m| m.len()).unwrap_or(0);
        let lines = std::fs::read_to_string(path)
            .map(|c| c.lines().count() as u32)
            .unwrap_or(0);

        total_bytes += bytes;
        total_lines += lines;

        files_map.insert(rel_path.clone(), json!({
            "path": rel_path,
            "bytes": bytes,
            "lines": lines,
            "symbols": {}
        }));
    }

    Ok(json!({
        "files": files_map,
        "total_files": files_map.len(),
        "total_bytes": total_bytes,
        "total_lines": total_lines,
    }))
}

async fn handle_restart_workspace(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    let workspace_root = PathBuf::from(
        params.get("workspace_root")
            .and_then(|v| v.as_str())
            .ok_or("Missing workspace_root")?
    );

    let restarted = ctx.session.restart_workspace(&workspace_root).await;
    Ok(json!({"restarted": restarted}))
}

async fn handle_remove_workspace(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    let workspace_root = PathBuf::from(
        params.get("workspace_root")
            .and_then(|v| v.as_str())
            .ok_or("Missing workspace_root")?
    );

    let stopped = ctx.session.close_workspace(&workspace_root).await;
    Ok(json!({"servers_stopped": stopped}))
}

async fn handle_raw_lsp_request(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    let workspace_root = PathBuf::from(
        params.get("workspace_root")
            .and_then(|v| v.as_str())
            .ok_or("Missing workspace_root")?
    );
    let method = params.get("method")
        .and_then(|v| v.as_str())
        .ok_or("Missing method")?;
    let lsp_params = params.get("params").cloned().unwrap_or(json!({}));
    let language = params.get("language")
        .and_then(|v| v.as_str())
        .unwrap_or("python");

    ctx.session.get_or_create_workspace_for_language(language, &workspace_root).await?;
    let client = ctx.session.get_workspace_client_for_language(language, &workspace_root).await
        .ok_or("Failed to get LSP client")?;

    let result = client.send_request_raw(method, lsp_params).await
        .map_err(|e| format!("LSP error: {}", e))?;

    Ok(result)
}

pub fn relative_path(path: &Path, workspace_root: &Path) -> String {
    path.canonicalize()
        .unwrap_or_else(|_| path.to_path_buf())
        .strip_prefix(workspace_root.canonicalize().unwrap_or_else(|_| workspace_root.to_path_buf()))
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|_| path.to_string_lossy().to_string())
}

pub fn is_excluded(rel_path: &str, exclude_patterns: &[String]) -> bool {
    let path = Path::new(rel_path);
    let parts: Vec<&str> = path.iter().filter_map(|s| s.to_str()).collect();

    for pat in exclude_patterns {
        if rel_path.contains(pat) {
            return true;
        }
        if !pat.contains('/') && !pat.contains('*') && !pat.contains('?') {
            if parts.contains(&pat.as_str()) {
                return true;
            }
        }
        if let Some(filename) = path.file_name().and_then(|f| f.to_str()) {
            if glob_match(pat, filename) {
                return true;
            }
        }
        if glob_match(pat, rel_path) {
            return true;
        }
    }
    false
}

fn glob_match(pattern: &str, text: &str) -> bool {
    if let Ok(glob) = Glob::new(pattern) {
        glob.compile_matcher().is_match(text)
    } else {
        false
    }
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct SymbolDict {
    pub name: String,
    pub kind: String,
    pub path: String,
    pub line: u32,
    pub column: u32,
    pub container: Option<String>,
    pub detail: Option<String>,
    pub documentation: Option<String>,
    pub range_start_line: Option<u32>,
    pub range_end_line: Option<u32>,
}

impl From<SymbolDict> for SymbolInfo {
    fn from(s: SymbolDict) -> Self {
        SymbolInfo {
            name: s.name,
            kind: s.kind,
            path: s.path,
            line: s.line,
            column: s.column,
            container: s.container,
            detail: s.detail,
            documentation: s.documentation,
            range_start_line: s.range_start_line,
            range_end_line: s.range_end_line,
            r#ref: None,
        }
    }
}

pub fn flatten_symbols(
    response: &DocumentSymbolResponse,
    file_path: &str,
    container: Option<&str>,
) -> Vec<SymbolDict> {
    let mut result = Vec::new();

    match response {
        DocumentSymbolResponse::Nested(symbols) => {
            flatten_document_symbols(symbols, file_path, container, &mut result);
        }
        DocumentSymbolResponse::Flat(symbols) => {
            for sym in symbols {
                result.push(SymbolDict {
                    name: sym.name.clone(),
                    kind: SymbolKind::from_lsp_kind(sym.kind).to_string(),
                    path: file_path.to_string(),
                    line: sym.location.range.start.line + 1,
                    column: sym.location.range.start.character,
                    container: sym.container_name.clone(),
                    detail: None,
                    documentation: None,
                    range_start_line: Some(sym.location.range.start.line + 1),
                    range_end_line: Some(sym.location.range.end.line + 1),
                });
            }
        }
    }

    result
}

fn flatten_document_symbols(
    symbols: &[DocumentSymbol],
    file_path: &str,
    container: Option<&str>,
    output: &mut Vec<SymbolDict>,
) {
    for sym in symbols {
        output.push(SymbolDict {
            name: sym.name.clone(),
            kind: SymbolKind::from_lsp_kind(sym.kind).to_string(),
            path: file_path.to_string(),
            line: sym.selection_range.start.line + 1,
            column: sym.selection_range.start.character,
            container: container.map(String::from),
            detail: sym.detail.clone(),
            documentation: None,
            range_start_line: Some(sym.range.start.line + 1),
            range_end_line: Some(sym.range.end.line + 1),
        });

        if !sym.children.is_empty() {
            flatten_document_symbols(&sym.children, file_path, Some(&sym.name), output);
        }
    }
}

pub async fn collect_all_workspace_symbols(
    ctx: &HandlerContext,
    workspace_root: &Path,
) -> Result<Vec<SymbolDict>, String> {
    let config = ctx.session.config.read().await;
    let excluded_languages: std::collections::HashSet<String> = config.workspaces.excluded_languages.iter().cloned().collect();
    drop(config);

    let skip_dirs: std::collections::HashSet<&str> = [
        "node_modules", "__pycache__", ".git", "venv", ".venv",
        "build", "dist", ".tox", ".eggs",
    ].into_iter().collect();

    let mut languages_found: HashMap<String, Vec<PathBuf>> = HashMap::new();

    for entry in WalkDir::new(workspace_root)
        .into_iter()
        .filter_entry(|e| {
            let name = e.file_name().to_str().unwrap_or("");
            if e.file_type().is_dir() {
                !skip_dirs.contains(name) && !name.starts_with('.') && !name.ends_with(".egg-info")
            } else {
                true
            }
        })
        .filter_map(|e| e.ok())
    {
        if !entry.file_type().is_file() {
            continue;
        }

        let path = entry.path();
        let lang_id = get_language_id(path);
        
        if lang_id == "plaintext" || excluded_languages.contains(lang_id) {
            continue;
        }

        let config = ctx.session.config.read().await;
        if get_server_for_language(lang_id, Some(&*config)).is_none() {
            continue;
        }
        drop(config);

        languages_found
            .entry(lang_id.to_string())
            .or_default()
            .push(path.to_path_buf());
    }

    let mut all_symbols = Vec::new();

    for (lang_id, files) in languages_found {
        if let Err(e) = ctx.session.get_or_create_workspace_for_language(&lang_id, workspace_root).await {
            warn!("Failed to create workspace for {}: {}", lang_id, e);
            continue;
        }

        let client = match ctx.session.get_workspace_client_for_language(&lang_id, workspace_root).await {
            Some(c) => c,
            None => continue,
        };

        for file_path in &files {
            let symbols = get_file_symbols_cached(ctx, &client, workspace_root, file_path).await;
            all_symbols.extend(symbols);
        }
    }

    Ok(all_symbols)
}

pub async fn collect_symbols_for_paths(
    ctx: &HandlerContext,
    paths: &[PathBuf],
    workspace_root: &Path,
) -> Result<Vec<SymbolDict>, String> {
    let mut files_by_language: HashMap<String, Vec<PathBuf>> = HashMap::new();

    for file_path in paths {
        if !file_path.exists() {
            continue;
        }
        let lang = get_language_id(file_path);
        if lang != "plaintext" {
            files_by_language
                .entry(lang.to_string())
                .or_default()
                .push(file_path.clone());
        }
    }

    let mut all_symbols = Vec::new();

    for (lang, files) in files_by_language {
        if let Err(e) = ctx.session.get_or_create_workspace_for_language(&lang, workspace_root).await {
            warn!("Failed to create workspace for {}: {}", lang, e);
            continue;
        }

        let client = match ctx.session.get_workspace_client_for_language(&lang, workspace_root).await {
            Some(c) => c,
            None => continue,
        };

        for file_path in &files {
            let symbols = get_file_symbols_cached(ctx, &client, workspace_root, file_path).await;
            all_symbols.extend(symbols);
        }
    }

    Ok(all_symbols)
}

async fn get_file_symbols_cached(
    ctx: &HandlerContext,
    client: &Arc<leta_lsp::LspClient>,
    workspace_root: &Path,
    file_path: &Path,
) -> Vec<SymbolDict> {
    let file_sha = get_file_sha(file_path);
    let cache_key = (file_path.to_string_lossy().to_string(), workspace_root.to_string_lossy().to_string(), file_sha.clone());

    if let Some(cached) = ctx.symbol_cache.get::<_, Vec<SymbolDict>>(&cache_key) {
        return cached;
    }

    let uri = path_to_uri(file_path);
    let rel_path = relative_path(file_path, workspace_root);

    if let Err(e) = ctx.session.ensure_document_open(file_path, workspace_root).await {
        debug!("Failed to open document {}: {}", file_path.display(), e);
        return Vec::new();
    }

    let params = json!({
        "textDocument": {"uri": uri}
    });

    let result: Result<DocumentSymbolResponse, _> = client.send_request("textDocument/documentSymbol", params).await;

    let symbols = match result {
        Ok(response) => flatten_symbols(&response, &rel_path, None),
        Err(e) => {
            debug!("Failed to get symbols for {}: {}", file_path.display(), e);
            Vec::new()
        }
    };

    let final_sha = get_file_sha(file_path);
    let final_cache_key = (file_path.to_string_lossy().to_string(), workspace_root.to_string_lossy().to_string(), final_sha);
    let _ = ctx.symbol_cache.set(&final_cache_key, &symbols);

    symbols
}

fn get_file_sha(path: &Path) -> String {
    std::fs::read(path)
        .map(|bytes| {
            let hash = blake3::hash(&bytes);
            hash.to_hex()[..16].to_string()
        })
        .unwrap_or_default()
}

pub fn format_locations(
    locations: &[Location],
    workspace_root: &Path,
    context: u32,
) -> Vec<Value> {
    let mut result = Vec::new();

    for loc in locations {
        let file_path = uri_to_path(&loc.uri);
        let rel_path = relative_path(&file_path, workspace_root);
        let line = loc.range.start.line + 1;

        let mut location = json!({
            "path": rel_path,
            "line": line,
            "column": loc.range.start.character,
        });

        if context > 0 {
            if let Ok(content) = read_file_content(&file_path) {
                let lines: Vec<&str> = content.lines().collect();
                let center = (line as usize).saturating_sub(1);
                let start = center.saturating_sub(context as usize);
                let end = (center + context as usize).min(lines.len().saturating_sub(1));

                let context_lines: Vec<String> = lines[start..=end].iter().map(|s| s.to_string()).collect();
                location["context_lines"] = json!(context_lines);
                location["context_start"] = json!(start + 1);
            }
        }

        result.push(location);
    }

    result.sort_by(|a, b| {
        let path_a = a.get("path").and_then(|v| v.as_str()).unwrap_or("");
        let path_b = b.get("path").and_then(|v| v.as_str()).unwrap_or("");
        let line_a = a.get("line").and_then(|v| v.as_u64()).unwrap_or(0);
        let line_b = b.get("line").and_then(|v| v.as_u64()).unwrap_or(0);
        (path_a, line_a).cmp(&(path_b, line_b))
    });

    result
}

pub fn format_type_hierarchy_items(
    items: &[TypeHierarchyItem],
    workspace_root: &Path,
    context: u32,
) -> Vec<Value> {
    let mut result = Vec::new();
    let mut seen = std::collections::HashSet::new();

    for item in items {
        let file_path = uri_to_path(&item.uri);
        let rel_path = relative_path(&file_path, workspace_root);
        let line = item.selection_range.start.line + 1;

        let key = (rel_path.clone(), line);
        if seen.contains(&key) {
            continue;
        }
        seen.insert(key);

        let mut location = json!({
            "path": rel_path,
            "line": line,
            "column": item.selection_range.start.character,
            "name": item.name,
            "kind": SymbolKind::from_lsp_kind(item.kind).to_string(),
        });

        if let Some(detail) = &item.detail {
            location["detail"] = json!(detail);
        }

        if context > 0 {
            if let Ok(content) = read_file_content(&file_path) {
                let lines: Vec<&str> = content.lines().collect();
                let center = (line as usize).saturating_sub(1);
                let start = center.saturating_sub(context as usize);
                let end = (center + context as usize).min(lines.len().saturating_sub(1));

                let context_lines: Vec<String> = lines[start..=end].iter().map(|s| s.to_string()).collect();
                location["context_lines"] = json!(context_lines);
                location["context_start"] = json!(start + 1);
            }
        }

        result.push(location);
    }

    result.sort_by(|a, b| {
        let path_a = a.get("path").and_then(|v| v.as_str()).unwrap_or("");
        let path_b = b.get("path").and_then(|v| v.as_str()).unwrap_or("");
        let line_a = a.get("line").and_then(|v| v.as_u64()).unwrap_or(0);
        let line_b = b.get("line").and_then(|v| v.as_u64()).unwrap_or(0);
        (path_a, line_a).cmp(&(path_b, line_b))
    });

    result
}
