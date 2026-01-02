"""Handler for references command."""

from ..rpc import ReferencesParams, ReferencesResult, LocationInfo
from ...lsp.types import (
    ReferenceParams,
    TextDocumentIdentifier,
    Position,
    ReferenceContext,
)
from .base import HandlerContext


async def handle_references(
    ctx: HandlerContext, params: ReferencesParams
) -> ReferencesResult:
    workspace, doc, path = await ctx.get_workspace_and_document({
        "path": params.path,
        "workspace_root": params.workspace_root,
    })
    assert workspace.client
    line, column = ctx.parse_position({"line": params.line, "column": params.column})
    context = params.context

    result = await workspace.client.send_request(
        "textDocument/references",
        ReferenceParams(
            text_document=TextDocumentIdentifier(uri=doc.uri),
            position=Position(line=line, character=column),
            context=ReferenceContext(include_declaration=True),
        ),
    )

    locations = ctx.format_locations(result, workspace.root, context)
    return ReferencesResult(
        locations=[LocationInfo(**loc) for loc in locations]
    )
