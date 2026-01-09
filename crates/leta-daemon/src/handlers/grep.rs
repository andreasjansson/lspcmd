use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use fastrace::trace;
use leta_fs::{get_language_id, read_file_content};
use leta_lsp::lsp_types::{DocumentSymbolParams, TextDocumentIdentifier};
use leta_servers::get_server_for_language;
use leta_types::{GrepParams, GrepResult, SymbolInfo};
use regex::Regex;
use tracing::debug;

use super::{flatten_document_symbols, relative_path, HandlerContext};
use crate::session::WorkspaceHandle;

const SKIP_DIRS: &[&str] = &[
    "node_modules",
    "__pycache__",
    ".git",
    "venv",
    ".venv",
    "build",
    "dist",
    ".tox",
    ".eggs",
    "target",
];

fn should_use_prefilter(pattern: &str) -> bool {
    if pattern.is_empty() {
        return false;
    }
    let core = pattern
        .trim_start_matches("(?i)")
        .trim_start_matches('^')
        .trim_end_matches('$');
    if core.len() <= 2 {
        return false;
    }
    if core == ".*" || core == ".+" || core == ".?" {
        return false;
    }
    true
}

fn pattern_to_text_regex(pattern: &str) -> Option<Regex> {
    let core = pattern
        .trim_start_matches("(?i)")
        .trim_start_matches('^')
        .trim_end_matches('$');

    let flags = if pattern.starts_with("(?i)") {
        "(?i)"
    } else {
        ""
    };

    Regex::new(&format!("{}{}", flags, core)).ok()
}

#[trace]
fn find_candidate_files(
    workspace_root: &Path,
    pattern: &str,
    excluded_languages: &HashSet<String>,
) -> Vec<PathBuf> {
    let skip_dirs: HashSet<&str> = SKIP_DIRS.iter().copied().collect();
    let text_regex = match pattern_to_text_regex(pattern) {
        Some(r) => r,
        None => return Vec::new(),
    };

    let mut candidates = Vec::new();

    for entry in walkdir::WalkDir::new(workspace_root)
        .into_iter()
        .filter_entry(|e| {
            let name = e.file_name().to_string_lossy();
            !name.starts_with('.')
                && !skip_dirs.contains(name.as_ref())
                && !name.ends_with(".egg-info")
        })
    {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };

        if !entry.file_type().is_file() {
            continue;
        }

        let path = entry.path();
        let lang = get_language_id(path);

        if lang == "plaintext" || excluded_languages.contains(lang) {
            continue;
        }

        if get_server_for_language(lang, None).is_none() {
            continue;
        }

        if let Ok(content) = read_file_content(path) {
            if text_regex.is_match(&content) {
                candidates.push(path.to_path_buf());
            }
        }
    }

    candidates
}

#[trace]
pub async fn handle_grep(ctx: &HandlerContext, params: GrepParams) -> Result<GrepResult, String> {
    debug!(
        "handle_grep: pattern={} workspace={}",
        params.pattern, params.workspace_root
    );
    let workspace_root = PathBuf::from(&params.workspace_root);

    let flags = if params.case_sensitive { "" } else { "(?i)" };
    let pattern = format!("{}{}", flags, params.pattern);
    let regex =
        Regex::new(&pattern).map_err(|e| format!("Invalid regex '{}': {}", params.pattern, e))?;

    let kinds_set: Option<HashSet<String>> = params
        .kinds
        .map(|k| k.into_iter().map(|s| s.to_lowercase()).collect());

    let symbols = if let Some(paths) = params.paths {
        collect_symbols_for_paths(ctx, &paths, &workspace_root).await?
    } else if should_use_prefilter(&pattern) {
        let config = ctx.session.config().await;
        let excluded_languages: HashSet<String> = config
            .workspaces
            .excluded_languages
            .iter()
            .cloned()
            .collect();
        let candidates = find_candidate_files(&workspace_root, &pattern, &excluded_languages);
        debug!(
            "Prefilter found {} candidate files for pattern '{}'",
            candidates.len(),
            params.pattern
        );
        if candidates.is_empty() {
            Vec::new()
        } else {
            let paths: Vec<String> = candidates
                .iter()
                .map(|p| p.to_string_lossy().to_string())
                .collect();
            collect_symbols_for_paths(ctx, &paths, &workspace_root).await?
        }
    } else {
        super::collect_all_workspace_symbols(ctx, &workspace_root).await?
    };

    let mut filtered: Vec<SymbolInfo> = symbols
        .into_iter()
        .filter(|s| {
            if !regex.is_match(&s.name) {
                return false;
            }
            if let Some(ref kinds) = kinds_set {
                if !kinds.contains(&s.kind.to_lowercase()) {
                    return false;
                }
            }
            if !params.exclude_patterns.is_empty() {
                if is_excluded(&s.path, &params.exclude_patterns) {
                    return false;
                }
            }
            true
        })
        .collect();

    if params.include_docs {
        for sym in &mut filtered {
            if let Some(doc) =
                get_symbol_documentation(ctx, &workspace_root, &sym.path, sym.line, sym.column)
                    .await
            {
                sym.documentation = Some(doc);
            }
        }
    }

    // Sort by path and line for deterministic output
    filtered.sort_by(|a, b| (&a.path, a.line).cmp(&(&b.path, b.line)));

    let warning = if filtered.is_empty() && params.pattern.contains(r"\|") {
        Some("No results. Note: use '|' for alternation, not '\\|' (e.g., 'foo|bar' not 'foo\\|bar')".to_string())
    } else {
        None
    };

    Ok(GrepResult {
        symbols: filtered,
        warning,
    })
}

