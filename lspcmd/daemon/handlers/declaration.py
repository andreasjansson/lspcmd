"""Handler for declaration command."""

from ..rpc import DeclarationParams as RPCDeclarationParams, DeclarationResult, LocationInfo
from ...lsp.types import TextDocumentPositionParams, TextDocumentIdentifier, Position
from .base import HandlerContext


async def handle_declaration(
    ctx: HandlerContext, params: RPCDeclarationParams
) -> DeclarationResult:
    workspace, doc, path = await ctx.get_workspace_and_document({
        "path": params.path,
        "workspace_root": params.workspace_root,
    })
    line, column = ctx.parse_position({"line": params.line, "column": params.column})
    context = params.context

    result = await workspace.client.send_request(
        "textDocument/declaration",
        TextDocumentPositionParams(
            textDocument=TextDocumentIdentifier(uri=doc.uri),
            position=Position(line=line, character=column),
        ),
    )

    locations = ctx.format_locations(result, workspace.root, context)
    return DeclarationResult(
        locations=[LocationInfo(**loc) for loc in locations]
    )
