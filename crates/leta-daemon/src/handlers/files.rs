use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use fastrace::trace;
use leta_types::{FileInfo, FilesParams, FilesResult, StreamDone, StreamMessage};
use regex::Regex;
use tokio::sync::mpsc;

use super::{relative_path, HandlerContext};

const DEFAULT_EXCLUDE_DIRS: &[&str] = &[
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "target",
    "build",
    "dist",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".eggs",
    ".cache",
    ".coverage",
    ".hypothesis",
    ".nox",
    ".ruff_cache",
    "__pypackages__",
    ".pants.d",
    ".pyre",
    ".pytype",
    "vendor",
    "third_party",
    ".bundle",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".parcel-cache",
    "coverage",
    ".nyc_output",
    ".zig-cache",
];

const BINARY_EXTENSIONS: &[&str] = &[
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".pdf", ".zip", ".tar",
    ".gz", ".bz2", ".xz", ".7z", ".rar", ".exe", ".dll", ".so", ".dylib", ".a", ".o", ".lib",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".avi",
    ".mov", ".mkv", ".pyc", ".pyo", ".class", ".jar", ".war", ".ear", ".db", ".sqlite", ".sqlite3",
    ".bin", ".dat", ".pak", ".bundle", ".lock",
];

#[trace]
pub async fn handle_files(
    _ctx: &HandlerContext,
    params: FilesParams,
) -> Result<FilesResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let target_path = params
        .subpath
        .clone()
        .map(PathBuf::from)
        .unwrap_or_else(|| workspace_root.clone());

    let mut exclude_dirs: HashSet<&str> = DEFAULT_EXCLUDE_DIRS.iter().copied().collect();

    for pattern in &params.include_patterns {
        exclude_dirs.remove(pattern.as_str());
    }

    let binary_exts: HashSet<&str> = BINARY_EXTENSIONS.iter().copied().collect();

    let filter_regex = params
        .filter_pattern
        .as_ref()
        .map(|p| Regex::new(p))
        .transpose()
        .map_err(|e| format!("Invalid filter pattern: {}", e))?;

    let head_limit = if params.head == 0 {
        usize::MAX
    } else {
        params.head as usize
    };
    let (files_info, excluded_dirs, total_bytes, total_lines, truncated) = walk_directory(
        &target_path,
        &workspace_root,
        &exclude_dirs,
        &binary_exts,
        &params,
        filter_regex.as_ref(),
        head_limit,
    );

    let total_files = files_info.len() as u32;

    Ok(FilesResult {
        files: files_info,
        total_files,
        total_bytes,
        total_lines,
        excluded_dirs,
        truncated,
    })
}

fn walk_directory(
    target_path: &Path,
    workspace_root: &Path,
    exclude_dirs: &HashSet<&str>,
    binary_exts: &HashSet<&str>,
    params: &FilesParams,
    filter_regex: Option<&Regex>,
    head: usize,
) -> (HashMap<String, FileInfo>, Vec<String>, u64, u32, bool) {
    let mut files_info: HashMap<String, FileInfo> = HashMap::new();
    let mut found_excluded: HashSet<String> = HashSet::new();
    let mut total_bytes: u64 = 0;
    let mut total_lines: u32 = 0;
    let mut truncated = false;

    let exclude_regexes: Vec<Regex> = params
        .exclude_patterns
        .iter()
        .filter_map(|p| Regex::new(p).ok())
        .collect();

    let include_regexes: Vec<Regex> = params
        .include_patterns
        .iter()
        .filter_map(|p| Regex::new(p).ok())
        .collect();

    let mut iter = walkdir::WalkDir::new(target_path).into_iter();

    while let Some(entry_result) = iter.next() {
        if files_info.len() >= head {
            truncated = true;
            break;
        }

        let entry = match entry_result {
            Ok(e) => e,
            Err(_) => continue,
        };

        let path = entry.path();
        let name = entry.file_name().to_string_lossy();
        let rel_path = relative_path(path, workspace_root);

        if entry.file_type().is_dir() {
            if entry.depth() == 0 {
                continue;
            }

            let is_default_excluded = exclude_dirs.contains(name.as_ref());
            let is_egg_info = name.ends_with(".egg-info");
            let is_pattern_excluded = exclude_regexes.iter().any(|re| re.is_match(&rel_path));
            let is_included = include_regexes.iter().any(|re| re.is_match(&rel_path));

            if is_egg_info {
                iter.skip_current_dir();
                continue;
            }

            if (is_default_excluded || is_pattern_excluded) && !is_included {
                if filter_regex.is_none() {
                    found_excluded.insert(rel_path);
                }
                iter.skip_current_dir();
                continue;
            }

            continue;
        }

        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");

        if binary_exts.contains(&format!(".{}", ext).as_str()) {
            continue;
        }

        if let Some(re) = filter_regex {
            if !re.is_match(&rel_path) {
                continue;
            }
        }

        if exclude_regexes.iter().any(|re| re.is_match(&rel_path)) {
            continue;
        }

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
        };

        total_bytes += bytes;
        total_lines += lines;
        files_info.insert(rel_path, file_info);
    }

    let mut excluded_dirs: Vec<String> = found_excluded.into_iter().collect();
    excluded_dirs.sort();

    (
        files_info,
        excluded_dirs,
        total_bytes,
        total_lines,
        truncated,
    )
}

