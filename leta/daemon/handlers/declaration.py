"""Handler for declaration command."""

from ..rpc import (
    DeclarationParams as RPCDeclarationParams,
    DeclarationResult,
    LocationInfo,
)
from ...lsp.protocol import LSPResponseError, LSPMethodNotSupported
from ...lsp.types import TextDocumentPositionParams, TextDocumentIdentifier, Position
from .base import HandlerContext


async def handle_declaration(
    ctx: HandlerContext, params: RPCDeclarationParams
) -> DeclarationResult:
    workspace, doc, _ = await ctx.get_workspace_and_document(
        {
            "path": params.path,
            "workspace_root": params.workspace_root,
        }
    )
    line, column = ctx.parse_position({"line": params.line, "column": params.column})
    context = params.context

    assert workspace.client is not None

    # Check capabilities before sending request to avoid timeouts
    if not workspace.client.capabilities.supports_declaration():
        raise LSPMethodNotSupported(
            "textDocument/declaration", workspace.server_config.name
        )

    try:
        result = await workspace.client.send_request(
            "textDocument/declaration",
            TextDocumentPositionParams(
                textDocument=TextDocumentIdentifier(uri=doc.uri),
                position=Position(line=line, character=column),
            ),
        )
    except LSPResponseError as e:
        if e.is_method_not_found():
            raise LSPMethodNotSupported(
                "textDocument/declaration", workspace.server_config.name
            )
        raise

    locations = ctx.format_locations(result, workspace.root, context)
    return DeclarationResult(locations=[LocationInfo(**loc) for loc in locations])
