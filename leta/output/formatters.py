import json
from functools import singledispatch
from pathlib import Path

from pydantic import BaseModel

from ..daemon.rpc import (
    CallNode,
    CallsResult,
    CacheInfo,
    DeclarationResult,
    DescribeSessionResult,
    FileInfo,
    FilesResult,
    GrepResult,
    ImplementationsResult,
    LocationInfo,
    MoveFileResult,
    ReferencesResult,
    RemoveWorkspaceResult,
    RenameResult,
    ResolveSymbolResult,
    RestartWorkspaceResult,
    ShowResult,
    SubtypesResult,
    SupertypesResult,
    SymbolInfo,
    WorkspaceInfo,
)


def format_result(result: BaseModel, output_format: str = "plain") -> str:
    if output_format == "json":
        return json.dumps(result.model_dump(exclude_none=True), indent=2)
    return format_model(result)


def format_output(data: object, output_format: str = "plain") -> str:
    """Legacy format function for backwards compatibility with tests.
    
    Handles both Pydantic models and raw dicts/lists.
    New code should use format_result with typed models instead.
    """
    if output_format == "json":
        if isinstance(data, BaseModel):
            return json.dumps(data.model_dump(exclude_none=True), indent=2)
        return json.dumps(data, indent=2)
    
    if isinstance(data, BaseModel):
        return format_model(data)
    
    if data is None:
        return ""
    
    if isinstance(data, str):
        return data
    
    if isinstance(data, dict):
        return _format_dict_legacy(data)
    
    if isinstance(data, list):
        return _format_list_legacy(data)
    
    return str(data)


def _format_dict_legacy(data: dict[str, object]) -> str:
    """Format a dict using legacy duck-typing logic."""
    if "error" in data and data["error"]:
        if "matches" in data:
            return _format_ambiguous_error_legacy(data)
        return f"Error: {data['error']}"
    
    symbols_list = data.get("symbols")
    if isinstance(symbols_list, list):
        if data.get("warning"):
            return f"Warning: {data['warning']}"
        symbols = [SymbolInfo.model_validate(s) for s in symbols_list]
        return _format_symbols(symbols)
    
    locations_list = data.get("locations")
    if isinstance(locations_list, list):
        locations = [LocationInfo.model_validate(loc) for loc in locations_list]
        return _format_locations(locations)
    
    if "warning" in data:
        return f"Warning: {data['warning']}"
    
    if "files_changed" in data and "imports_updated" not in data:
        files = data["files_changed"]
        if isinstance(files, list):
            return f"Renamed in {len(files)} file(s):\n" + "\n".join(f"  {f}" for f in files)
    
    if "files_changed" in data and "imports_updated" in data:
        files = data["files_changed"]
        imports_updated = data["imports_updated"]
        if isinstance(files, list):
            if imports_updated:
                return f"Moved file and updated imports in {len(files)} file(s):\n" + "\n".join(f"  {f}" for f in files)
            return f"Moved file (imports not updated):\n  {files[0]}" if files else "File moved"
    
    if "restarted" in data:
        restarted = data["restarted"]
        if isinstance(restarted, list):
            return f"Restarted {len(restarted)} server(s): {', '.join(str(s) for s in restarted)}"
    
    if "content" in data and "path" in data:
        result = ShowResult.model_validate(data)
        return format_model(result)
    
    if "files" in data and "total_files" in data and "total_bytes" in data:
        result = FilesResult.model_validate(data)
        return format_model(result)
    
    if "root" in data and data["root"]:
        root = CallNode.model_validate(data["root"])
        return _format_call_tree(root)
    
    if "calls" in data or "called_by" in data:
        node = CallNode.model_validate(data)
        return _format_call_tree(node)
    
    path_list = data.get("path")
    if isinstance(path_list, list) and path_list:
        nodes = [CallNode.model_validate(n) for n in path_list]
        return _format_call_path(nodes)
    
    if "message" in data and data["message"]:
        return str(data["message"])
    
    if "workspaces" in data:
        result = DescribeSessionResult.model_validate(data)
        return format_model(result)
    
    return json.dumps(data, indent=2)


def _format_list_legacy(data: list[object]) -> str:
    """Format a list using legacy duck-typing logic."""
    if not data:
        return ""
    
    first = data[0]
    if not isinstance(first, dict):
        return "\n".join(str(item) for item in data)
    
    if "error" in first:
        return f"Error: {first['error']}"
    
    if "path" in first and "line" in first and "kind" not in first:
        locations = [LocationInfo.model_validate(loc) for loc in data]
        return _format_locations(locations)
    
    if "kind" in first:
        symbols = [SymbolInfo.model_validate(s) for s in data]
        return _format_symbols(symbols)
    
    return "\n".join(format_output(item, "plain") for item in data)


