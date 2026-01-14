use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use fastrace::future::FutureExt as _;
use fastrace::trace;
use fastrace::Span;
use leta_fs::{get_language_id, read_file_content};
use leta_lsp::lsp_types::{DocumentSymbolParams, TextDocumentIdentifier};
use leta_servers::get_server_for_language;
use leta_types::{GrepParams, GrepResult, StreamDone, StreamMessage, SymbolInfo};
use rayon::prelude::*;
use regex::Regex;
use tokio::sync::mpsc;
use tracing::{debug, info, warn};

use super::{flatten_document_symbols, relative_path, HandlerContext};
use crate::session::WorkspaceHandle;

struct GrepFilter<'a> {
    regex: &'a Regex,
    kinds: Option<&'a HashSet<String>>,
    exclude_regexes: &'a [Regex],
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
    tracing::info!(
        "handle_grep START: pattern={} workspace={} limit={} path_pattern={:?}",
        params.pattern,
        params.workspace_root,
        params.limit,
        params.path_pattern
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

    let exclude_regexes: Vec<Regex> = params
        .exclude_patterns
        .iter()
        .filter_map(|p| Regex::new(p).ok())
        .collect();

    let filter = GrepFilter {
        regex: &regex,
        kinds: kinds_set.as_ref(),
        exclude_regexes: &exclude_regexes,
        path_regex: path_regex.as_ref(),
    };

    tracing::info!("handle_grep: starting enumerate_source_files");
    let files = enumerate_source_files(&workspace_root, &excluded_languages);
    tracing::info!(
        "handle_grep: enumerate_source_files done, found {} files",
        files.len()
    );

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
    let mut entries_seen = 0u64;
    let mut files_checked = 0u64;

    for entry in jwalk::WalkDir::new(workspace_root)
        .sort(true)
        .process_read_dir(move |_depth, _path, _state, children| {
            children.retain(|entry| {
                entry
                    .as_ref()
                    .map(|e| {
                        let name = e.file_name().to_string_lossy();
                        !name.starts_with('.')
                            && !skip_dirs.contains(name.as_ref())
                            && !name.ends_with(".egg-info")
                    })
                    .unwrap_or(false)
            });
        })
    {
        entries_seen += 1;
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };

        if !entry.file_type().is_file() {
            continue;
        }

        files_checked += 1;
        let path = entry.path();
        let lang = get_language_id(&path);

        if lang == "plaintext" || excluded_languages.contains(lang) {
            continue;
        }

        if get_server_for_language(lang, None).is_some() {
            files.push(path);
        }
    }

    fastrace::local::LocalSpan::add_properties(|| {
        [
            ("entries_seen", entries_seen.to_string()),
            ("files_checked", files_checked.to_string()),
            ("source_files", files.len().to_string()),
        ]
    });

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
    let mut uncached_files: Vec<&PathBuf> = Vec::new();

    // Phase 1: Check cache and collect results from cached files
    filter_cached_symbols(
        ctx,
        workspace_root,
        files,
        filter,
        limit,
        &mut results,
        &mut uncached_files,
    );

    if results.len() >= limit {
        return (results, HashMap::new(), true);
    }

    // Phase 2: Prefilter uncached files (read file contents to check for pattern)
    let files_to_fetch = prefilter_uncached_files(&uncached_files, text_regex);

    // Phase 3: Group by language
    let uncached_by_lang = group_files_by_language(&files_to_fetch);

    (results, uncached_by_lang, false)
}

fn build_cache_key(workspace_root: &Path, file_path: &Path) -> String {
    let file_mtime = leta_fs::file_mtime(file_path);
    format!(
        "{}:{}:{}",
        file_path.display(),
        workspace_root.display(),
        file_mtime
    )
}

