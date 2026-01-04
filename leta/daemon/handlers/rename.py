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

    logger.info(f"Rename: files_modified={files_modified}, renamed_files={renamed_files}")

    # Close old documents FIRST (before notifying about file changes)
    # This is important for servers like ruby-lsp that check if files are managed by client
    for old_path, new_path in renamed_files:
        await workspace.close_document(old_path)

    # Build list of file changes for didChangeWatchedFiles notification
    file_changes: list[tuple[Path, FileChangeType]] = []
    for old_path, new_path in renamed_files:
        file_changes.append((old_path, FileChangeType.Deleted))
        file_changes.append((new_path, FileChangeType.Created))
    for rel_path in files_modified:
        abs_path = workspace_root / rel_path
        if abs_path.exists() and abs_path not in [new for _, new in renamed_files]:
            file_changes.append((abs_path, FileChangeType.Changed))

    # Notify LSP about file changes (needed for jdtls and other file-watching servers)
    if file_changes:
        await workspace.notify_files_changed(file_changes)

    # Now open the new documents
    for old_path, new_path in renamed_files:
        await workspace.ensure_document_open(new_path)
    for rel_path in files_modified:
        abs_path = workspace_root / rel_path
        if abs_path.exists() and abs_path not in [new for _, new in renamed_files]:
            await workspace.ensure_document_open(abs_path)

    return RenameResult(files_changed=files_modified)


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
