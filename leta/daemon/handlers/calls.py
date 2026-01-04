"""Handler for calls command."""

from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from ..rpc import CallsParams, CallsResult, CallNode
from ...lsp.protocol import LSPResponseError, LSPMethodNotSupported
from ...lsp.types import (
    SymbolKind,
    CallHierarchyItem,
    CallHierarchyItemParams,
    TextDocumentPositionParams,
    TextDocumentIdentifier,
    Position,
)
from ...utils.uri import uri_to_path
from .base import HandlerContext

if TYPE_CHECKING:
    from ..session import Workspace


class FormattedCallItem(TypedDict):
    name: str
    kind: str | None
    detail: str | None
    path: str
    line: int
    column: int


class FormattedCallItemWithCalls(FormattedCallItem, total=False):
    calls: list["FormattedCallItemWithCalls"]
    called_by: list["FormattedCallItemWithCalls"]
    from_ranges: list[dict[str, int]]
    call_sites: list[dict[str, int]]


async def handle_calls(ctx: HandlerContext, params: CallsParams) -> CallsResult:
    workspace_root = Path(params.workspace_root).resolve()
    mode = params.mode
    max_depth = params.max_depth
    include_non_workspace = params.include_non_workspace

    if mode == "outgoing":
        if (
            params.from_path is None
            or params.from_line is None
            or params.from_column is None
        ):
            return CallsResult(
                error="from_path, from_line, and from_column are required for outgoing mode"
            )
        path = Path(params.from_path).resolve()
        line = params.from_line
        column = params.from_column
        symbol_name = params.from_symbol or ""
        result = await _get_outgoing_calls_tree(
            ctx,
            workspace_root,
            path,
            line,
            column,
            symbol_name,
            max_depth,
            include_non_workspace,
        )
        if "error" in result:
            return CallsResult(error=str(result["error"]))
        return CallsResult(
            root=_dict_to_call_node(result) if "name" in result else None
        )
    elif mode == "incoming":
        if params.to_path is None or params.to_line is None or params.to_column is None:
            return CallsResult(
                error="to_path, to_line, and to_column are required for incoming mode"
            )
        path = Path(params.to_path).resolve()
        line = params.to_line
        column = params.to_column
        symbol_name = params.to_symbol or ""
        result = await _get_incoming_calls_tree(
            ctx,
            workspace_root,
            path,
            line,
            column,
            symbol_name,
            max_depth,
            include_non_workspace,
        )
        if "error" in result:
            return CallsResult(error=str(result["error"]))
        return CallsResult(
            root=_dict_to_call_node(result) if "name" in result else None
        )
    else:
        if (
            params.from_path is None
            or params.from_line is None
            or params.from_column is None
            or params.to_path is None
            or params.to_line is None
            or params.to_column is None
        ):
            return CallsResult(
                error="from_path, from_line, from_column, to_path, to_line, and to_column are required for path mode"
            )
        from_path = Path(params.from_path).resolve()
        from_line = params.from_line
        from_column = params.from_column
        from_symbol = params.from_symbol or ""
        to_path = Path(params.to_path).resolve()
        to_line = params.to_line
        to_column = params.to_column
        to_symbol = params.to_symbol or ""
        result = await _find_call_path(
            ctx,
            workspace_root,
            from_path,
            from_line,
            from_column,
            from_symbol,
            to_path,
            to_line,
            to_column,
            to_symbol,
            max_depth,
            include_non_workspace,
        )
        if result.get("found"):
            path_items = result.get("path")
            if path_items:
                return CallsResult(
                    path=[_dict_to_call_node(item) for item in path_items]
                )
        return CallsResult(
            message=str(result.get("message")) if result.get("message") else None
        )