def _format_ambiguous_error_legacy(data: dict[str, object]) -> str:
    """Format an ambiguous symbol error with match details."""
    lines = [f"Error: {data['error']}"]
    matches = data.get("matches", [])
    
    if isinstance(matches, list):
        for m in matches:
            if isinstance(m, dict):
                container = f" in {m['container']}" if m.get("container") else ""
                kind = f"[{m['kind']}] " if m.get("kind") else ""
                detail = f" ({m['detail']})" if m.get("detail") else ""
                ref = m.get("ref", "")
                lines.append(f"  {ref}")
                lines.append(f"    {m['path']}:{m['line']} {kind}{m['name']}{detail}{container}")
    
    total = data.get("total_matches")
    if isinstance(total, int) and isinstance(matches, list) and total > len(matches):
        lines.append(f"  ... and {total - len(matches)} more")
    
    return "\n".join(lines)


# Export aliases for backwards compatibility with tests
def format_code_actions(actions: list[dict[str, object]]) -> str:
    """Format code actions for display."""
    lines: list[str] = []
    for action in actions:
        title = action.get("title", "")
        kind = action.get("kind", "")
        preferred = " [preferred]" if action.get("is_preferred") else ""
        if kind:
            lines.append(f"[{kind}] {title}{preferred}")
        else:
            lines.append(f"{title}{preferred}")
    return "\n".join(lines)


def format_locations(locations: list[LocationInfo] | list[dict[str, object]]) -> str:
    typed_locations = [
        loc if isinstance(loc, LocationInfo) else LocationInfo.model_validate(loc)
        for loc in locations
    ]
    return _format_locations(typed_locations)


def format_symbols(symbols: list[SymbolInfo] | list[dict[str, object]]) -> str:
    typed_symbols = [
        sym if isinstance(sym, SymbolInfo) else SymbolInfo.model_validate(sym)
        for sym in symbols
    ]
    return _format_symbols(typed_symbols)


def format_session(result: DescribeSessionResult | dict[str, object]) -> str:
    if isinstance(result, dict):
        # Add defaults for missing optional fields for test compatibility
        if "caches" not in result:
            result = {**result, "caches": {}}
        result = DescribeSessionResult.model_validate(result)
    return _format_session(result)


def format_tree(result: FilesResult | dict[str, object]) -> str:
    if isinstance(result, dict):
        result = FilesResult.model_validate(result)
    return _format_tree(result)


def format_call_tree(node: CallNode | dict[str, object]) -> str:
    if isinstance(node, dict):
        node = CallNode.model_validate(node)
    return _format_call_tree(node)


def format_call_path(path: list[CallNode] | list[dict[str, object]]) -> str:
    typed_path = [
        node if isinstance(node, CallNode) else CallNode.model_validate(node)
        for node in path
    ]
    return _format_call_path(typed_path)


@singledispatch
def format_model(result: BaseModel) -> str:
    return json.dumps(result.model_dump(exclude_none=True), indent=2)


@format_model.register
def _(result: GrepResult) -> str:
    if result.warning:
        return f"Warning: {result.warning}"
    return _format_symbols(result.symbols)


@format_model.register
def _(result: ReferencesResult) -> str:
    return _format_locations(result.locations)


@format_model.register
def _(result: DeclarationResult) -> str:
    return _format_locations(result.locations)


@format_model.register
def _(result: ImplementationsResult) -> str:
    if result.error:
        return f"Error: {result.error}"
    return _format_locations(result.locations)


@format_model.register
def _(result: SubtypesResult) -> str:
    return _format_locations(result.locations)


@format_model.register
def _(result: SupertypesResult) -> str:
    return _format_locations(result.locations)


@format_model.register
def _(result: ShowResult) -> str:
    start = result.start_line
    end = result.end_line
    if start == end:
        location = f"{result.path}:{start}"
    else:
        location = f"{result.path}:{start}-{end}"

    lines = [location, "", result.content]

    if result.truncated:
        head = 200
        total_lines = result.total_lines or head
        symbol = result.symbol or "SYMBOL"
        lines.append("")
        lines.append(
            f'[truncated after {head} lines, use `leta show "{symbol}" --head {total_lines}` to show the full {total_lines} lines]'
        )

    return "\n".join(lines)


@format_model.register
def _(result: RenameResult) -> str:
    files = result.files_changed
    return f"Renamed in {len(files)} file(s):\n" + "\n".join(f"  {f}" for f in files)


@format_model.register
def _(result: MoveFileResult) -> str:
    files = result.files_changed
    if result.imports_updated:
        return f"Moved file and updated imports in {len(files)} file(s):\n" + "\n".join(
            f"  {f}" for f in files
        )
    else:
        return (
            f"Moved file (imports not updated):\n  {files[0]}"
            if files
            else "File moved"
        )


