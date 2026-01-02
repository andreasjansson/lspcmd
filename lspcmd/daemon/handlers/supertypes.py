"""Handler for supertypes command."""

from ..rpc import SupertypesParams, SupertypesResult, LocationInfo
from ...lsp.protocol import LSPResponseError, LSPMethodNotSupported
from ...lsp.types import (
    PrepareTypeHierarchyParams,
    TypeHierarchySupertypesParams,
    TextDocumentIdentifier,
    Position,
)
from .base import HandlerContext


async def handle_supertypes(
    ctx: HandlerContext, params: SupertypesParams
) -> SupertypesResult:
    workspace, doc, path = await ctx.get_workspace_and_document({
        "path": params.path,
        "workspace_root": params.workspace_root,
    })
    line, column = ctx.parse_position({"line": params.line, "column": params.column})
    context = params.context

    await workspace.client.wait_for_service_ready()

    try:
        prepare_result = await workspace.client.send_request(
            "textDocument/prepareTypeHierarchy",
            PrepareTypeHierarchyParams(
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
            TypeHierarchySupertypesParams(item=item),
        )
    except LSPResponseError as e:
        if e.is_method_not_found():
            raise LSPMethodNotSupported(
                "typeHierarchy/supertypes", workspace.server_config.name
            )
        raise

    locations = ctx.format_type_hierarchy_items(result, workspace.root, context)
    return SupertypesResult(
        locations=[LocationInfo(**loc) for loc in locations]
    )
