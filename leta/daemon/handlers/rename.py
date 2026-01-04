"""Handler for rename command."""

import logging
from pathlib import Path

from ..rpc import RenameParams as RPCRenameParams, RenameResult

logger = logging.getLogger(__name__)

from ...lsp.types import (
    RenameParams,
    TextDocumentIdentifier,
    Position,
    WorkspaceEdit,
    TextEdit,
    TextDocumentEdit,
    CreateFile,
    RenameFile,
    DeleteFile,
    FileChangeType,
)
from ...utils.text import read_file_content
from ...utils.uri import uri_to_path
from .base import HandlerContext


async def handle_rename(ctx: HandlerContext, params: RPCRenameParams) -> RenameResult:
    logger.info(f"Rename request: {params.path}:{params.line}:{params.column} -> {params.new_name}")
    workspace, doc, _ = await ctx.get_workspace_and_document(
        {
            "path": params.path,
            "workspace_root": params.workspace_root,
        }
    )
    line, column = ctx.parse_position({"line": params.line, "column": params.column})
    new_name = params.new_name
    workspace_root = Path(params.workspace_root).resolve()

    assert workspace.client is not None

    rename_params = RenameParams(
        textDocument=TextDocumentIdentifier(uri=doc.uri),
        position=Position(line=line, character=column),
        newName=new_name,
    )
    result = await workspace.client.send_request("textDocument/rename", rename_params)

    if not result:
        raise ValueError("Rename not supported or failed")

    files_modified, renamed_files = await _apply_workspace_edit(ctx, result, workspace_root)

    logger.debug(f"Rename: files_modified={files_modified}, renamed_files={renamed_files}")
    
    # For ruby-lsp, we need to close documents AFTER applying edits but BEFORE 
    # sending didChangeWatchedFiles. This is because ruby-lsp only calls 
    # index.handle_change for CHANGED if the file is NOT in the store.
    # The file content on disk must be the NEW content when ruby-lsp reads it.
    files_to_close = _get_files_from_workspace_edit(result, workspace_root)
    logger.info(f"Closing {len(files_to_close)} documents after applying edits: {files_to_close}")
    for file_path in files_to_close:
        await workspace.close_document(file_path)

    # Build list of file changes for didChangeWatchedFiles notification
    # 
    # For ruby-lsp, we MUST use DELETED followed by CREATED for modified files:
    # - DELETED: calls index.delete(uri) unconditionally - removes old entries
    # - CREATED: calls index.index_single(uri, content) - adds new entries
    # 
    # Using CHANGED doesn't work reliably because:
    # - CHANGED only calls handle_change if file is NOT in store
    # - The didClose notification might not be processed before didChangeWatchedFiles
    file_changes: list[tuple[Path, FileChangeType]] = []
    for old_path, new_path in renamed_files:
        file_changes.append((old_path, FileChangeType.Deleted))
        file_changes.append((new_path, FileChangeType.Created))
    for rel_path in files_modified:
        abs_path = workspace_root / rel_path
        if abs_path.exists() and abs_path not in [new for _, new in renamed_files]:
            file_changes.append((abs_path, FileChangeType.Deleted))
            file_changes.append((abs_path, FileChangeType.Created))

    # Notify LSP about file changes (needed for servers that watch files)
    if file_changes:
        logger.info(f"Notifying LSP about {len(file_changes)} file changes: {file_changes}")
        await workspace.notify_files_changed(file_changes)
        
        # For ruby-lsp, we need to wait for it to process the file changes
        # It processes messages in order from stdin, so we need to ensure the
        # didChangeWatchedFiles notification is fully written before sending
        # the sync request.
        if workspace.client and workspace.client.server_name == "ruby-lsp":
            import asyncio
            from ...lsp.types import WorkspaceSymbolParams
            try:
                # Small delay to ensure the notification is sent first
                await asyncio.sleep(0.05)
                logger.info("Sending workspace/symbol sync request to ruby-lsp")
                # Send a request that forces queue processing - ruby-lsp processes
                # messages in order, so by the time we get a response, the notification
                # should have been processed
                await workspace.client.send_request(
                    "workspace/symbol",
                    WorkspaceSymbolParams(query="__leta_sync__"),
                    timeout=5.0,
                )
                logger.info("workspace/symbol sync completed")
            except Exception as e:
                logger.warning(f"workspace/symbol sync failed: {e}")

    # Reopen all modified documents
    # This also forces the LSP to process the file changes (especially for ruby-lsp
    # which processes messages asynchronously) because ensure_document_open sends a
    # documentSymbol request and waits for the response
    for old_path, new_path in renamed_files:
        await workspace.ensure_document_open(new_path)
    for rel_path in files_modified:
        abs_path = workspace_root / rel_path
        if abs_path.exists() and abs_path not in [new for _, new in renamed_files]:
            await workspace.ensure_document_open(abs_path)

    return RenameResult(files_changed=files_modified)