fn count_lines(path: &Path) -> u32 {
    std::fs::read_to_string(path)
        .map(|content| content.lines().count() as u32)
        .unwrap_or(0)
}

pub async fn handle_files_streaming(
    _ctx: &HandlerContext,
    params: FilesParams,
    tx: mpsc::Sender<StreamMessage>,
) {
    let result = handle_files_streaming_inner(&params, &tx).await;

    match result {
        Ok((truncated, count)) => {
            let _ = tx
                .send(StreamMessage::Done(StreamDone {
                    warning: None,
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

async fn handle_files_streaming_inner(
    params: &FilesParams,
    tx: &mpsc::Sender<StreamMessage>,
) -> Result<(bool, u32), String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let target_path = params
        .subpath
        .clone()
        .map(PathBuf::from)
        .unwrap_or_else(|| workspace_root.clone());

    let mut exclude_dirs: HashSet<&str> = DEFAULT_EXCLUDE_DIRS.iter().copied().collect();

    for pattern in &params.include_patterns {
        exclude_dirs.remove(pattern.as_str());
    }

    let binary_exts: HashSet<&str> = BINARY_EXTENSIONS.iter().copied().collect();

    let filter_regex = params
        .filter_pattern
        .as_ref()
        .map(|p| Regex::new(p))
        .transpose()
        .map_err(|e| format!("Invalid filter pattern: {}", e))?;

    let head_limit = if params.head == 0 {
        usize::MAX
    } else {
        params.head as usize
    };

    let exclude_regexes: Vec<Regex> = params
        .exclude_patterns
        .iter()
        .filter_map(|p| Regex::new(p).ok())
        .collect();

    let include_regexes: Vec<Regex> = params
        .include_patterns
        .iter()
        .filter_map(|p| Regex::new(p).ok())
        .collect();

    let mut count = 0u32;
    let mut truncated = false;
    let mut iter = walkdir::WalkDir::new(&target_path)
        .sort_by_file_name()
        .into_iter();

    while let Some(entry_result) = iter.next() {
        if count as usize >= head_limit {
            truncated = true;
            break;
        }

        let entry = match entry_result {
            Ok(e) => e,
            Err(_) => continue,
        };

        let path = entry.path();
        let name = entry.file_name().to_string_lossy();
        let rel_path = relative_path(path, &workspace_root);

        if entry.file_type().is_dir() {
            if entry.depth() == 0 {
                continue;
            }

            let is_default_excluded = exclude_dirs.contains(name.as_ref());
            let is_egg_info = name.ends_with(".egg-info");
            let is_pattern_excluded = exclude_regexes.iter().any(|re| re.is_match(&rel_path));
            let is_included = include_regexes.iter().any(|re| re.is_match(&rel_path));

            if is_egg_info || ((is_default_excluded || is_pattern_excluded) && !is_included) {
                iter.skip_current_dir();
            }
            continue;
        }

        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");

        if binary_exts.contains(&format!(".{}", ext).as_str()) {
            continue;
        }

        if let Some(re) = filter_regex.as_ref() {
            if !re.is_match(&rel_path) {
                continue;
            }
        }

        if exclude_regexes.iter().any(|re| re.is_match(&rel_path)) {
            continue;
        }

        let metadata = match std::fs::metadata(path) {
            Ok(m) => m,
            Err(_) => continue,
        };

        let bytes = metadata.len();
        let lines = count_lines(path);

        let file_info = FileInfo {
            path: rel_path,
            lines,
            bytes,
        };

        if tx.send(StreamMessage::File(file_info)).await.is_err() {
            return Ok((false, count));
        }
        count += 1;
    }

    Ok((truncated, count))
}
