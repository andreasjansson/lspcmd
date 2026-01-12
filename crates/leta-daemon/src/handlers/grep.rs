use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use fastrace::trace;
use fastrace::Span;
use leta_fs::{get_language_id, read_file_content};
use leta_lsp::lsp_types::{DocumentSymbolParams, TextDocumentIdentifier};
use leta_servers::get_server_for_language;
use leta_types::{GrepParams, GrepResult, StreamDone, StreamMessage, SymbolInfo};
use regex::Regex;
use tokio::sync::mpsc;
use tracing::{debug, info, warn};

use super::{flatten_document_symbols, relative_path, HandlerContext};
use crate::session::WorkspaceHandle;

struct GrepFilter<'a> {
    regex: &'a Regex,
    kinds: Option<&'a HashSet<String>>,
    exclude_patterns: &'a [String],
    path_regex: Option<&'a Regex>,
}

impl GrepFilter<'_> {
    fn matches(&self, sym: &SymbolInfo) -> bool {
        if !self.regex.is_match(&sym.name) {
            return false;
        }
        if let Some(kinds) = self.kinds {
            if !kinds.contains(&sym.kind.to_lowercase()) {
                return false;
            }
        }
        if !self.exclude_patterns.is_empty() && is_excluded(&sym.path, self.exclude_patterns) {
            return false;
        }
        if let Some(path_re) = self.path_regex {
            if !path_re.is_match(&sym.path) {
                return false;
            }
        }
        true
    }

    fn path_matches(&self, rel_path: &str) -> bool {
        if let Some(path_re) = self.path_regex {
            path_re.is_match(rel_path)
        } else {
            true
        }
    }
}

pub const SKIP_DIRS: &[&str] = &[
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
pub async fn handle_grep(ctx: &HandlerContext, params: GrepParams) -> Result<GrepResult, String> {
    debug!(
        "handle_grep: pattern={} workspace={} limit={} path_pattern={:?}",
        params.pattern, params.workspace_root, params.limit, params.path_pattern
    );
    let workspace_root = PathBuf::from(&params.workspace_root);

    let flags = if params.case_sensitive { "" } else { "(?i)" };
    let pattern = format!("{}{}", flags, params.pattern);
    let regex =
        Regex::new(&pattern).map_err(|e| format!("Invalid regex '{}': {}", params.pattern, e))?;

    let path_regex = params
        .path_pattern
        .as_ref()
        .map(|p| Regex::new(p))
        .transpose()
        .map_err(|e| format!("Invalid path pattern: {}", e))?;

    let kinds_set: Option<HashSet<String>> = params
        .kinds
        .clone()
        .map(|k| k.into_iter().map(|s| s.to_lowercase()).collect());

    let config = ctx.session.config().await;
    let excluded_languages: HashSet<String> = config
        .workspaces
        .excluded_languages
        .iter()
        .cloned()
        .collect();

    let limit = if params.limit == 0 {
        usize::MAX
    } else {
        params.limit as usize
    };
    let filter = GrepFilter {
        regex: &regex,
        kinds: kinds_set.as_ref(),
        exclude_patterns: &params.exclude_patterns,
        path_regex: path_regex.as_ref(),
    };

    let files = enumerate_source_files(&workspace_root, &excluded_languages);

    let text_pattern = if should_use_prefilter(&pattern) {
        Some(pattern.as_str())
    } else {
        None
    };

    let mut filtered = collect_and_filter_symbols(
        ctx,
        &workspace_root,
        &files,
        text_pattern,
        &excluded_languages,
        &filter,
        limit,
    )
    .await?;

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

    filtered.sort_by(|a, b| (&a.path, a.line).cmp(&(&b.path, b.line)));

    let warning = if filtered.is_empty() && params.pattern.contains(r"\|") {
        Some("No results. Note: use '|' for alternation, not '\\|' (e.g., 'foo|bar' not 'foo\\|bar')".to_string())
    } else {
        None
    };

    let truncated = filtered.len() >= limit;

    Ok(GrepResult {
        symbols: filtered,
        warning,
        truncated,
        total_count: None,
    })
}

#[trace]
pub fn enumerate_source_files(
    workspace_root: &Path,
    excluded_languages: &HashSet<String>,
) -> Vec<PathBuf> {
    let skip_dirs: HashSet<&str> = SKIP_DIRS.iter().copied().collect();
    let mut files = Vec::new();

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

        if get_server_for_language(lang, None).is_some() {
            files.push(path.to_path_buf());
        }
    }

    files
}

