"""Handler for move-file command."""

import asyncio
from pathlib import Path

from ..rpc import MoveFileParams, MoveFileResult
from ...lsp.protocol import LSPResponseError
from ...lsp.types import (
    RenameFilesParams,
    FileRename,
    WorkspaceEdit,
    TextEdit,
    TextDocumentEdit,
    CreateFile,
    RenameFile,
    DeleteFile,
)
from ...utils.text import read_file_content
from ...utils.uri import path_to_uri, uri_to_path
from .base import HandlerContext


async def handle_move_file(
    ctx: HandlerContext, params: MoveFileParams
) -> MoveFileResult:
    old_path = Path(params.old_path).resolve()
    new_path = Path(params.new_path).resolve()
    workspace_root = Path(params.workspace_root).resolve()

    if not old_path.exists():
        raise ValueError(f"Source file does not exist: {old_path}")

    if new_path.exists():
        raise ValueError(f"Destination already exists: {new_path}")

    workspace = await ctx.session.get_or_create_workspace(old_path, workspace_root)
    if not workspace or not workspace.client:
        raise ValueError(f"No language server available for {old_path.suffix} files")

    await workspace.client.wait_for_service_ready()

    server_name = workspace.server_config.name
    caps = workspace.client.capabilities.model_dump()
    supports_will_rename = (
        caps.get("workspace", {}).get("fileOperations", {}).get("willRename")
    )

    if not supports_will_rename:
        raise ValueError(f"move-file is not supported by {server_name}")

    opened_for_indexing: list[Path] = []
    if old_path.suffix == ".py":
        python_files = ctx.find_all_source_files(workspace_root)
        python_files = [f for f in python_files if f.suffix == ".py" and f != old_path]
        for file_path in python_files:
            if str(file_path) not in workspace.open_documents:
                await workspace.ensure_document_open(file_path)
                opened_for_indexing.append(file_path)
        if opened_for_indexing:
            await asyncio.sleep(0.5)

    old_uri = path_to_uri(old_path)
    new_uri = path_to_uri(new_path)

    try:
        workspace_edit = await workspace.client.send_request(
            "workspace/willRenameFiles",
            RenameFilesParams(files=[FileRename(oldUri=old_uri, newUri=new_uri)]),
        )
    except LSPResponseError as e:
        if e.is_method_not_found():
            raise ValueError(f"move-file is not supported by {server_name}")
        raise
    finally:
        for file_path in opened_for_indexing:
            await workspace.close_document(file_path)

    files_modified: list[str] = []
    imports_updated = False
    file_already_moved = False

    if workspace_edit:
        additional_files, file_already_moved = await _apply_workspace_edit_for_move(
            ctx, workspace_edit, workspace_root, old_path, new_path
        )
        files_modified.extend(additional_files)
        imports_updated = (
            len(
                [
                    f
                    for f in additional_files
                    if f != ctx.relative_path(new_path, workspace_root)
                ]
            )
            > 0
        )

    if not file_already_moved:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.rename(new_path)
        files_modified.append(ctx.relative_path(new_path, workspace_root))

    return MoveFileResult(
        files_changed=list(dict.fromkeys(files_modified)),
        imports_updated=imports_updated,
    )


async def _apply_workspace_edit_for_move(
    ctx: HandlerContext,
    edit: WorkspaceEdit,
    workspace_root: Path,
    move_old_path: Path,
    move_new_path: Path,
) -> tuple[list[str], bool]:
    files_modified: list[str] = []
    file_moved = False

    if edit.changes:
        for uri, text_edits in edit.changes.items():
            file_path = uri_to_path(uri)
            await _apply_text_edits(file_path, text_edits)
            files_modified.append(ctx.relative_path(file_path, workspace_root))

    if edit.documentChanges:
        for change in edit.documentChanges:
            if isinstance(change, CreateFile):
                file_path = uri_to_path(change.uri)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.touch()
                files_modified.append(ctx.relative_path(file_path, workspace_root))
            elif isinstance(change, RenameFile):
                old_path = uri_to_path(change.oldUri)
                new_path = uri_to_path(change.newUri)
                if old_path == move_old_path and new_path == move_new_path:
                    file_moved = True
                new_path.parent.mkdir(parents=True, exist_ok=True)
                old_path.rename(new_path)
                files_modified.append(ctx.relative_path(new_path, workspace_root))
            elif isinstance(change, DeleteFile):
                file_path = uri_to_path(change.uri)
                file_path.unlink(missing_ok=True)
                files_modified.append(ctx.relative_path(file_path, workspace_root))
            elif isinstance(change, TextDocumentEdit):
                file_path = uri_to_path(change.textDocument.uri)
                await _apply_text_edits(file_path, change.edits)
                files_modified.append(ctx.relative_path(file_path, workspace_root))

    return files_modified, file_moved


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