#[trace]
pub async fn collect_symbols_with_prefilter(
    ctx: &HandlerContext,
    workspace_root: &Path,
    text_pattern: Option<&str>,
) -> Result<Vec<SymbolInfo>, String> {
    let config = ctx.session.config().await;
    let excluded_languages: HashSet<String> = config
        .workspaces
        .excluded_languages
        .iter()
        .cloned()
        .collect();

    let use_prefilter = text_pattern
        .map(|p| should_use_prefilter(p))
        .unwrap_or(false);

    if use_prefilter {
        let pattern = text_pattern.unwrap();
        let candidates = find_candidate_files(workspace_root, pattern, &excluded_languages);
        debug!(
            "Prefilter found {} candidate files for pattern '{}'",
            candidates.len(),
            pattern
        );
        if candidates.is_empty() {
            return Ok(Vec::new());
        }
        let paths: Vec<String> = candidates
            .iter()
            .map(|p| p.to_string_lossy().to_string())
            .collect();
        collect_symbols_for_paths(ctx, &paths, workspace_root).await
    } else {
        super::collect_all_workspace_symbols(ctx, workspace_root).await
    }
}

#[trace]
async fn collect_symbols_for_paths(
    ctx: &HandlerContext,
    paths: &[String],
    workspace_root: &Path,
) -> Result<Vec<SymbolInfo>, String> {
    let mut all_symbols = Vec::new();
    let mut files_by_lang: HashMap<String, Vec<PathBuf>> = HashMap::new();

    for path_str in paths {
        let path = PathBuf::from(path_str);
        if !path.exists() {
            continue;
        }
        let lang = get_language_id(&path);
        if lang != "plaintext" {
            files_by_lang
                .entry(lang.to_string())
                .or_default()
                .push(path);
        }
    }

    for (lang, files) in files_by_lang {
        if get_server_for_language(&lang, None).is_none() {
            continue;
        }

        let workspace = match ctx
            .session
            .get_or_create_workspace_for_language(&lang, workspace_root)
            .await
        {
            Ok(ws) => ws,
            Err(_) => continue,
        };

        workspace.wait_for_ready(30).await;

        for file_path in files {
            if let Ok(symbols) = get_file_symbols(ctx, &workspace, workspace_root, &file_path).await
            {
                all_symbols.extend(symbols);
            }
        }
    }

    Ok(all_symbols)
}

#[trace]
pub async fn get_file_symbols(
    ctx: &HandlerContext,
    workspace: &WorkspaceHandle<'_>,
    workspace_root: &Path,
    file_path: &Path,
) -> Result<Vec<SymbolInfo>, String> {
    use std::sync::atomic::Ordering;

    let file_sha = leta_fs::file_sha(file_path);
    let cache_key = format!(
        "{}:{}:{}",
        file_path.display(),
        workspace_root.display(),
        file_sha
    );

    if let Some(cached) = ctx.symbol_cache.get::<Vec<SymbolInfo>>(&cache_key) {
        ctx.cache_stats.symbol_hits.fetch_add(1, Ordering::Relaxed);
        return Ok(cached);
    }
    ctx.cache_stats
        .symbol_misses
        .fetch_add(1, Ordering::Relaxed);

    let client = workspace.client().await.ok_or("No LSP client")?;
    let uri = leta_fs::path_to_uri(file_path);

    workspace.ensure_document_open(file_path).await?;

    let response: Option<leta_lsp::lsp_types::DocumentSymbolResponse> = client
        .send_request(
            "textDocument/documentSymbol",
            DocumentSymbolParams {
                text_document: TextDocumentIdentifier {
                    uri: uri.parse().unwrap(),
                },
                work_done_progress_params: Default::default(),
                partial_result_params: Default::default(),
            },
        )
        .await
        .map_err(|e| e.to_string())?;

    let symbols = match response {
        Some(resp) => {
            let rel_path = relative_path(file_path, workspace_root);
            flatten_document_symbols(&resp, &rel_path)
        }
        None => Vec::new(),
    };

    ctx.symbol_cache.set(&cache_key, &symbols);
    Ok(symbols)
}