def _get_files_from_workspace_edit(edit: WorkspaceEdit, workspace_root: Path) -> list[Path]:
    """Extract all file paths that will be modified by a workspace edit."""
    files: list[Path] = []
    
    if edit.changes:
        for uri in edit.changes.keys():
            files.append(uri_to_path(uri))
    
    if edit.documentChanges:
        for change in edit.documentChanges:
            if isinstance(change, TextDocumentEdit):
                files.append(uri_to_path(change.textDocument.uri))
            elif isinstance(change, RenameFile):
                files.append(uri_to_path(change.oldUri))
            elif isinstance(change, CreateFile):
                pass  # New file, nothing to close
            elif isinstance(change, DeleteFile):
                files.append(uri_to_path(change.uri))
    
    return files


async def _apply_workspace_edit(
    ctx: HandlerContext, edit: WorkspaceEdit, workspace_root: Path
) -> tuple[list[str], list[tuple[Path, Path]]]:
    """Apply a workspace edit and return (files_modified, renamed_files).
    
    renamed_files is a list of (old_path, new_path) tuples for file renames.
    """
    files_modified: list[str] = []
    renamed_files: list[tuple[Path, Path]] = []

    if edit.changes:
        for uri, text_edits in edit.changes.items():
            file_path = uri_to_path(uri)
            await _apply_text_edits(file_path, text_edits)
            files_modified.append(ctx.relative_path(file_path, workspace_root))

    if edit.documentChanges:
        for change in edit.documentChanges:
            if isinstance(change, CreateFile):
                file_path = uri_to_path(change.uri)
                file_path.touch()
                files_modified.append(ctx.relative_path(file_path, workspace_root))
            elif isinstance(change, RenameFile):
                old_path = uri_to_path(change.oldUri)
                new_path = uri_to_path(change.newUri)
                # Skip if already renamed (handles duplicate rename operations from some LSP servers)
                if not old_path.exists():
                    logger.debug(f"Skipping rename: source file does not exist: {old_path}")
                    continue
                if new_path.exists():
                    logger.debug(f"Skipping rename: target file already exists: {new_path}")
                    continue
                new_path.parent.mkdir(parents=True, exist_ok=True)
                old_path.rename(new_path)
                files_modified.append(ctx.relative_path(new_path, workspace_root))
                renamed_files.append((old_path, new_path))
            elif isinstance(change, DeleteFile):
                file_path = uri_to_path(change.uri)
                file_path.unlink(missing_ok=True)
                files_modified.append(ctx.relative_path(file_path, workspace_root))
            elif isinstance(change, TextDocumentEdit):
                file_path = uri_to_path(change.textDocument.uri)
                await _apply_text_edits(file_path, change.edits)
                files_modified.append(ctx.relative_path(file_path, workspace_root))

    return files_modified, renamed_files


async def _apply_text_edits(file_path: Path, edits: list[TextEdit]) -> None:
    content = read_file_content(file_path)
    lines = content.splitlines(keepends=True)

    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    sorted_edits = sorted(
        edits,
        key=lambda e: (e.range.start.line, e.range.start.character),
        reverse=True,
    )

    for edit in sorted_edits:
        start = edit.range.start
        end = edit.range.end
        new_text = edit.newText

        start_line = start.line
        start_char = start.character
        end_line = end.line
        end_char = end.character

        if start_line >= len(lines):
            lines.extend([""] * (start_line - len(lines) + 1))

        if start_line == end_line:
            line = lines[start_line] if start_line < len(lines) else ""
            lines[start_line] = line[:start_char] + new_text + line[end_char:]
        else:
            first_line = (
                lines[start_line][:start_char] if start_line < len(lines) else ""
            )
            last_line = lines[end_line][end_char:] if end_line < len(lines) else ""
            lines[start_line : end_line + 1] = [first_line + new_text + last_line]

    result = "".join(lines)
    if result.endswith("\n\n") and not content.endswith("\n\n"):
        result = result[:-1]

    file_path.write_text(result)
