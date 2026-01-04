"""Handler for supertypes command."""

from ..rpc import SupertypesParams, SupertypesResult, LocationInfo
from ...lsp.protocol import LSPResponseError, LSPMethodNotSupported
from ...lsp.types import (
    TextDocumentPositionParams,
    TypeHierarchyItemParams,
    TextDocumentIdentifier,
    Position,
)
from .base import HandlerContext


async def handle_supertypes(
    ctx: HandlerContext, params: SupertypesParams
) -> SupertypesResult:
    workspace, doc, _ = await ctx.get_workspace_and_document(
        {
            "path": params.path,
            "workspace_root": params.workspace_root,
        }
    )
    line, column = ctx.parse_position({"line": params.line, "column": params.column})
    context = params.context

    assert workspace.client is not None

    await workspace.client.wait_for_service_ready()

    # Check capabilities before sending request to avoid timeouts
    if not workspace.client.capabilities.supports_type_hierarchy():
        raise LSPMethodNotSupported(
            "textDocument/prepareTypeHierarchy", workspace.server_config.name
        )

    try:
        prepare_result = await workspace.client.send_request(
            "textDocument/prepareTypeHierarchy",
            TextDocumentPositionParams(
                textDocument=TextDocumentIdentifier(uri=doc.uri),
                position=Position(line=line, character=column),
            ),
        )
    except LSPResponseError as e:
        if e.is_method_not_found():
            raise LSPMethodNotSupported(
                "textDocument/prepareTypeHierarchy", workspace.server_config.name
            )
        raise

    if not prepare_result:
        return SupertypesResult(locations=[])

    item = prepare_result[0]

    try:
        result = await workspace.client.send_request(
            "typeHierarchy/supertypes",
            TypeHierarchyItemParams(item=item),
        )
    except LSPResponseError as e:
        if e.is_method_not_found():
            raise LSPMethodNotSupported(
                "typeHierarchy/supertypes", workspace.server_config.name
            )
        raise

    locations = ctx.format_type_hierarchy_items(result, workspace.root, context)
    return SupertypesResult(locations=[LocationInfo(**loc) for loc in locations])
