"""Handler for files command."""

import logging
from pathlib import Path

from ..rpc import FilesParams, FilesResult, FileInfo
from .base import HandlerContext, DEFAULT_EXCLUDE_DIRS, BINARY_EXTENSIONS, is_excluded

logger = logging.getLogger(__name__)


async def handle_files(ctx: HandlerContext, params: FilesParams) -> FilesResult:
    workspace_root = Path(params.workspace_root).resolve()
    subpath = params.subpath
    exclude_patterns = params.exclude_patterns
    include_patterns = set(params.include_patterns)

    active_excludes = DEFAULT_EXCLUDE_DIRS - include_patterns

    if subpath:
        scan_root = Path(subpath).resolve()
        if not scan_root.exists():
            raise ValueError(f"Path does not exist: {subpath}")
        if not scan_root.is_dir():
            raise ValueError(f"Path is not a directory: {subpath}")
    else:
        scan_root = workspace_root

    files = ctx.find_all_files_for_tree(scan_root, active_excludes)

    if exclude_patterns:
        files = [
            f
            for f in files
            if not is_excluded(ctx.relative_path(f, workspace_root), exclude_patterns)
        ]

    files_by_language = ctx.group_files_by_language(files)
    symbol_counts_by_file: dict[Path, dict[str, int]] = {}

    for lang_id, lang_files in files_by_language.items():
        if lang_id is None:
            continue
        try:
            workspace = await ctx.session.get_or_create_workspace_for_language(
                lang_id, workspace_root
            )
            if workspace and workspace.client:
                for file_path in lang_files:
                    symbols = await ctx.get_file_symbols_cached(
                        workspace, workspace_root, file_path
                    )
                    counts: dict[str, int] = {}
                    for sym in symbols:
                        kind = sym.get("kind", "").lower()
                        if kind:
                            counts[kind] = counts.get(kind, 0) + 1
                    symbol_counts_by_file[file_path] = counts
                    if str(file_path) in workspace.open_documents:
                        await workspace.close_document(file_path)
        except Exception as e:
            logger.debug(f"Could not get symbols for {lang_id}: {e}")

    tree_data: dict[str, FileInfo] = {}
    total_bytes = 0
    total_files = 0
    total_lines = 0

    for file_path in sorted(files):
        rel_path = ctx.relative_path(file_path, workspace_root)
        try:
            size = file_path.stat().st_size
        except Exception:
            size = 0

        is_binary = file_path.suffix.lower() in BINARY_EXTENSIONS
        lines = 0
        if not is_binary:
            try:
                content = file_path.read_text(errors="replace")
                lines = content.count("\n") + (
                    1 if content and not content.endswith("\n") else 0
                )
            except Exception:
                pass

        symbols = symbol_counts_by_file.get(file_path, {})

        tree_data[rel_path] = FileInfo(
            path=rel_path,
            lines=lines,
            bytes=size,
            symbols=symbols,
        )
        total_bytes += size
        total_files += 1
        total_lines += lines

    return FilesResult(
        files=tree_data,
        total_files=total_files,
        total_bytes=total_bytes,
        total_lines=total_lines,
    )
