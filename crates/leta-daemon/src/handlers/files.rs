use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use fastrace::prelude::*;
use leta_fs::get_language_id;
use leta_servers::get_server_for_language;
use leta_types::{FileInfo, FilesParams, FilesResult, SymbolInfo};
use tracing::info;

use super::{get_file_symbols, relative_path, HandlerContext};

const DEFAULT_EXCLUDE_DIRS: &[&str] = &[
    ".git", "__pycache__", "node_modules", ".venv", "venv", "target",
    "build", "dist", ".tox", ".mypy_cache", ".pytest_cache", ".eggs",
    ".cache", ".coverage", ".hypothesis", ".nox", ".ruff_cache",
    "__pypackages__", ".pants.d", ".pyre", ".pytype", "vendor",
    "third_party", ".bundle", ".next", ".nuxt", ".svelte-kit",
    ".turbo", ".parcel-cache", "coverage", ".nyc_output", ".zig-cache",
];

const BINARY_EXTENSIONS: &[&str] = &[
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".a", ".o", ".lib",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".avi", ".mov", ".mkv",
    ".pyc", ".pyo", ".class", ".jar", ".war", ".ear",
    ".db", ".sqlite", ".sqlite3", ".bin", ".dat", ".pak", ".bundle", ".lock",
];

#[instrument(skip(ctx), fields(workspace_root = %params.workspace_root))]
pub async fn handle_files(
    ctx: &HandlerContext,
    params: FilesParams,
) -> Result<FilesResult, String> {
    let start = std::time::Instant::now();
    let workspace_root = PathBuf::from(&params.workspace_root);
    let target_path = params.subpath
        .map(PathBuf::from)
        .unwrap_or_else(|| workspace_root.clone());

    let mut exclude_dirs: HashSet<&str> = DEFAULT_EXCLUDE_DIRS.iter().copied().collect();
    
    for pattern in &params.include_patterns {
        exclude_dirs.remove(pattern.as_str());
    }

    let binary_exts: HashSet<&str> = BINARY_EXTENSIONS.iter().copied().collect();

    let mut files_info: HashMap<String, FileInfo> = HashMap::new();
    let mut total_bytes: u64 = 0;
    let mut total_lines: u32 = 0;

    let mut source_files_by_lang: HashMap<String, Vec<PathBuf>> = HashMap::new();

    let walk_start = std::time::Instant::now();
    for entry in walkdir::WalkDir::new(&target_path)
        .into_iter()
        .filter_entry(|e| {
            let name = e.file_name().to_string_lossy();
            if name.starts_with('.') && e.depth() > 0 {
                return params.include_patterns.iter().any(|p| p == name.as_ref());
            }
            if exclude_dirs.contains(name.as_ref()) {
                return params.include_patterns.iter().any(|p| p == name.as_ref());
            }
            if name.ends_with(".egg-info") {
                return false;
            }
            !is_excluded_by_patterns(e.path(), &workspace_root, &params.exclude_patterns)
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
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        
        if binary_exts.contains(&format!(".{}", ext).as_str()) {
            continue;
        }

        let rel_path = relative_path(path, &workspace_root);
        
        let metadata = match std::fs::metadata(path) {
            Ok(m) => m,
            Err(_) => continue,
        };
        
        let bytes = metadata.len();
        let lines = count_lines(path);

        let file_info = FileInfo {
            path: rel_path.clone(),
            lines,
            bytes,
            symbols: HashMap::new(),
        };

        let lang = get_language_id(path);
        if lang != "plaintext" && get_server_for_language(&lang, None).is_some() {
            source_files_by_lang.entry(lang.to_string()).or_default().push(path.to_path_buf());
        }

        total_bytes += bytes;
        total_lines += lines;
        files_info.insert(rel_path, file_info);
    }
    info!("walk_dir took {:?}, found {} files, {} source files by language", 
          walk_start.elapsed(), files_info.len(), source_files_by_lang.len());

    let lsp_start = std::time::Instant::now();
    let mut lsp_files_processed = 0;
    for (lang, files) in &source_files_by_lang {
        let lang_start = std::time::Instant::now();
        let file_count = files.len();
        
        let workspace = match ctx.session.get_or_create_workspace_for_language(lang, &workspace_root).await {
            Ok(ws) => ws,
            Err(e) => {
                info!("Failed to get workspace for {}: {}", lang, e);
                continue;
            }
        };
        info!("get_or_create_workspace for {} took {:?}", lang, lang_start.elapsed());

        let ready_start = std::time::Instant::now();
        workspace.wait_for_ready(30).await;
        info!("wait_for_ready for {} took {:?}", lang, ready_start.elapsed());

        let symbols_start = std::time::Instant::now();
        
        for file_path in files {
            let rel_path = relative_path(file_path, &workspace_root);
            
            match get_file_symbols(ctx, &workspace, &workspace_root, file_path).await {
                Ok(symbols) => {
                    if let Some(file_info) = files_info.get_mut(&rel_path) {
                        file_info.symbols = count_symbols(&symbols);
                    }
                }
                Err(e) => {
                    info!("Failed to get symbols for {}: {}", rel_path, e);
                }
            }
            lsp_files_processed += 1;
        }
        info!("documentSymbol for {} ({} files): {:?}", lang, file_count, symbols_start.elapsed());
    }
    info!("total LSP processing took {:?}, processed {} files", lsp_start.elapsed(), lsp_files_processed);

    let total_files = files_info.len() as u32;

    info!("handle_files total time: {:?}", start.elapsed());
    Ok(FilesResult {
        files: files_info,
        total_files,
        total_bytes,
        total_lines,
    })
}

fn count_lines(path: &Path) -> u32 {
    std::fs::read_to_string(path)
        .map(|content| content.lines().count() as u32)
        .unwrap_or(0)
}

fn count_symbols(symbols: &[SymbolInfo]) -> HashMap<String, u32> {
    let mut counts: HashMap<String, u32> = HashMap::new();
    for sym in symbols {
        let kind = sym.kind.to_string().to_lowercase();
        *counts.entry(kind).or_insert(0) += 1;
    }
    counts
}

fn is_excluded_by_patterns(path: &Path, workspace_root: &Path, patterns: &[String]) -> bool {
    let rel_path = relative_path(path, workspace_root);
    let path_parts: Vec<&str> = Path::new(&rel_path).iter().filter_map(|s| s.to_str()).collect();
    let filename = Path::new(&rel_path).file_name().and_then(|s| s.to_str()).unwrap_or("");

    for pattern in patterns {
        if glob_match(&rel_path, pattern) {
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
    regex::Regex::new(&format!("^{}$", regex_pattern))
        .map(|r| r.is_match(text))
        .unwrap_or(false)
}
