"""Handler for subtypes command."""

from ..rpc import SubtypesParams, SubtypesResult, LocationInfo
from ...lsp.protocol import LSPResponseError, LSPMethodNotSupported
from ...lsp.types import (
    TextDocumentPositionParams,
    TypeHierarchyItemParams,
    TextDocumentIdentifier,
    Position,
)
from .base import HandlerContext


async def handle_subtypes(
    ctx: HandlerContext, params: SubtypesParams
) -> SubtypesResult:
    workspace, doc, path = await ctx.get_workspace_and_document({
        "path": params.path,
        "workspace_root": params.workspace_root,
    })
    assert workspace.client
    line, column = ctx.parse_position({"line": params.line, "column": params.column})
    context = params.context

    await workspace.client.wait_for_service_ready()

    try:
        prepare_result = await workspace.client.send_request(
            "textDocument/prepareTypeHierarchy",
            TextDocumentPositionParams(
                text_document=TextDocumentIdentifier(uri=doc.uri),
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
        return SubtypesResult(locations=[])

    item = prepare_result[0]

    try:
        result = await workspace.client.send_request(
            "typeHierarchy/subtypes",
            TypeHierarchyItemParams(item=item),
        )
    except LSPResponseError as e:
        if e.is_method_not_found():
            raise LSPMethodNotSupported(
                "typeHierarchy/subtypes", workspace.server_config.name
            )
        raise

    locations = ctx.format_type_hierarchy_items(result, workspace.root, context)
    return SubtypesResult(
        locations=[LocationInfo(**loc) for loc in locations]
    )