def _dict_to_call_node(d: FormattedCallItemWithCalls) -> CallNode:
    calls = None
    called_by = None
    calls_list = d.get("calls")
    called_by_list = d.get("called_by")
    if calls_list is not None:
        calls = [_dict_to_call_node(c) for c in calls_list]
    if called_by_list is not None:
        called_by = [_dict_to_call_node(c) for c in called_by_list]
    return CallNode(
        name=d["name"],
        kind=d["kind"],
        detail=d["detail"],
        path=d["path"],
        line=d["line"],
        column=d["column"],
        calls=calls,
        called_by=called_by,
    )


async def _prepare_call_hierarchy(
    workspace: "Workspace",
    path: Path,
    line: int,
    column: int,
) -> CallHierarchyItem | None:
    doc = await workspace.ensure_document_open(path)
    assert workspace.client is not None

    try:
        result = await workspace.client.send_request(
            "textDocument/prepareCallHierarchy",
            TextDocumentPositionParams(
                textDocument=TextDocumentIdentifier(uri=doc.uri),
                position=Position(line=line - 1, character=column),
            ),
        )
    except LSPResponseError as e:
        if e.is_method_not_found():
            raise LSPMethodNotSupported(
                "textDocument/prepareCallHierarchy", workspace.server_config.name
            )
        raise

    if not result:
        return None
    return result[0]


def _is_path_in_workspace(uri: str, workspace_root: Path) -> bool:
    file_path = uri_to_path(uri)
    try:
        rel_path = file_path.relative_to(workspace_root)
        excluded_dirs = {
            ".venv",
            "venv",
            "node_modules",
            "vendor",
            ".git",
            "__pycache__",
            "target",
            "build",
            "dist",
        }
        if any(part in excluded_dirs for part in rel_path.parts):
            return False
        return True
    except ValueError:
        return False


def _format_call_hierarchy_item(
    item: CallHierarchyItem, workspace_root: Path, ctx: HandlerContext
) -> FormattedCallItemWithCalls:
    file_path = uri_to_path(item.uri)
    sel_range = item.selectionRange
    return FormattedCallItemWithCalls(
        name=item.name,
        kind=SymbolKind(item.kind).name,
        detail=item.detail,
        path=ctx.relative_path(file_path, workspace_root),
        line=sel_range.start.line + 1,
        column=sel_range.start.character,
    )


class CallTreeError(TypedDict):
    error: str


class CallTreeSuccess(FormattedCallItemWithCalls):
    pass


CallTreeResult = CallTreeError | CallTreeSuccess


async def _get_outgoing_calls_tree(
    ctx: HandlerContext,
    workspace_root: Path,
    path: Path,
    line: int,
    column: int,
    symbol_name: str,
    max_depth: int,
    include_non_workspace: bool = False,
) -> CallTreeResult:
    workspace = await ctx.session.get_or_create_workspace(path, workspace_root)
    if not workspace or not workspace.client:
        raise ValueError(f"No language server available for {path}")

    await workspace.client.wait_for_service_ready()
    await workspace.client.wait_for_indexing()

    item = await _prepare_call_hierarchy(workspace, path, line, column)
    if not item:
        rel_path = ctx.relative_path(path, workspace_root)
        return CallTreeError(
            error=f"No callable symbol found at {rel_path}:{line}:{column} for '{symbol_name}'. "
            + "The symbol may not be a function/method, or the position may be incorrect."
        )

    formatted = _format_call_hierarchy_item(item, workspace_root, ctx)
    root: CallTreeSuccess = CallTreeSuccess(
        name=formatted["name"],
        kind=formatted["kind"],
        detail=formatted["detail"],
        path=formatted["path"],
        line=formatted["line"],
        column=formatted["column"],
    )
    root["calls"] = await _expand_outgoing_calls(
        ctx,
        workspace,
        workspace_root,
        item,
        max_depth,
        set(),
        include_non_workspace,
        is_root=True,
    )
    return root


