"""Handler for rename command."""

from pathlib import Path

from ..rpc import RenameParams as RPCRenameParams, RenameResult
from ...lsp.types import (
    RenameParams,
    WorkspaceEdit,
    TextEdit,
    TextDocumentEdit,
    CreateFile,
    RenameFile,
    DeleteFile,
    TextDocumentIdentifier,
    Position,
)
from ...utils.text import read_file_content
from ...utils.uri import uri_to_path
from .base import HandlerContext


async def handle_rename(ctx: HandlerContext, params: RPCRenameParams) -> RenameResult:
    workspace, doc, path = await ctx.get_workspace_and_document({
        "path": params.path,
        "workspace_root": params.workspace_root,
    })
    assert workspace.client
    line, column = ctx.parse_position({"line": params.line, "column": params.column})
    new_name = params.new_name
    workspace_root = Path(params.workspace_root).resolve()

    result = await workspace.client.send_request(
        "textDocument/rename",
        RenameParams(
            text_document=TextDocumentIdentifier(uri=doc.uri),
            position=Position(line=line, character=column),
            new_name=new_name,
        ),
    )

    if not result:
        raise ValueError("Rename not supported or failed")

    files_modified = await _apply_workspace_edit(ctx, result, workspace_root)
    return RenameResult(files_changed=files_modified)


async def _apply_workspace_edit(
    ctx: HandlerContext, edit: WorkspaceEdit, workspace_root: Path
) -> list[str]:
    files_modified: list[str] = []

    if edit.changes:
        for uri, text_edits in edit.changes.items():
            file_path = uri_to_path(uri)
            await _apply_text_edits(file_path, text_edits)
            files_modified.append(ctx.relative_path(file_path, workspace_root))

    if edit.document_changes:
        for change in edit.document_changes:
            if isinstance(change, CreateFile):
                file_path = uri_to_path(change.uri)
                file_path.touch()
                files_modified.append(ctx.relative_path(file_path, workspace_root))
            elif isinstance(change, RenameFile):
                old_path = uri_to_path(change.old_uri)
                new_path = uri_to_path(change.new_uri)
                new_path.parent.mkdir(parents=True, exist_ok=True)
                old_path.rename(new_path)
                files_modified.append(ctx.relative_path(new_path, workspace_root))
            elif isinstance(change, DeleteFile):
                file_path = uri_to_path(change.uri)
                file_path.unlink(missing_ok=True)
                files_modified.append(ctx.relative_path(file_path, workspace_root))
            elif isinstance(change, TextDocumentEdit):
                file_path = uri_to_path(change.text_document.uri)
                await _apply_text_edits(file_path, change.edits)
                files_modified.append(ctx.relative_path(file_path, workspace_root))

    return files_modified


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
        new_text = edit.new_text

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
            first_line = lines[start_line][:start_char] if start_line < len(lines) else ""
            last_line = lines[end_line][end_char:] if end_line < len(lines) else ""
            lines[start_line : end_line + 1] = [first_line + new_text + last_line]

    result = "".join(lines)
    if result.endswith("\n\n") and not content.endswith("\n\n"):
        result = result[:-1]

    file_path.write_text(result)