@format_model.register
def _(result: RestartWorkspaceResult) -> str:
    servers = result.restarted
    return f"Restarted {len(servers)} server(s): {', '.join(servers)}"


@format_model.register
def _(result: RemoveWorkspaceResult) -> str:
    servers = result.servers_stopped
    return f"Stopped {len(servers)} server(s): {', '.join(servers)}"


@format_model.register
def _(result: FilesResult) -> str:
    return _format_tree(result)


@format_model.register
def _(result: CallsResult) -> str:
    if result.error:
        return f"Error: {result.error}"
    if result.message:
        return result.message
    if result.root:
        return _format_call_tree(result.root)
    if result.path:
        return _format_call_path(result.path)
    return ""


@format_model.register
def _(result: DescribeSessionResult) -> str:
    return _format_session(result)


@format_model.register
def _(result: ResolveSymbolResult) -> str:
    if result.error:
        lines = [f"Error: {result.error}"]
        if result.matches:
            for m in result.matches:
                container = f" in {m.container}" if m.container else ""
                kind = f"[{m.kind}] " if m.kind else ""
                detail = f" ({m.detail})" if m.detail else ""
                ref = m.ref or ""
                lines.append(f"  {ref}")
                lines.append(f"    {m.path}:{m.line} {kind}{m.name}{detail}{container}")
            if result.total_matches and result.total_matches > len(result.matches):
                lines.append(f"  ... and {result.total_matches - len(result.matches)} more")
        return "\n".join(lines)
    return f"{result.path}:{result.line}"


def _format_locations(locations: list[LocationInfo]) -> str:
    lines: list[str] = []
    for loc in locations:
        if loc.name and loc.kind:
            parts = [f"{loc.path}:{loc.line}", f"[{loc.kind}]", loc.name]
            if loc.detail:
                parts.append(f"({loc.detail})")
            lines.append(" ".join(filter(None, parts)))
        elif loc.context_lines:
            context_start = loc.context_start or loc.line
            context_end = context_start + len(loc.context_lines) - 1
            lines.append(f"{loc.path}:{context_start}-{context_end}")
            for context_line in loc.context_lines:
                lines.append(context_line)
            lines.append("")
        else:
            line_content = _get_line_content(loc.path, loc.line)
            if line_content is not None:
                lines.append(f"{loc.path}:{loc.line} {line_content}")
            else:
                lines.append(f"{loc.path}:{loc.line}")

    return "\n".join(lines)


def _get_line_content(path: str, line: int) -> str | None:
    try:
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = Path.cwd() / file_path
        if not file_path.exists():
            return None
        content = file_path.read_text()
        file_lines = content.splitlines()
        if 0 < line <= len(file_lines):
            return file_lines[line - 1]
        return None
    except Exception:
        return None


def _format_symbols(symbols: list[SymbolInfo]) -> str:
    lines: list[str] = []
    for sym in symbols:
        location = f"{sym.path}:{sym.line}" if sym.path else ""

        parts = [location, f"[{sym.kind}]", sym.name]
        if sym.detail:
            parts.append(f"({sym.detail})")
        if sym.container:
            parts.append(f"in {sym.container}")

        lines.append(" ".join(filter(None, parts)))

        if sym.documentation:
            doc_lines = sym.documentation.strip().split("\n")
            for doc_line in doc_lines:
                lines.append(f"    {doc_line}")
            lines.append("")

    return "\n".join(lines)


def _format_session(result: DescribeSessionResult) -> str:
    lines: list[str] = []

    lines.append(f"Daemon PID: {result.daemon_pid}")

    if result.caches:
        lines.append("\nCaches:")
        hover = result.caches.get("hover_cache")
        symbol = result.caches.get("symbol_cache")
        if hover:
            lines.append(
                f"  Hover:  {_format_size(hover.current_bytes)} / {_format_size(hover.max_bytes)} "
                f"({hover.entries} entries)"
            )
        if symbol:
            lines.append(
                f"  Symbol: {_format_size(symbol.current_bytes)} / {_format_size(symbol.max_bytes)} "
                f"({symbol.entries} entries)"
            )

    if not result.workspaces:
        lines.append("\nNo active workspaces")
        return "\n".join(lines)

    lines.append("\nActive workspaces:")
    for ws in result.workspaces:
        status = "running" if ws.server_pid else "stopped"
        pid_str = f", PID {ws.server_pid}" if ws.server_pid else ""

        lines.append(f"\n  {ws.root}")
        lines.append(f"    Server: {ws.language} ({status}{pid_str})")
        if ws.open_documents:
            lines.append(f"    Open documents ({len(ws.open_documents)}):")
            for doc in ws.open_documents[:5]:
                lines.append(f"      {doc}")
            if len(ws.open_documents) > 5:
                lines.append(f"      ... and {len(ws.open_documents) - 5} more")

    return "\n".join(lines)


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    else:
        return f"{size / (1024 * 1024):.1f}MB"