#[trace]
fn classify_and_filter_cached(
    ctx: &HandlerContext,
    workspace_root: &Path,
    files: &[PathBuf],
    text_regex: Option<&Regex>,
    filter: &GrepFilter<'_>,
    limit: usize,
) -> (Vec<SymbolInfo>, HashMap<String, Vec<PathBuf>>, bool) {
    let mut results = Vec::new();
    let mut uncached_by_lang: HashMap<String, Vec<PathBuf>> = HashMap::new();

    for file_path in files {
        let rel_path = relative_path(file_path, workspace_root);
        if !filter.path_matches(&rel_path) {
            continue;
        }

        if let Some(symbols) = check_file_cache(ctx, workspace_root, file_path) {
            for sym in symbols {
                if filter.matches(&sym) {
                    results.push(sym);
                    if results.len() >= limit {
                        return (results, uncached_by_lang, true);
                    }
                }
            }
        } else {
            let should_fetch = match text_regex {
                Some(re) => prefilter_file(file_path, re),
                None => true,
            };

            if should_fetch {
                let lang = get_language_id(file_path);
                uncached_by_lang
                    .entry(lang.to_string())
                    .or_default()
                    .push(file_path.clone());
            }
        }
    }

    (results, uncached_by_lang, false)
}

#[trace]
async fn fetch_and_filter_symbols(
    ctx: &HandlerContext,
    workspace_root: &Path,
    lang: &str,
    files: &[PathBuf],
    filter: &GrepFilter<'_>,
    results: &mut Vec<SymbolInfo>,
    limit: usize,
) -> Result<bool, String> {
    let workspace = ctx
        .session
        .get_or_create_workspace_for_language(lang, workspace_root)
        .await?;

    for file_path in files {
        match get_file_symbols_no_wait(ctx, &workspace, workspace_root, file_path).await {
            Ok(symbols) => {
                for sym in symbols {
                    if filter.matches(&sym) {
                        results.push(sym);
                        if results.len() >= limit {
                            return Ok(true);
                        }
                    }
                }
            }
            Err(e) => {
                warn!("Failed to get symbols for {}: {}", file_path.display(), e);
            }
        }
    }
    Ok(false)
}

async fn collect_and_filter_symbols(
    ctx: &HandlerContext,
    workspace_root: &Path,
    files: &[PathBuf],
    text_pattern: Option<&str>,
    _excluded_languages: &HashSet<String>,
    filter: &GrepFilter<'_>,
    limit: usize,
) -> Result<Vec<SymbolInfo>, String> {
    let span = Span::enter_with_local_parent("collect_and_filter_symbols");
    let text_regex = text_pattern.and_then(pattern_to_text_regex);

    let (mut results, uncached_by_lang, limit_reached) = {
        let _guard = span.set_local_parent();
        classify_and_filter_cached(
            ctx,
            workspace_root,
            files,
            text_regex.as_ref(),
            filter,
            limit,
        )
    };

    if limit_reached {
        return Ok(results);
    }

    for (lang, uncached_files) in uncached_by_lang {
        if results.len() >= limit {
            break;
        }

        match fetch_and_filter_symbols(
            ctx,
            workspace_root,
            &lang,
            &uncached_files,
            filter,
            &mut results,
            limit,
        )
        .await
        {
            Ok(true) => break,
            Ok(false) => {}
            Err(e) => {
                warn!("Failed to fetch symbols for language {}: {}", lang, e);
            }
        }
    }

    Ok(results)
}

enum FileStatus {
    Cached(Vec<SymbolInfo>),
    NeedsFetch,
    Skipped,
}

#[trace]
fn check_file_cache(
    ctx: &HandlerContext,
    workspace_root: &Path,
    file_path: &Path,
) -> Option<Vec<SymbolInfo>> {
    get_cached_symbols(ctx, workspace_root, file_path)
}

#[trace]
fn prefilter_file(file_path: &Path, text_regex: &Regex) -> bool {
    match read_file_content(file_path) {
        Ok(content) => text_regex.is_match(&content),
        Err(e) => {
            warn!(
                "Failed to read file for prefilter {}: {}",
                file_path.display(),
                e
            );
            false
        }
    }
}

