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
use tracing::{debug, warn};

use super::{flatten_document_symbols, relative_path, HandlerContext};
use crate::session::WorkspaceHandle;

struct GrepFilter<'a> {
    regex: &'a Regex,
    kinds: Option<&'a HashSet<String>>,
    exclude_regexes: &'a [Regex],
    path_regex: Option<&'a Regex>,
}

impl GrepFilter<'_> {
    #[trace]
    fn matches(&self, sym: &SymbolInfo) -> bool {
        if !self.regex.is_match(&sym.name) {
            return false;
        }
        if let Some(kinds) = self.kinds {
            if !kinds.contains(&sym.kind.to_lowercase()) {
                return false;
            }
        }
        for exclude_re in self.exclude_regexes {
            if exclude_re.is_match(&sym.path) {
                return false;
            }
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

    if core.is_empty() || core == "." || core == ".*" {
        return false;
    }

    let start_anchor = pattern.trim_start_matches("(?i)").starts_with('^');
    let end_anchor = pattern.ends_with('$');

    if start_anchor && end_anchor {
        return false;
    }

    true
}

fn pattern_to_text_regex(pattern: &str) -> Option<Regex> {
    let core = pattern
        .trim_start_matches("(?i)")
        .trim_start_matches('^')
        .trim_end_matches('$');

    if core.is_empty() {
        return None;
    }

    let has_special_chars = core.chars().any(|c| {
        matches!(
            c,
            '.' | '*' | '+' | '?' | '[' | ']' | '(' | ')' | '{' | '}' | '|' | '\\' | '^' | '$'
        )
    });

    let text_pattern = if has_special_chars {
        let mut result = String::new();
        let mut chars = core.chars().peekable();
        while let Some(c) = chars.next() {
            match c {
                '\\' => {
                    if let Some(&next) = chars.peek() {
                        match next {
                            'd' | 'w' | 's' | 'D' | 'W' | 'S' => {
                                return None;
                            }
                            _ => {
                                chars.next();
                                result.push(next);
                            }
                        }
                    }
                }
                '.' => result.push('.'),
                '*' | '+' | '?' => {}
                '[' | ']' | '(' | ')' | '{' | '}' | '|' | '^' | '$' => {
                    return None;
                }
                _ => result.push(c),
            }
        }
        result
    } else {
        core.to_string()
    };

    if text_pattern.len() < 2 {
        return None;
    }

    let case_insensitive = pattern.starts_with("(?i)");
    let regex_pattern = if case_insensitive {
        format!("(?i){}", regex::escape(&text_pattern))
    } else {
        regex::escape(&text_pattern)
    };

    Regex::new(&regex_pattern).ok()
}

#[trace]
pub fn enumerate_source_files(
    workspace_root: &Path,
    excluded_languages: &HashSet<String>,
) -> Vec<PathBuf> {
    let skip_dirs: HashSet<&str> = SKIP_DIRS.iter().copied().collect();
    let mut files = Vec::new();

    for entry in walkdir::WalkDir::new(workspace_root)
        .sort_by_file_name()
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
    let func_start = std::time::Instant::now();
    let mut results = Vec::new();
    let mut uncached_by_lang: HashMap<String, Vec<PathBuf>> = HashMap::new();

    let mut total_symbols = 0u64;
    let mut cache_hits = 0u64;
    let mut cache_misses = 0u64;
    let mut match_time = std::time::Duration::ZERO;
    let mut cache_time = std::time::Duration::ZERO;
    let mut rel_path_time = std::time::Duration::ZERO;
    let mut prefilter_time = std::time::Duration::ZERO;
    let mut sym_iter_time = std::time::Duration::ZERO;

    for file_path in files {
        let start = std::time::Instant::now();
        let rel_path = relative_path(file_path, workspace_root);
        rel_path_time += start.elapsed();

        if !filter.path_matches(&rel_path) {
            continue;
        }

        let start = std::time::Instant::now();
        let cached = check_file_cache(ctx, workspace_root, file_path);
        cache_time += start.elapsed();

        if let Some(symbols) = cached {
            cache_hits += 1;
            let iter_start = std::time::Instant::now();
            for sym in symbols {
                total_symbols += 1;
                let start = std::time::Instant::now();
                let matched = filter.matches(&sym);
                match_time += start.elapsed();
                if matched {
                    results.push(sym);
                    if results.len() >= limit {
                        sym_iter_time += iter_start.elapsed();
                        tracing::info!(
                            "classify: files={} hits={} misses={} syms={} rel_path={:?} cache={:?} prefilter={:?} sym_iter={:?} match={:?} total={:?}",
                            files.len(), cache_hits, cache_misses, total_symbols, rel_path_time, cache_time, prefilter_time, sym_iter_time, match_time, func_start.elapsed()
                        );
                        return (results, uncached_by_lang, true);
                    }
                }
            }
            sym_iter_time += iter_start.elapsed();
        } else {
            cache_misses += 1;
            let start = std::time::Instant::now();
            let should_fetch = match text_regex {
                Some(re) => prefilter_file(file_path, re),
                None => true,
            };
            prefilter_time += start.elapsed();

            if should_fetch {
                let lang = get_language_id(file_path);
                uncached_by_lang
                    .entry(lang.to_string())
                    .or_default()
                    .push(file_path.clone());
            }
        }
    }

    tracing::info!(
        "classify: files={} hits={} misses={} syms={} rel_path={:?} cache={:?} prefilter={:?} sym_iter={:?} match={:?} total={:?}",
        files.len(), cache_hits, cache_misses, total_symbols, rel_path_time, cache_time, prefilter_time, sym_iter_time, match_time, func_start.elapsed()
    );

    (results, uncached_by_lang, false)
}

fn process_file_in_filter_loop(
    ctx: &HandlerContext,
    workspace_root: &Path,
    file_path: &Path,
    text_regex: Option<&Regex>,
    filter: &GrepFilter<'_>,
    limit: usize,
    results: &mut Vec<SymbolInfo>,
    uncached_by_lang: &mut HashMap<String, Vec<PathBuf>>,
) {
    let rel_path = relative_path(file_path, workspace_root);
    if !filter.path_matches(&rel_path) {
        return;
    }

    if let Some(symbols) = check_file_cache(ctx, workspace_root, file_path) {
        for sym in symbols {
            if filter.matches(&sym) {
                results.push(sym);
                if results.len() >= limit {
                    return;
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
                .push(file_path.to_path_buf());
        }
    }
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

fn check_file_cache(
    ctx: &HandlerContext,
    workspace_root: &Path,
    file_path: &Path,
) -> Option<Vec<SymbolInfo>> {
    get_cached_symbols(ctx, workspace_root, file_path)
}

fn prefilter_file(file_path: &Path, text_regex: &Regex) -> bool {
    if let Some(content) = read_file_content(file_path) {
        text_regex.is_match(&content)
    } else {
        false
    }
}

#[trace]
async fn fetch_and_filter_symbols(
    ctx: &HandlerContext,
    workspace_root: &Path,
    lang: &str,
    uncached_files: &[PathBuf],
    filter: &GrepFilter<'_>,
    results: &mut Vec<SymbolInfo>,
    limit: usize,
) -> Result<bool, String> {
    let workspace = ctx
        .session
        .get_or_create_workspace_for_language(lang, workspace_root)
        .await?;

    for file_path in uncached_files {
        if results.len() >= limit {
            return Ok(true);
        }

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

async fn get_file_symbols_no_wait(
    ctx: &HandlerContext,
    workspace: &WorkspaceHandle,
    workspace_root: &Path,
    file_path: &Path,
) -> Result<Vec<SymbolInfo>, String> {
    let uri = leta_fs::path_to_uri(file_path);

    let params = DocumentSymbolParams {
        text_document: TextDocumentIdentifier { uri: uri.clone() },
        work_done_progress_params: Default::default(),
        partial_result_params: Default::default(),
    };

    let response = workspace
        .client
        .document_symbols(params)
        .await
        .map_err(|e| format!("document_symbols failed: {}", e))?;

    let rel_path = relative_path(file_path, workspace_root);

    let symbols = flatten_document_symbols(response, &rel_path);

    let cache_key = format!(
        "{}:{}:{}",
        file_path.display(),
        workspace_root.display(),
        leta_fs::file_mtime(file_path)
    );
    ctx.symbol_cache.put(&cache_key, &symbols);

    Ok(symbols)
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
pub async fn handle_grep(ctx: &HandlerContext, params: GrepParams) -> Result<GrepResult, String> {
    debug!(
        "handle_grep: pattern={} workspace={} limit={}",
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

    let exclude_regexes: Vec<Regex> = params
        .exclude_patterns
        .iter()
        .filter_map(|p| Regex::new(p).ok())
        .collect();

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
        exclude_regexes: &exclude_regexes,
        path_regex: path_regex.as_ref(),
    };

    let files = enumerate_source_files(&workspace_root, &excluded_languages);

    let text_pattern = if should_use_prefilter(&pattern) {
        Some(pattern.as_str())
    } else {
        None
    };

    let mut symbols = collect_and_filter_symbols(
        ctx,
        &workspace_root,
        &files,
        text_pattern,
        &excluded_languages,
        &filter,
        limit,
    )
    .await?;

    symbols.sort_by(|a, b| (&a.path, a.line).cmp(&(&b.path, b.line)));

    let truncated = symbols.len() >= limit;

    if params.include_docs {
        for sym in &mut symbols {
            if let Some(doc) =
                get_symbol_documentation(ctx, &workspace_root, &sym.path, sym.line, sym.column)
                    .await
            {
                sym.documentation = Some(doc);
            }
        }
    }

    let warning = if symbols.is_empty() && params.pattern.contains(r"\|") {
        Some("No results. Note: use '|' for alternation, not '\\|' (e.g., 'foo|bar' not 'foo\\|bar')".to_string())
    } else {
        None
    };

    Ok(GrepResult {
        symbols,
        truncated,
        warning,
    })
}

async fn get_symbol_documentation(
    ctx: &HandlerContext,
    workspace_root: &Path,
    rel_path: &str,
    line: u32,
    column: u32,
) -> Option<String> {
    let file_path = workspace_root.join(rel_path);
    let lang = get_language_id(&file_path);

    let workspace = ctx
        .session
        .get_or_create_workspace_for_language(lang, workspace_root)
        .await
        .ok()?;

    let uri = leta_fs::path_to_uri(&file_path);

    let params = leta_lsp::lsp_types::HoverParams {
        text_document_position_params: leta_lsp::lsp_types::TextDocumentPositionParams {
            text_document: TextDocumentIdentifier { uri },
            position: leta_lsp::lsp_types::Position {
                line: line.saturating_sub(1),
                character: column.saturating_sub(1),
            },
        },
        work_done_progress_params: Default::default(),
    };

    let hover = workspace.client.hover(params).await.ok()??;

    match hover.contents {
        leta_lsp::lsp_types::HoverContents::Markup(markup) => {
            let text = markup.value.trim();
            if text.is_empty() {
                None
            } else {
                Some(text.to_string())
            }
        }
        leta_lsp::lsp_types::HoverContents::Scalar(scalar) => match scalar {
            leta_lsp::lsp_types::MarkedString::String(s) => {
                let s = s.trim();
                if s.is_empty() {
                    None
                } else {
                    Some(s.to_string())
                }
            }
            leta_lsp::lsp_types::MarkedString::LanguageString(ls) => {
                let s = ls.value.trim();
                if s.is_empty() {
                    None
                } else {
                    Some(s.to_string())
                }
            }
        },
        leta_lsp::lsp_types::HoverContents::Array(arr) => {
            let texts: Vec<String> = arr
                .iter()
                .filter_map(|ms| match ms {
                    leta_lsp::lsp_types::MarkedString::String(s) => {
                        let s = s.trim();
                        if s.is_empty() {
                            None
                        } else {
                            Some(s.to_string())
                        }
                    }
                    leta_lsp::lsp_types::MarkedString::LanguageString(ls) => {
                        let s = ls.value.trim();
                        if s.is_empty() {
                            None
                        } else {
                            Some(s.to_string())
                        }
                    }
                })
                .collect();
            if texts.is_empty() {
                None
            } else {
                Some(texts.join("\n\n"))
            }
        }
    }
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

    let exclude_regexes: Vec<Regex> = params
        .exclude_patterns
        .iter()
        .filter_map(|p| Regex::new(p).ok())
        .collect();

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
        exclude_regexes: &exclude_regexes,
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

    for file_path in files {
        if count as usize >= limit {
            return Ok((count, true));
        }

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
            let mut matching: Vec<_> = symbols.into_iter().filter(|s| filter.matches(s)).collect();
            matching.sort_by_key(|s| s.line);

            for mut sym in matching {
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
            continue;
        }

        let should_fetch = match &text_regex {
            Some(re) => prefilter_file(file_path, re),
            None => true,
        };

        if !should_fetch {
            continue;
        }

        let workspace = match ctx
            .session
            .get_or_create_workspace_for_language(lang, workspace_root)
            .await
        {
            Ok(ws) => ws,
            Err(e) => {
                warn!("Failed to get workspace for {}: {}", lang, e);
                continue;
            }
        };

        match get_file_symbols_no_wait(ctx, &workspace, workspace_root, file_path).await {
            Ok(symbols) => {
                let mut matching: Vec<_> =
                    symbols.into_iter().filter(|s| filter.matches(s)).collect();
                matching.sort_by_key(|s| s.line);

                for mut sym in matching {
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
            Err(e) => {
                warn!("Failed to get symbols for {}: {}", file_path.display(), e);
            }
        }
    }

    Ok((count, false))
}
