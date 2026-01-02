"""Handler for declaration command."""

from ..rpc import DeclarationParams, DeclarationResult, LocationInfo
from ...lsp.protocol import LSPResponseError, LSPMethodNotSupported
from .base import HandlerContext


async def handle_declaration(
    ctx: HandlerContext, params: DeclarationParams
) -> DeclarationResult:
    workspace, doc, path = await ctx.get_workspace_and_document({
        "path": params.path,
        "workspace_root": params.workspace_root,
    })
    line, column = ctx.parse_position({"line": params.line, "column": params.column})
    context = params.context

    try:
        result = await workspace.client.send_request(
            "textDocument/declaration",
            {
                "textDocument": {"uri": doc.uri},
                "position": {"line": line, "character": column},
            },
        )
    except LSPResponseError as e:
        if e.is_method_not_found():
            raise LSPMethodNotSupported(
                "textDocument/declaration", workspace.server_config.name
            )
        raise

    locations = ctx.format_locations(result, workspace.root, context)
    return DeclarationResult(
        locations=[LocationInfo(**loc) for loc in locations]
    )