async def _expand_outgoing_calls(
    ctx: HandlerContext,
    workspace: "Workspace",
    workspace_root: Path,
    item: CallHierarchyItem,
    depth: int,
    visited: set[tuple[str, int]],
    include_non_workspace: bool = False,
    is_root: bool = False,
) -> list[FormattedCallItemWithCalls]:
    if depth <= 0:
        return []

    item_key = (item.uri, item.selectionRange.start.line)
    if item_key in visited:
        return []
    visited.add(item_key)

    assert workspace.client is not None

    try:
        result = await workspace.client.send_request(
            "callHierarchy/outgoingCalls",
            CallHierarchyItemParams(item=item),
        )
    except LSPResponseError as e:
        if e.is_method_not_found():
            if is_root:
                raise LSPMethodNotSupported(
                    "callHierarchy/outgoingCalls", workspace.server_config.name
                )
            return []
        raise

    if not result:
        return []

    calls: list[FormattedCallItemWithCalls] = []
    for call in result:
        to_item = call.to

        if not include_non_workspace and not _is_path_in_workspace(
            to_item.uri, workspace_root
        ):
            continue

        call_info = _format_call_hierarchy_item(to_item, workspace_root, ctx)
        call_info["from_ranges"] = [
            {"line": r.start.line + 1, "column": r.start.character}
            for r in call.fromRanges
        ]
        call_info["calls"] = await _expand_outgoing_calls(
            ctx,
            workspace,
            workspace_root,
            to_item,
            depth - 1,
            visited,
            include_non_workspace,
        )
        calls.append(call_info)

    return calls


async def _get_incoming_calls_tree(
    ctx: HandlerContext,
    workspace_root: Path,
    path: Path,
    line: int,
    column: int,
    symbol_name: str,
    max_depth: int,
    include_non_workspace: bool = False,
) -> CallTreeResult:
    workspace = await ctx.session.get_or_create_workspace(path, workspace_root)
    if not workspace or not workspace.client:
        raise ValueError(f"No language server available for {path}")

    await workspace.client.wait_for_service_ready()

    item = await _prepare_call_hierarchy(workspace, path, line, column)
    if not item:
        rel_path = ctx.relative_path(path, workspace_root)
        return CallTreeError(
            error=f"No callable symbol found at {rel_path}:{line}:{column} for '{symbol_name}'. "
            + "The symbol may not be a function/method, or the position may be incorrect."
        )

    formatted = _format_call_hierarchy_item(item, workspace_root, ctx)
    root: CallTreeSuccess = CallTreeSuccess(
        name=formatted["name"],
        kind=formatted["kind"],
        detail=formatted["detail"],
        path=formatted["path"],
        line=formatted["line"],
        column=formatted["column"],
    )
    root["called_by"] = await _expand_incoming_calls(
        ctx,
        workspace,
        workspace_root,
        item,
        max_depth,
        set(),
        include_non_workspace,
        is_root=True,
    )
    return root


async def _expand_incoming_calls(
    ctx: HandlerContext,
    workspace: "Workspace",
    workspace_root: Path,
    item: CallHierarchyItem,
    depth: int,
    visited: set[tuple[str, int]],
    include_non_workspace: bool = False,
    is_root: bool = False,
) -> list[FormattedCallItemWithCalls]:
    if depth <= 0:
        return []

    item_key = (item.uri, item.selectionRange.start.line)
    if item_key in visited:
        return []
    visited.add(item_key)

    assert workspace.client is not None

    try:
        result = await workspace.client.send_request(
            "callHierarchy/incomingCalls",
            CallHierarchyItemParams(item=item),
        )
    except LSPResponseError as e:
        if e.is_method_not_found():
            if is_root:
                raise LSPMethodNotSupported(
                    "callHierarchy/incomingCalls", workspace.server_config.name
                )
            return []
        raise

    if not result:
        return []

    callers: list[FormattedCallItemWithCalls] = []
    for call in result:
        from_item = call.from_

        if not include_non_workspace and not _is_path_in_workspace(
            from_item.uri, workspace_root
        ):
            continue

        caller_info = _format_call_hierarchy_item(from_item, workspace_root, ctx)
        caller_info["call_sites"] = [
            {"line": r.start.line + 1, "column": r.start.character}
            for r in call.fromRanges
        ]
        caller_info["called_by"] = await _expand_incoming_calls(
            ctx,
            workspace,
            workspace_root,
            from_item,
            depth - 1,
            visited,
            include_non_workspace,
        )
        callers.append(caller_info)

    return callers