#[trace]
fn filter_cached_symbols<'a>(
    ctx: &HandlerContext,
    workspace_root: &Path,
    files: &'a [PathBuf],
    filter: &GrepFilter<'_>,
    limit: usize,
    results: &mut Vec<SymbolInfo>,
    uncached_files: &mut Vec<&'a PathBuf>,
) {
    use std::sync::atomic::Ordering;

    let key_build_start = std::time::Instant::now();
    let filtered_files: Vec<_> = files
        .iter()
        .filter(|file_path| {
            let rel_path = relative_path(file_path, workspace_root);
            filter.path_matches(&rel_path)
        })
        .collect();

    let cache_keys: Vec<String> = filtered_files
        .iter()
        .map(|file_path| build_cache_key(workspace_root, file_path))
        .collect();
    let key_build_time = key_build_start.elapsed();

    let cache_start = std::time::Instant::now();
    let cache_key_refs: Vec<&str> = cache_keys.iter().map(|s| s.as_str()).collect();
    let cached_values: Vec<Option<Vec<SymbolInfo>>> = ctx.symbol_cache.get_many(&cache_key_refs);
    let cache_check_time = cache_start.elapsed();

    let mut cache_hits = 0u64;
    let mut symbols_checked = 0u64;
    let match_start = std::time::Instant::now();

    for (file_path, cached) in filtered_files.into_iter().zip(cached_values.into_iter()) {
        if let Some(symbols) = cached {
            cache_hits += 1;
            ctx.cache_stats.symbol_hits.fetch_add(1, Ordering::Relaxed);
            for sym in symbols {
                symbols_checked += 1;
                if filter.matches(&sym) {
                    results.push(sym);
                    if results.len() >= limit {
                        let match_time = match_start.elapsed();
                        fastrace::local::LocalSpan::add_properties(|| {
                            [
                                (
                                    "key_build_ms",
                                    format!("{:.1}", key_build_time.as_secs_f64() * 1000.0),
                                ),
                                (
                                    "cache_check_ms",
                                    format!("{:.1}", cache_check_time.as_secs_f64() * 1000.0),
                                ),
                                ("cache_hits", cache_hits.to_string()),
                                ("symbols_checked", symbols_checked.to_string()),
                                (
                                    "match_ms",
                                    format!("{:.1}", match_time.as_secs_f64() * 1000.0),
                                ),
                            ]
                        });
                        return;
                    }
                }
            }
        } else {
            uncached_files.push(file_path);
        }
    }
    let match_time = match_start.elapsed();

    fastrace::local::LocalSpan::add_properties(|| {
        [
            (
                "key_build_ms",
                format!("{:.1}", key_build_time.as_secs_f64() * 1000.0),
            ),
            (
                "cache_check_ms",
                format!("{:.1}", cache_check_time.as_secs_f64() * 1000.0),
            ),
            ("cache_hits", cache_hits.to_string()),
            ("symbols_checked", symbols_checked.to_string()),
            (
                "match_ms",
                format!("{:.1}", match_time.as_secs_f64() * 1000.0),
            ),
        ]
    });
}

#[trace]
fn prefilter_uncached_files<'a>(
    uncached_files: &[&'a PathBuf],
    text_regex: Option<&Regex>,
) -> Vec<&'a PathBuf> {
    let start = std::time::Instant::now();
    let result = match text_regex {
        Some(re) => uncached_files
            .par_iter()
            .filter(|path| prefilter_file(path, re))
            .copied()
            .collect(),
        None => uncached_files.to_vec(),
    };
    let elapsed = start.elapsed();

    fastrace::local::LocalSpan::add_properties(|| {
        [
            ("files_checked", uncached_files.len().to_string()),
            ("files_matched", result.len().to_string()),
            (
                "prefilter_ms",
                format!("{:.1}", elapsed.as_secs_f64() * 1000.0),
            ),
        ]
    });

    result
}

