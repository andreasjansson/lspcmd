use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use fastrace::trace;
use leta_types::{FileInfo, FilesParams, FilesResult};
use regex::Regex;

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

    let (files_info, excluded_dirs, total_bytes, total_lines) = walk_directory(
        &target_path,
        &workspace_root,
        &exclude_dirs,
        &binary_exts,
        &params,
        filter_regex.as_ref(),
    );

    let total_files = files_info.len() as u32;

    Ok(FilesResult {
        files: files_info,
        total_files,
        total_bytes,
        total_lines,
        excluded_dirs,
    })
}

fn walk_directory(
    target_path: &Path,
    workspace_root: &Path,
    exclude_dirs: &HashSet<&str>,
    binary_exts: &HashSet<&str>,
    params: &FilesParams,
    filter_regex: Option<&Regex>,
) -> (HashMap<String, FileInfo>, Vec<String>, u64, u32) {
    let mut files_info: HashMap<String, FileInfo> = HashMap::new();
    let mut found_excluded: HashSet<String> = HashSet::new();
    let mut total_bytes: u64 = 0;
    let mut total_lines: u32 = 0;

    let mut iter = walkdir::WalkDir::new(target_path).into_iter();

    while let Some(entry_result) = iter.next() {
        let entry = match entry_result {
            Ok(e) => e,
            Err(_) => continue,
        };

        let path = entry.path();
        let name = entry.file_name().to_string_lossy();

        if entry.file_type().is_dir() {
            if entry.depth() == 0 {
                continue;
            }

            let is_default_excluded = exclude_dirs.contains(name.as_ref());
            let is_egg_info = name.ends_with(".egg-info");
            let is_pattern_excluded =
                is_excluded_by_patterns(path, workspace_root, &params.exclude_patterns);
            let is_included = params.include_patterns.iter().any(|p| p == name.as_ref());

            if is_egg_info {
                iter.skip_current_dir();
                continue;
            }

            if (is_default_excluded || is_pattern_excluded) && !is_included {
                let rel_path = relative_path(path, workspace_root);
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

        let rel_path = relative_path(path, workspace_root);

        if let Some(re) = filter_regex {
            if !re.is_match(&rel_path) {
                continue;
            }
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

    (files_info, excluded_dirs, total_bytes, total_lines)
}

fn count_lines(path: &Path) -> u32 {
    std::fs::read_to_string(path)
        .map(|content| content.lines().count() as u32)
        .unwrap_or(0)
}

fn is_excluded_by_patterns(path: &Path, workspace_root: &Path, patterns: &[String]) -> bool {
    let rel_path = relative_path(path, workspace_root);

    for pattern in patterns {
        if let Ok(re) = Regex::new(pattern) {
            if re.is_match(&rel_path) {
                return true;
            }
        }
    }
    false
}