class CallPathResult(TypedDict, total=False):
    found: bool
    path: list[FormattedCallItemWithCalls]
    from_: FormattedCallItemWithCalls
    to: FormattedCallItemWithCalls
    message: str
    error: str


async def _find_call_path(
    ctx: HandlerContext,
    workspace_root: Path,
    from_path: Path,
    from_line: int,
    from_column: int,
    from_symbol: str,
    to_path: Path,
    to_line: int,
    to_column: int,
    to_symbol: str,
    max_depth: int,
    include_non_workspace: bool = False,
) -> CallPathResult:
    workspace = await ctx.session.get_or_create_workspace(from_path, workspace_root)
    if not workspace or not workspace.client:
        raise ValueError(f"No language server available for {from_path}")

    await workspace.client.wait_for_service_ready()

    from_item = await _prepare_call_hierarchy(
        workspace, from_path, from_line, from_column
    )
    if not from_item:
        rel_path = ctx.relative_path(from_path, workspace_root)
        return CallPathResult(
            error=f"No callable symbol found at {rel_path}:{from_line}:{from_column} for '{from_symbol}'. "
            + "The symbol may not be a function/method, or the position may be incorrect."
        )

    to_item = await _prepare_call_hierarchy(workspace, to_path, to_line, to_column)
    if not to_item:
        rel_path = ctx.relative_path(to_path, workspace_root)
        return CallPathResult(
            error=f"No callable symbol found at {rel_path}:{to_line}:{to_column} for '{to_symbol}'. "
            + "The symbol may not be a function/method, or the position may be incorrect."
        )

    to_key = (to_item.uri, to_item.selectionRange.start.line)

    path = await _bfs_call_path(
        workspace, workspace_root, from_item, to_key, max_depth, include_non_workspace
    )

    if not path:
        return CallPathResult(
            found=False,
            from_=_format_call_hierarchy_item(from_item, workspace_root, ctx),
            to=_format_call_hierarchy_item(to_item, workspace_root, ctx),
            message=f"No call path found from '{from_symbol}' to '{to_symbol}' within depth {max_depth}",
        )

    return CallPathResult(
        found=True,
        path=[_format_call_hierarchy_item(item, workspace_root, ctx) for item in path],
    )


async def _bfs_call_path(
    workspace: "Workspace",
    workspace_root: Path,
    start_item: CallHierarchyItem,
    target_key: tuple[str, int],
    max_depth: int,
    include_non_workspace: bool = False,
) -> list[CallHierarchyItem] | None:
    queue: deque[tuple[CallHierarchyItem, list[CallHierarchyItem], int]] = deque(
        [(start_item, [start_item], 0)]
    )
    visited: set[tuple[str, int]] = set()
    start_key = (start_item.uri, start_item.selectionRange.start.line)
    visited.add(start_key)

    assert workspace.client is not None

    while queue:
        current_item, path, depth = queue.popleft()

        if depth >= max_depth:
            continue

        try:
            result = await workspace.client.send_request(
                "callHierarchy/outgoingCalls",
                CallHierarchyItemParams(item=current_item),
            )
        except LSPResponseError:
            continue

        if not result:
            continue

        for call in result:
            to_item = call.to

            if not include_non_workspace and not _is_path_in_workspace(
                to_item.uri, workspace_root
            ):
                continue

            item_key = (to_item.uri, to_item.selectionRange.start.line)

            if item_key == target_key:
                return path + [to_item]

            if item_key not in visited:
                visited.add(item_key)
                queue.append((to_item, path + [to_item], depth + 1))

    return None
