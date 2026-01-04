"""Handler for implementations command."""

from ..rpc import (
    ImplementationsParams as RPCImplementationsParams,
    ImplementationsResult,
    LocationInfo,
)
from ...lsp.protocol import LSPResponseError, LSPMethodNotSupported
from ...lsp.types import TextDocumentPositionParams, TextDocumentIdentifier, Position
from .base import HandlerContext


async def handle_implementations(
    ctx: HandlerContext, params: RPCImplementationsParams
) -> ImplementationsResult:
    workspace, doc, _ = await ctx.get_workspace_and_document(
        {
            "path": params.path,
            "workspace_root": params.workspace_root,
        }
    )
    assert workspace.client
    line, column = ctx.parse_position({"line": params.line, "column": params.column})
    context = params.context

    caps = workspace.client.capabilities.model_dump()
    if not caps.get("implementationProvider"):
        server_name = workspace.server_config.name
        return ImplementationsResult(
            error=f"Server '{server_name}' does not support implementations (may require a license)"
        )

    try:
        result = await workspace.client.send_request(
            "textDocument/implementation",
            TextDocumentPositionParams(
                textDocument=TextDocumentIdentifier(uri=doc.uri),
                position=Position(line=line, character=column),
            ),
        )
    except LSPResponseError as e:
        if e.is_method_not_found():
            raise LSPMethodNotSupported(
                "textDocument/implementation", workspace.server_config.name
            )
        raise

    locations = ctx.format_locations(result, workspace.root, context)
    return ImplementationsResult(locations=[LocationInfo(**loc) for loc in locations])