fn classify_file(
    ctx: &HandlerContext,
    workspace_root: &Path,
    file_path: &Path,
    text_regex: Option<&Regex>,
    excluded_languages: &HashSet<String>,
) -> FileStatus {
    let lang = get_language_id(file_path);
    if lang == "plaintext" || excluded_languages.contains(lang) {
        return FileStatus::Skipped;
    }
    if get_server_for_language(lang, None).is_none() {
        return FileStatus::Skipped;
    }

    if let Some(symbols) = check_file_cache(ctx, workspace_root, file_path) {
        return FileStatus::Cached(symbols);
    }

    match text_regex {
        Some(re) => {
            if prefilter_file(file_path, re) {
                FileStatus::NeedsFetch
            } else {
                FileStatus::Skipped
            }
        }
        None => FileStatus::NeedsFetch,
    }
}

#[trace]
fn classify_all_files(
    ctx: &HandlerContext,
    workspace_root: &Path,
    files: &[PathBuf],
    text_regex: Option<&Regex>,
    excluded_languages: &HashSet<String>,
) -> (Vec<SymbolInfo>, HashMap<String, Vec<PathBuf>>) {
    let mut cached_symbols = Vec::new();
    let mut uncached_by_lang: HashMap<String, Vec<PathBuf>> = HashMap::new();
    let mut skipped = 0u32;
    let mut cached_count = 0u32;
    let mut needs_fetch = 0u32;

    for file_path in files {
        match classify_file(
            ctx,
            workspace_root,
            file_path,
            text_regex,
            excluded_languages,
        ) {
            FileStatus::Cached(symbols) => {
                cached_count += 1;
                cached_symbols.extend(symbols);
            }
            FileStatus::NeedsFetch => {
                needs_fetch += 1;
                let lang = get_language_id(file_path);
                uncached_by_lang
                    .entry(lang.to_string())
                    .or_default()
                    .push(file_path.to_path_buf());
            }
            FileStatus::Skipped => {
                skipped += 1;
            }
        }
    }

    info!(
        "classify_all_files: {} files -> {} cached, {} need_fetch, {} skipped",
        files.len(),
        cached_count,
        needs_fetch,
        skipped
    );

    (cached_symbols, uncached_by_lang)
}

#[trace]
async fn fetch_symbols_for_language(
    ctx: &HandlerContext,
    workspace_root: &Path,
    lang: &str,
    files: &[PathBuf],
) -> Result<Vec<SymbolInfo>, String> {
    let workspace = ctx
        .session
        .get_or_create_workspace_for_language(lang, workspace_root)
        .await?;

    let mut symbols = Vec::new();
    for file_path in files {
        match get_file_symbols_no_wait(ctx, &workspace, workspace_root, file_path).await {
            Ok(file_symbols) => symbols.extend(file_symbols),
            Err(e) => {
                warn!("Failed to get symbols for {}: {}", file_path.display(), e);
            }
        }
    }
    Ok(symbols)
}

pub async fn collect_symbols_smart(
    ctx: &HandlerContext,
    workspace_root: &Path,
    files: &[PathBuf],
    text_pattern: Option<&str>,
    excluded_languages: &HashSet<String>,
) -> Result<Vec<SymbolInfo>, String> {
    let span = Span::enter_with_local_parent("collect_symbols_smart");
    let text_regex = text_pattern.and_then(pattern_to_text_regex);

    let (mut all_symbols, uncached_by_lang) = {
        let _guard = span.set_local_parent();
        classify_all_files(
            ctx,
            workspace_root,
            files,
            text_regex.as_ref(),
            excluded_languages,
        )
    };

    let uncached_count: usize = uncached_by_lang.values().map(|v| v.len()).sum();
    if uncached_count > 0 {
        debug!(
            "Fetching symbols for {} uncached files (pattern: {:?})",
            uncached_count, text_pattern
        );
    }

    for (lang, uncached_files) in uncached_by_lang {
        match fetch_symbols_for_language(ctx, workspace_root, &lang, &uncached_files).await {
            Ok(symbols) => all_symbols.extend(symbols),
            Err(e) => {
                warn!("Failed to fetch symbols for language {}: {}", lang, e);
            }
        }
    }

    Ok(all_symbols)
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

    let files = enumerate_source_files(workspace_root, &excluded_languages);
    let pattern = if text_pattern
        .map(|p| should_use_prefilter(p))
        .unwrap_or(false)
    {
        text_pattern
    } else {
        None
    };

    collect_symbols_smart(ctx, workspace_root, &files, pattern, &excluded_languages).await
}