#[trace]
async fn get_symbol_documentation(
    ctx: &HandlerContext,
    workspace_root: &Path,
    rel_path: &str,
    line: u32,
    column: u32,
) -> Option<String> {
    use std::sync::atomic::Ordering;

    let file_path = workspace_root.join(rel_path);
    let workspace = ctx.session.get_workspace_for_file(&file_path).await?;
    let client = workspace.client().await?;

    let file_sha = leta_fs::file_sha(&file_path);
    let cache_key = format!(
        "hover:{}:{}:{}:{}",
        file_path.display(),
        line,
        column,
        file_sha
    );

    if let Some(cached) = ctx.hover_cache.get::<String>(&cache_key) {
        ctx.cache_stats.hover_hits.fetch_add(1, Ordering::Relaxed);
        return if cached.is_empty() {
            None
        } else {
            Some(cached)
        };
    }
    ctx.cache_stats.hover_misses.fetch_add(1, Ordering::Relaxed);

    workspace.ensure_document_open(&file_path).await.ok()?;
    let uri = leta_fs::path_to_uri(&file_path);

    let response: Option<leta_lsp::lsp_types::Hover> = client
        .send_request(
            "textDocument/hover",
            leta_lsp::lsp_types::HoverParams {
                text_document_position_params: leta_lsp::lsp_types::TextDocumentPositionParams {
                    text_document: TextDocumentIdentifier {
                        uri: uri.parse().unwrap(),
                    },
                    position: leta_lsp::lsp_types::Position {
                        line: line - 1,
                        character: column,
                    },
                },
                work_done_progress_params: Default::default(),
            },
        )
        .await
        .ok()?;

    let doc = response.and_then(|h| extract_hover_content(&h.contents));
    ctx.hover_cache
        .set(&cache_key, &doc.clone().unwrap_or_default());
    doc
}

fn extract_hover_content(contents: &leta_lsp::lsp_types::HoverContents) -> Option<String> {
    use leta_lsp::lsp_types::{HoverContents, MarkedString, MarkupContent};

    match contents {
        HoverContents::Scalar(MarkedString::String(s)) => Some(s.clone()),
        HoverContents::Scalar(MarkedString::LanguageString(ls)) => Some(ls.value.clone()),
        HoverContents::Markup(MarkupContent { value, .. }) => Some(value.clone()),
        HoverContents::Array(arr) => {
            let parts: Vec<String> = arr
                .iter()
                .filter_map(|ms| match ms {
                    MarkedString::String(s) => Some(s.clone()),
                    MarkedString::LanguageString(ls) => Some(ls.value.clone()),
                })
                .collect();
            if parts.is_empty() {
                None
            } else {
                Some(parts.join("\n"))
            }
        }
    }
}

fn is_excluded(path: &str, patterns: &[String]) -> bool {
    let path_parts: Vec<&str> = Path::new(path).iter().filter_map(|s| s.to_str()).collect();
    let filename = Path::new(path)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("");

    for pattern in patterns {
        if glob_match(path, pattern) {
            return true;
        }
        if !pattern.contains('/') && !pattern.contains('*') && !pattern.contains('?') {
            if path_parts.contains(&pattern.as_str()) {
                return true;
            }
        }
        if glob_match(filename, pattern) {
            return true;
        }
    }
    false
}

fn glob_match(text: &str, pattern: &str) -> bool {
    let regex_pattern = pattern
        .replace('.', r"\.")
        .replace('*', ".*")
        .replace('?', ".");
    Regex::new(&format!("^{}$", regex_pattern))
        .map(|r| r.is_match(text))
        .unwrap_or(false)
}
