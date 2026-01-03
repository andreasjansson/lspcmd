"""Handler for show command."""

from pathlib import Path
from typing import Union

from ..rpc import ShowParams
from ...lsp.types import (
    TextDocumentPositionParams,
    DocumentSymbolParams,
    TextDocumentIdentifier,
    Position,
)
from ...utils.text import read_file_content, get_lines_around
from .base import HandlerContext, find_symbol_at_line, expand_variable_range, LocationDict


async def handle_show(
    ctx: HandlerContext, params: ShowParams
) -> Union[list[LocationDict], dict[str, object]]:
    """Handle show command, returning either locations or definition content."""
    body = params.body

    if params.direct_location:
        return await _handle_direct_definition(ctx, params, body)

    if body:
        return await _handle_definition_body(ctx, params)
    
    return await _handle_location_request(ctx, params)


async def _handle_direct_definition(
    ctx: HandlerContext, params: ShowParams, body: bool
) -> Union[list[LocationDict], dict[str, object]]:
    path = Path(params.path).resolve()
    workspace_root = Path(params.workspace_root).resolve()
    line = params.line
    context = params.context
    head = params.head or 200
    symbol_name = params.symbol_name
    symbol_kind = params.symbol_kind

    rel_path = ctx.relative_path(path, workspace_root)
    content = read_file_content(path)
    lines = content.splitlines()

    if body:
        range_start = params.range_start_line
        range_end = params.range_end_line

        if range_start is not None and range_end is not None:
            start = range_start - 1
            end = range_end - 1

            if start == end and symbol_kind in ("Constant", "Variable"):
                end = expand_variable_range(lines, start)
        else:
            workspace = await ctx.session.get_or_create_workspace(path, workspace_root)
            doc = await workspace.ensure_document_open(path)
            assert workspace.client is not None
            result = await workspace.client.send_request(
                "textDocument/documentSymbol",
                DocumentSymbolParams(textDocument=TextDocumentIdentifier(uri=doc.uri)),
            )
            if result:
                symbol = find_symbol_at_line(result, line - 1)
                if symbol:
                    start = symbol["range_start"]
                    end = symbol["range_end"]
                else:
                    start = end = line - 1
            else:
                start = end = line - 1

        if context > 0:
            start = max(0, start - context)
            end = min(len(lines) - 1, end + context)

        total_lines = end - start + 1
        truncated = total_lines > head
        if truncated:
            end = start + head - 1

        return {
            "path": rel_path,
            "start_line": start + 1,
            "end_line": end + 1,
            "content": "\n".join(lines[start : end + 1]),
            "truncated": truncated,
            "total_lines": total_lines,
            "head": head,
            "symbol": symbol_name,
        }
    else:
        location: LocationDict = {
            "path": rel_path,
            "line": line,
            "column": params.column,
        }

        if context > 0 and path.exists():
            ctx_lines, start, end = get_lines_around(content, line - 1, context)
            location["context_lines"] = ctx_lines
            location["context_start"] = start + 1

        return [location]


async def _handle_definition_body(ctx: HandlerContext, params: ShowParams) -> dict[str, object]:
    locations = await _handle_location_request(ctx, params)
    if not locations:
        return {"error": "Definition not found"}

    loc = locations[0]
    workspace_root = Path(params.workspace_root).resolve()
    path_val = loc.get("path")
    line_val = loc.get("line")
    assert path_val is not None and line_val is not None
    file_path = workspace_root / path_val
    target_line = line_val - 1
    context = params.context
    head = params.head or 200
    symbol_name = params.symbol_name

    workspace, doc, _ = await ctx.get_workspace_and_document({
        "path": str(file_path),
        "workspace_root": params.workspace_root,
    })

    assert workspace.client is not None

    result = await workspace.client.send_request(
        "textDocument/documentSymbol",
        DocumentSymbolParams(textDocument=TextDocumentIdentifier(uri=doc.uri)),
    )

    content = read_file_content(file_path)
    lines = content.splitlines()

    if result:
        symbol = find_symbol_at_line(result, target_line)
        if symbol:
            start = symbol["range_start"]
            end = symbol["range_end"]
            if context > 0:
                start = max(0, start - context)
                end = min(len(lines) - 1, end + context)

            total_lines = end - start + 1
            truncated = total_lines > head
            if truncated:
                end = start + head - 1

            return {
                "path": path_val,
                "start_line": start + 1,
                "end_line": end + 1,
                "content": "\n".join(lines[start : end + 1]),
                "truncated": truncated,
                "total_lines": total_lines,
                "head": head,
                "symbol": symbol_name,
            }
        else:
            return {"error": "Language server does not provide symbol ranges"}

    return {
        "path": path_val,
        "start_line": line_val,
        "end_line": line_val,
        "content": lines[target_line] if target_line < len(lines) else "",
    }


async def _handle_location_request(
    ctx: HandlerContext, params: ShowParams
) -> list[LocationDict]:
    workspace, doc, _ = await ctx.get_workspace_and_document({
        "path": params.path,
        "workspace_root": params.workspace_root,
    })
    line, column = ctx.parse_position({"line": params.line, "column": params.column})
    context = params.context

    assert workspace.client is not None

    result = await workspace.client.send_request(
        "textDocument/definition",
        TextDocumentPositionParams(
            textDocument=TextDocumentIdentifier(uri=doc.uri),
            position=Position(line=line, character=column),
        ),
    )

    return ctx.format_locations(result, workspace.root, context)
