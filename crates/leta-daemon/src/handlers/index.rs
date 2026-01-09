use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use fastrace::collector::Config as FastraceConfig;
use fastrace::prelude::*;
use fastrace::trace;
use leta_config::Config;
use leta_fs::get_language_id;
use leta_servers::get_server_for_language;
use leta_types::{AddWorkspaceParams, AddWorkspaceResult};
use tokio::sync::Semaphore;
use tracing::{info, warn};

use super::{get_file_symbols, HandlerContext};
use crate::profiling::CollectingReporter;

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
pub async fn handle_add_workspace(
    ctx: &HandlerContext,
    params: AddWorkspaceParams,
) -> Result<AddWorkspaceResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root)
        .canonicalize()
        .map_err(|e| format!("Invalid path: {}", e))?;
    let workspace_str = workspace_root.to_string_lossy().to_string();

    let config = Config::load().map_err(|e| e.to_string())?;

    if config.workspaces.roots.contains(&workspace_str) {
        return Ok(AddWorkspaceResult {
            added: false,
            workspace_root: workspace_str,
            message: "Workspace already exists".to_string(),
        });
    }

    Config::add_workspace_root(&workspace_root).map_err(|e| e.to_string())?;

    info!("Added workspace: {}", workspace_root.display());

    let ctx_clone = HandlerContext::new(
        Arc::clone(&ctx.session),
        Arc::clone(&ctx.hover_cache),
        Arc::clone(&ctx.symbol_cache),
    );
    let workspace_root_clone = workspace_root.clone();

    tokio::spawn(async move {
        index_workspace_background(ctx_clone, workspace_root_clone).await;
    });

    Ok(AddWorkspaceResult {
        added: true,
        workspace_root: workspace_str,
        message: "Workspace added, indexing started in background".to_string(),
    })
}

#[trace]
async fn index_workspace_background(ctx: HandlerContext, workspace_root: PathBuf) {
    let start = std::time::Instant::now();
    info!(
        "Starting background indexing for {}",
        workspace_root.display()
    );

    let exclude_dirs: HashSet<&str> = DEFAULT_EXCLUDE_DIRS.iter().copied().collect();
    let binary_exts: HashSet<&str> = BINARY_EXTENSIONS.iter().copied().collect();

    let mut files_by_lang: std::collections::HashMap<String, Vec<PathBuf>> =
        std::collections::HashMap::new();

    for entry in walkdir::WalkDir::new(&workspace_root)
        .into_iter()
        .filter_entry(|e| {
            let name = e.file_name().to_string_lossy();
            if name.starts_with('.') && e.depth() > 0 {
                return false;
            }
            !exclude_dirs.contains(name.as_ref()) && !name.ends_with(".egg-info")
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

        let lang = get_language_id(path);
        if lang != "plaintext" && get_server_for_language(&lang, None).is_some() {
            files_by_lang
                .entry(lang.to_string())
                .or_default()
                .push(path.to_path_buf());
        }
    }

    let total_files: usize = files_by_lang.values().map(|v| v.len()).sum();
    info!(
        "Found {} source files across {} languages",
        total_files,
        files_by_lang.len()
    );

    let num_cpus = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4);
    let semaphore = Arc::new(Semaphore::new(num_cpus));

    let mut total_indexed = 0u32;
    let mut files_by_language: std::collections::HashMap<String, u32> =
        std::collections::HashMap::new();
    let mut time_by_language: std::collections::HashMap<String, u64> =
        std::collections::HashMap::new();
    let mut server_startups: Vec<leta_types::ServerStartupStats> = Vec::new();

    for (lang, files) in &files_by_lang {
        let file_count = files.len() as u32;

        let workspace = match ctx
            .session
            .get_or_create_workspace_for_language(lang, &workspace_root)
            .await
        {
            Ok(ws) => ws,
            Err(e) => {
                warn!("Failed to get workspace for {}: {}", lang, e);
                continue;
            }
        };

        if let Some(startup_stats) = workspace.get_startup_stats().await {
            if startup_stats.total_time_ms > 0 {
                server_startups.push(startup_stats);
            }
        }

        workspace.wait_for_ready(60).await;

        let lang_start = std::time::Instant::now();
        let mut handles = Vec::new();

        for file_path in files {
            let permit = semaphore.clone().acquire_owned().await.unwrap();
            let ctx = HandlerContext::new(
                Arc::clone(&ctx.session),
                Arc::clone(&ctx.hover_cache),
                Arc::clone(&ctx.symbol_cache),
            );
            let workspace_root = workspace_root.clone();
            let lang = lang.clone();
            let file_path = file_path.clone();

            let handle = tokio::spawn(async move {
                let result = index_single_file(&ctx, &workspace_root, &file_path, &lang).await;
                drop(permit);
                result
            });
            handles.push(handle);
        }

        let mut lang_indexed = 0u32;
        for handle in handles {
            match handle.await {
                Ok(Ok(())) => lang_indexed += 1,
                Ok(Err(_)) => {}
                Err(_) => {}
            }
        }

        let lang_time = lang_start.elapsed();
        total_indexed += lang_indexed;
        files_by_language.insert(lang.clone(), file_count);
        time_by_language.insert(lang.clone(), lang_time.as_millis() as u64);

        info!("Indexed {} {} files in {:?}", lang_indexed, lang, lang_time);
    }

    let total_time = start.elapsed();
    info!(
        "Background indexing complete: {} files in {:?}",
        total_indexed, total_time
    );

    let stats = leta_types::IndexingStats {
        workspace_root: workspace_root.to_string_lossy().to_string(),
        total_files: total_indexed,
        files_by_language,
        total_time_ms: total_time.as_millis() as u64,
        time_by_language,
        server_startups,
    };
    ctx.session.add_indexing_stats(stats).await;
}

#[trace]
async fn index_single_file(
    ctx: &HandlerContext,
    workspace_root: &Path,
    file_path: &Path,
    lang: &str,
) -> Result<(), String> {
    let workspace = ctx
        .session
        .get_or_create_workspace_for_language(lang, workspace_root)
        .await?;

    get_file_symbols(ctx, &workspace, workspace_root, file_path).await?;
    Ok(())
}