#[trace]
pub fn get_cached_symbols(
    ctx: &HandlerContext,
    workspace_root: &Path,
    file_path: &Path,
) -> Option<Vec<SymbolInfo>> {
    use std::sync::atomic::Ordering;

    let file_mtime = leta_fs::file_mtime(file_path);
    let cache_key = format!(
        "{}:{}:{}",
        file_path.display(),
        workspace_root.display(),
        file_mtime
    );

    if let Some(cached) = ctx.symbol_cache.get::<Vec<SymbolInfo>>(&cache_key) {
        ctx.cache_stats.symbol_hits.fetch_add(1, Ordering::Relaxed);
        Some(cached)
    } else {
        None
    }
}

#[trace]
pub async fn get_file_symbols(
    ctx: &HandlerContext,
    workspace: &WorkspaceHandle<'_>,
    workspace_root: &Path,
    file_path: &Path,
) -> Result<Vec<SymbolInfo>, String> {
    workspace.wait_for_ready(30).await;
    get_file_symbols_no_wait(ctx, workspace, workspace_root, file_path).await
}

#[trace]
pub async fn get_file_symbols_no_wait(
    ctx: &HandlerContext,
    workspace: &WorkspaceHandle<'_>,
    workspace_root: &Path,
    file_path: &Path,
) -> Result<Vec<SymbolInfo>, String> {
    use std::sync::atomic::Ordering;

    let file_mtime = leta_fs::file_mtime(file_path);
    let cache_key = format!(
        "{}:{}:{}",
        file_path.display(),
        workspace_root.display(),
        file_mtime
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

    let file_mtime = leta_fs::file_mtime(&file_path);
    let cache_key = format!(
        "hover:{}:{}:{}:{}",
        file_path.display(),
        line,
        column,
        file_mtime
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
    for pattern in patterns {
        if let Ok(re) = Regex::new(pattern) {
            if re.is_match(path) {
                return true;
            }
        }
    }
    false
}

#[trace]
pub async fn handle_grep_streaming(
    ctx: &HandlerContext,
    params: GrepParams,
    tx: mpsc::Sender<StreamMessage>,
) {
    let result = handle_grep_streaming_inner(ctx, params, &tx).await;

    match result {
        Ok((warning, truncated, count)) => {
            let _ = tx
                .send(StreamMessage::Done(StreamDone {
                    warning,
                    truncated,
                    total_count: count,
                    profiling: None,
                }))
                .await;
        }
        Err(e) => {
            let _ = tx.send(StreamMessage::Error { message: e }).await;
        }
    }
}

#[trace]
async fn handle_grep_streaming_inner(
    ctx: &HandlerContext,
    params: GrepParams,
    tx: &mpsc::Sender<StreamMessage>,
) -> Result<(Option<String>, bool, u32), String> {
    debug!(
        "handle_grep_streaming: pattern={} workspace={} limit={}",
        params.pattern, params.workspace_root, params.limit
    );
    let workspace_root = PathBuf::from(&params.workspace_root);

    let flags = if params.case_sensitive { "" } else { "(?i)" };
    let pattern = format!("{}{}", flags, params.pattern);
    let regex =
        Regex::new(&pattern).map_err(|e| format!("Invalid regex '{}': {}", params.pattern, e))?;

    let path_regex = params
        .path_pattern
        .as_ref()
        .map(|p| Regex::new(p))
        .transpose()
        .map_err(|e| format!("Invalid path pattern: {}", e))?;

    let kinds_set: Option<HashSet<String>> = params
        .kinds
        .clone()
        .map(|k| k.into_iter().map(|s| s.to_lowercase()).collect());

    let config = ctx.session.config().await;
    let excluded_languages: HashSet<String> = config
        .workspaces
        .excluded_languages
        .iter()
        .cloned()
        .collect();

    let limit = if params.limit == 0 {
        usize::MAX
    } else {
        params.limit as usize
    };

    let filter = GrepFilter {
        regex: &regex,
        kinds: kinds_set.as_ref(),
        exclude_patterns: &params.exclude_patterns,
        path_regex: path_regex.as_ref(),
    };

    let files = enumerate_source_files(&workspace_root, &excluded_languages);

    let text_pattern = if should_use_prefilter(&pattern) {
        Some(pattern.as_str())
    } else {
        None
    };

    let (count, truncated) = stream_and_filter_symbols(
        ctx,
        &workspace_root,
        &files,
        text_pattern,
        &excluded_languages,
        &filter,
        limit,
        params.include_docs,
        tx,
    )
    .await?;

    let warning = if count == 0 && params.pattern.contains(r"\|") {
        Some("No results. Note: use '|' for alternation, not '\\|' (e.g., 'foo|bar' not 'foo\\|bar')".to_string())
    } else {
        None
    };

    Ok((warning, truncated, count))
}

#[trace]
async fn stream_and_filter_symbols(
    ctx: &HandlerContext,
    workspace_root: &Path,
    files: &[PathBuf],
    text_pattern: Option<&str>,
    excluded_languages: &HashSet<String>,
    filter: &GrepFilter<'_>,
    limit: usize,
    include_docs: bool,
    tx: &mpsc::Sender<StreamMessage>,
) -> Result<(u32, bool), String> {
    let text_regex = text_pattern.and_then(pattern_to_text_regex);

    let mut count = 0u32;
    let mut uncached_by_lang: HashMap<String, Vec<PathBuf>> = HashMap::new();
    let mut cached_matches: Vec<SymbolInfo> = Vec::new();

    for file_path in files {
        let lang = get_language_id(file_path);
        if lang == "plaintext" || excluded_languages.contains(lang) {
            continue;
        }
        if get_server_for_language(lang, None).is_none() {
            continue;
        }

        let rel_path = relative_path(file_path, workspace_root);
        if !filter.path_matches(&rel_path) {
            continue;
        }

        if let Some(symbols) = check_file_cache(ctx, workspace_root, file_path) {
            for sym in symbols {
                if filter.matches(&sym) {
                    cached_matches.push(sym);
                }
            }
        } else {
            let should_fetch = match &text_regex {
                Some(re) => prefilter_file(file_path, re),
                None => true,
            };

            if should_fetch {
                uncached_by_lang
                    .entry(lang.to_string())
                    .or_default()
                    .push(file_path.clone());
            }
        }
    }

    for mut sym in cached_matches {
        if include_docs {
            if let Some(doc) =
                get_symbol_documentation(ctx, workspace_root, &sym.path, sym.line, sym.column).await
            {
                sym.documentation = Some(doc);
            }
        }
        if tx.send(StreamMessage::Symbol(sym)).await.is_err() {
            return Ok((count, false));
        }
        count += 1;
        if count as usize >= limit {
            return Ok((count, true));
        }
    }

    for (lang, uncached_files) in uncached_by_lang {
        if count as usize >= limit {
            break;
        }

        let workspace = match ctx
            .session
            .get_or_create_workspace_for_language(&lang, workspace_root)
            .await
        {
            Ok(ws) => ws,
            Err(e) => {
                warn!("Failed to get workspace for {}: {}", lang, e);
                continue;
            }
        };

        for file_path in uncached_files {
            match get_file_symbols_no_wait(ctx, &workspace, workspace_root, &file_path).await {
                Ok(symbols) => {
                    for mut sym in symbols {
                        if filter.matches(&sym) {
                            if include_docs {
                                if let Some(doc) = get_symbol_documentation(
                                    ctx,
                                    workspace_root,
                                    &sym.path,
                                    sym.line,
                                    sym.column,
                                )
                                .await
                                {
                                    sym.documentation = Some(doc);
                                }
                            }
                            if tx.send(StreamMessage::Symbol(sym)).await.is_err() {
                                return Ok((count, false));
                            }
                            count += 1;
                            if count as usize >= limit {
                                return Ok((count, true));
                            }
                        }
                    }
                }
                Err(e) => {
                    warn!("Failed to get symbols for {}: {}", file_path.display(), e);
                }
            }
        }
    }

    Ok((count, false))
}