def _format_tree(result: FilesResult) -> str:
    if not result.files:
        return "0 files, 0B"

    tree: dict[str, object] = {}

    for rel_path, info in result.files.items():
        parts = Path(rel_path).parts
        current = tree
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            next_node = current[part]
            if isinstance(next_node, dict):
                current = next_node
        current[parts[-1]] = info

    lines: list[str] = []

    def format_file_info(info: FileInfo) -> str:
        parts = [_format_size(info.bytes)]
        parts.append(f"{info.lines} lines")

        if info.symbols:
            symbol_order = ["class", "struct", "interface", "enum", "function", "method"]
            symbol_parts = []
            for kind in symbol_order:
                count = info.symbols.get(kind, 0)
                if count > 0:
                    label = (
                        kind
                        if count == 1
                        else (kind + "es" if kind == "class" else kind + "s")
                    )
                    symbol_parts.append(f"{count} {label}")
            if symbol_parts:
                parts.extend(symbol_parts)

        return ", ".join(parts)

    def render_tree(node: dict[str, object], prefix: str = "", is_root: bool = True) -> None:
        entries = sorted(
            node.keys(),
            key=lambda k: (isinstance(node[k], dict), k),
        )
        for i, name in enumerate(entries):
            is_last = i == len(entries) - 1
            child = node[name]

            if is_root:
                connector = ""
                new_prefix = ""
            else:
                connector = "└── " if is_last else "├── "
                new_prefix = prefix + ("    " if is_last else "│   ")

            if isinstance(child, FileInfo):
                info_str = format_file_info(child)
                lines.append(f"{prefix}{connector}{name} ({info_str})")
            elif isinstance(child, dict):
                lines.append(f"{prefix}{connector}{name}")
                render_tree(child, new_prefix, is_root=False)

    render_tree(tree)
    lines.append("")
    lines.append(
        f"{result.total_files} files, {_format_size(result.total_bytes)}, {result.total_lines} lines"
    )

    return "\n".join(lines)


def _is_stdlib_path(path: str) -> bool:
    if "/typeshed-fallback/stdlib/" in path or "/typeshed/stdlib/" in path:
        return True
    if "/libexec/src/" in path and "/mod/" not in path:
        return True
    if path.endswith(".d.ts"):
        filename = path.split("/")[-1]
        if filename.startswith("lib."):
            return True
    if "/rustlib/src/rust/library/" in path:
        return True
    return False


def _format_call_tree(node: CallNode) -> str:
    lines: list[str] = []

    parts = [f"{node.path}:{node.line}" if node.path else "", f"[{node.kind}]" if node.kind else "", node.name]
    if node.detail:
        parts.append(f"({node.detail})")
    lines.append(" ".join(filter(None, parts)))

    if node.calls is not None:
        lines.append("")
        lines.append("Outgoing calls:")
        if node.calls:
            _render_calls_tree(node.calls, lines, "  ", is_outgoing=True)
    elif node.called_by is not None:
        lines.append("")
        lines.append("Incoming calls:")
        if node.called_by:
            _render_calls_tree(node.called_by, lines, "  ", is_outgoing=False)

    return "\n".join(lines)


def _render_calls_tree(
    items: list[CallNode], lines: list[str], prefix: str, is_outgoing: bool
) -> None:
    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        path = item.path or ""
        line = item.line or 0

        if _is_stdlib_path(path):
            parts = [f"[{item.kind}]" if item.kind else "", item.name]
        else:
            parts = [f"{path}:{line}", f"[{item.kind}]" if item.kind else "", item.name]
        if item.detail:
            parts.append(f"({item.detail})")
        lines.append(f"{prefix}{connector}" + " ".join(filter(None, parts)))

        children = item.calls if is_outgoing else item.called_by
        if children:
            _render_calls_tree(children, lines, child_prefix, is_outgoing)


def _format_call_path(path: list[CallNode]) -> str:
    if not path:
        return "Empty path"

    lines = ["Call path:"]
    for i, item in enumerate(path):
        file_path = item.path or ""
        line = item.line or 0

        parts = [f"{file_path}:{line}", f"[{item.kind}]" if item.kind else "", item.name]
        if item.detail:
            parts.append(f"({item.detail})")

        arrow = "" if i == 0 else "  → "
        lines.append(f"{arrow}" + " ".join(filter(None, parts)))

    return "\n".join(lines)