#[trace]
fn group_files_by_language(files: &[&PathBuf]) -> HashMap<String, Vec<PathBuf>> {
    let mut by_lang: HashMap<String, Vec<PathBuf>> = HashMap::new();
    for file_path in files {
        let lang = get_language_id(file_path);
        by_lang
            .entry(lang.to_string())
            .or_default()
            .push((*file_path).clone());
    }
    by_lang
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

        let fetch_span = Span::enter_with_parent("fetch_uncached", &span);
        match fetch_and_filter_symbols(
            ctx,
            workspace_root,
            &lang,
            &uncached_files,
            filter,
            &mut results,
            limit,
        )
        .in_span(fetch_span)
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

#[trace]
fn classify_all_files(
    ctx: &HandlerContext,
    workspace_root: &Path,
    files: &[PathBuf],
    text_regex: Option<&Regex>,
    excluded_languages: &HashSet<String>,
) -> (Vec<SymbolInfo>, HashMap<String, Vec<PathBuf>>) {
    use rayon::prelude::*;

    let start = std::time::Instant::now();
    let mut cached_symbols = Vec::new();
    let mut uncached_by_lang: HashMap<String, Vec<PathBuf>> = HashMap::new();

    // Phase 1: Filter by language support (fast, no I/O)
    let supported_files: Vec<(&PathBuf, &'static str)> = files
        .iter()
        .filter_map(|file_path| {
            let lang = get_language_id(file_path);
            if lang == "plaintext" || excluded_languages.contains(lang) {
                return None;
            }
            if get_server_for_language(lang, None).is_none() {
                return None;
            }
            Some((file_path, lang))
        })
        .collect();
    let skipped_lang = files.len() - supported_files.len();

    // Phase 2: Check cache (requires ctx, must be serial but uses batch reads)
    let cache_start = std::time::Instant::now();
    let cache_keys: Vec<String> = supported_files
        .iter()
        .map(|(file_path, _)| build_cache_key(workspace_root, file_path))
        .collect();
    let cache_key_refs: Vec<&str> = cache_keys.iter().map(|s| s.as_str()).collect();
    let cached_values: Vec<Option<Vec<SymbolInfo>>> = ctx.symbol_cache.get_many(&cache_key_refs);
    let cache_check_time = cache_start.elapsed();

    let mut uncached_files: Vec<(&PathBuf, &'static str)> = Vec::new();
    let mut cache_hits = 0u64;

    for ((file_path, lang), cached) in supported_files.into_iter().zip(cached_values.into_iter()) {
        if let Some(symbols) = cached {
            cache_hits += 1;
            cached_symbols.extend(symbols);
        } else {
            uncached_files.push((file_path, lang));
        }
    }

    // Phase 3: Prefilter uncached files in parallel (if regex provided)
    let prefilter_start = std::time::Instant::now();
    let (files_to_fetch, skipped_prefilter) = match text_regex {
        Some(re) => {
            let matches: Vec<_> = uncached_files
                .par_iter()
                .filter(|(file_path, _)| prefilter_file(file_path, re))
                .map(|(file_path, lang)| ((*file_path).clone(), *lang))
                .collect();
            let skipped = uncached_files.len() - matches.len();
            (matches, skipped)
        }
        None => {
            let all: Vec<_> = uncached_files
                .into_iter()
                .map(|(file_path, lang)| (file_path.clone(), lang))
                .collect();
            (all, 0)
        }
    };
    let prefilter_time = prefilter_start.elapsed();
    let prefilter_matches = files_to_fetch.len();

    // Phase 4: Group by language
    for (file_path, lang) in files_to_fetch {
        uncached_by_lang
            .entry(lang.to_string())
            .or_default()
            .push(file_path);
    }

    let total_time = start.elapsed();
    let uncached_total: usize = uncached_by_lang.values().map(|v| v.len()).sum();

    fastrace::local::LocalSpan::add_properties(|| {
        [
            ("files_total", files.len().to_string()),
            ("cache_hits", cache_hits.to_string()),
            ("cached_symbols", cached_symbols.len().to_string()),
            ("uncached_files", uncached_total.to_string()),
            ("skipped_lang", skipped_lang.to_string()),
            ("skipped_prefilter", skipped_prefilter.to_string()),
            ("prefilter_matches", prefilter_matches.to_string()),
            (
                "cache_check_ms",
                format!("{:.1}", cache_check_time.as_secs_f64() * 1000.0),
            ),
            (
                "prefilter_ms",
                format!("{:.1}", prefilter_time.as_secs_f64() * 1000.0),
            ),
            (
                "total_ms",
                format!("{:.1}", total_time.as_secs_f64() * 1000.0),
            ),
        ]
    });

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

#[trace]
pub async fn collect_symbols_smart(
    ctx: &HandlerContext,
    workspace_root: &Path,
    files: &[PathBuf],
    text_pattern: Option<&str>,
    excluded_languages: &HashSet<String>,
) -> Result<Vec<SymbolInfo>, String> {
    let text_regex = text_pattern.and_then(pattern_to_text_regex);

    let (mut all_symbols, uncached_by_lang) = classify_all_files(
        ctx,
        workspace_root,
        files,
        text_regex.as_ref(),
        excluded_languages,
    );

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

    let start = std::time::Instant::now();
    let file_mtime = leta_fs::file_mtime(file_path);
    let cache_key = format!(
        "{}:{}:{}",
        file_path.display(),
        workspace_root.display(),
        file_mtime
    );
    let cache_key_time = start.elapsed();

    if let Some(cached) = ctx.symbol_cache.get::<Vec<SymbolInfo>>(&cache_key) {
        ctx.cache_stats.symbol_hits.fetch_add(1, Ordering::Relaxed);
        return Ok(cached);
    }
    ctx.cache_stats
        .symbol_misses
        .fetch_add(1, Ordering::Relaxed);

    debug!("get_file_symbols_no_wait: getting client for {}", file_path.display());
    let client = workspace.client().await.ok_or("No LSP client")?;
    let uri = leta_fs::path_to_uri(file_path);

    debug!("get_file_symbols_no_wait: ensure_document_open {}", file_path.display());
    workspace.ensure_document_open(file_path).await?;

    debug!("get_file_symbols_no_wait: sending documentSymbol request for {}", file_path.display());
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
    debug!("get_file_symbols_no_wait: got response for {}", file_path.display());

    let flatten_start = std::time::Instant::now();
    let symbols = match response {
        Some(resp) => {
            let rel_path = relative_path(file_path, workspace_root);
            flatten_document_symbols(&resp, &rel_path)
        }
        None => Vec::new(),
    };
    let flatten_time = flatten_start.elapsed();

    let cache_start = std::time::Instant::now();
    ctx.symbol_cache.set(&cache_key, &symbols);
    let cache_set_time = cache_start.elapsed();

    fastrace::local::LocalSpan::add_properties(|| {
        [
            (
                "cache_key_ms",
                format!("{:.2}", cache_key_time.as_secs_f64() * 1000.0),
            ),
            (
                "flatten_ms",
                format!("{:.2}", flatten_time.as_secs_f64() * 1000.0),
            ),
            (
                "cache_set_ms",
                format!("{:.2}", cache_set_time.as_secs_f64() * 1000.0),
            ),
        ]
    });

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

#[trace]
pub async fn handle_grep_streaming(
    ctx: &HandlerContext,
    params: GrepParams,
    tx: mpsc::Sender<StreamMessage>,
) {
    info!("handle_grep_streaming: starting inner");
    let result = handle_grep_streaming_inner(ctx, params, &tx).await;
    info!("handle_grep_streaming: inner completed with result {:?}", result.is_ok());

    match result {
        Ok((warning, truncated, count)) => {
            info!("handle_grep_streaming: sending Done message");
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
            info!("handle_grep_streaming: sending Error message: {}", e);
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
    info!(
        "handle_grep_streaming_inner: pattern={} workspace={} limit={}",
        params.pattern, params.workspace_root, params.limit
    );
    let workspace_root = PathBuf::from(&params.workspace_root);
    info!("handle_grep_streaming_inner: set workspace_root");

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

    let exclude_regexes: Vec<Regex> = params
        .exclude_patterns
        .iter()
        .filter_map(|p| Regex::new(p).ok())
        .collect();

    let filter = GrepFilter {
        regex: &regex,
        kinds: kinds_set.as_ref(),
        exclude_regexes: &exclude_regexes,
        path_regex: path_regex.as_ref(),
    };

    info!("handle_grep_streaming_inner: calling enumerate_source_files");
    let files = enumerate_source_files(&workspace_root, &excluded_languages);
    info!("handle_grep_streaming_inner: found {} files", files.len());

    let text_pattern = if should_use_prefilter(&pattern) {
        Some(pattern.as_str())
    } else {
        None
    };

    info!("handle_grep_streaming_inner: calling stream_and_filter_symbols");
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
    info!("handle_grep_streaming_inner: stream_and_filter_symbols done, count={}", count);

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
    info!("stream_and_filter_symbols: starting with {} files", files.len());
    let text_regex = text_pattern.and_then(pattern_to_text_regex);
    let mut count = 0u32;
    let mut files_processed = 0u32;

    // Process files in sorted order and stream symbols immediately
    for file_path in files {
        files_processed += 1;
        if files_processed % 50 == 0 || files_processed <= 5 || (files_processed >= 99 && files_processed <= 105) {
            info!("stream_and_filter_symbols: processing file {} ({}): {}", files_processed, count, file_path.display());
        }
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

        // Try cache first
        if let Some(symbols) = get_cached_symbols(ctx, workspace_root, file_path) {
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

        // Check prefilter for uncached files
        let should_fetch = match &text_regex {
            Some(re) => prefilter_file(file_path, re),
            None => true,
        };

        if !should_fetch {
            continue;
        }

        // Fetch from LSP
        info!("stream_and_filter_symbols: getting workspace for {}", lang);
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
        info!("stream_and_filter_symbols: got workspace, fetching symbols from LSP");
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
