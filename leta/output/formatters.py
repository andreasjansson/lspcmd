import json
from pathlib import Path
from typing import Any, TypedDict


class LocationDict(TypedDict, total=False):
    path: str
    line: int
    column: int
    context_lines: list[str]
    context_start: int
    name: str
    kind: str
    detail: str


class SymbolDict(TypedDict, total=False):
    name: str
    kind: str
    path: str
    line: int
    column: int
    container: str
    detail: str
    documentation: str


class FileInfoDict(TypedDict, total=False):
    path: str
    lines: int
    bytes: int
    size: int
    symbols: dict[str, int]


class CallItemDict(TypedDict, total=False):
    name: str
    kind: str
    detail: str
    path: str
    line: int
    column: int
    calls: list["CallItemDict"]
    called_by: list["CallItemDict"]


def format_output(data: Any, output_format: str = "plain") -> str:
    if output_format == "json":
        return json.dumps(data, indent=2)
    return format_plain(data)


def format_plain(data: Any) -> str:
    if data is None:
        return ""

    if isinstance(data, str):
        return data

    if isinstance(data, dict):
        # Check error first - it can co-exist with other fields like locations
        if "error" in data and data["error"]:
            # Handle ambiguous symbol errors with matches
            if "matches" in data:
                return format_ambiguous_symbol_error(data)
            return f"Error: {data['error']}"

        # Handle new pydantic model structures - extract and format inner data
        if "symbols" in data and isinstance(data["symbols"], list):
            if data.get("warning"):
                return f"Warning: {data['warning']}"
            return format_symbols(data["symbols"])
        
        if "locations" in data and isinstance(data["locations"], list):
            return format_locations(data["locations"])

        if "warning" in data:
            return f"Warning: {data['warning']}"

        if "error" in data:
            # Handle ambiguous symbol errors with matches
            if "matches" in data:
                return format_ambiguous_symbol_error(data)
            return f"Error: {data['error']}"

        if "contents" in data:
            return data["contents"] or "No information available"

        # New format: files_changed (from pydantic models)
        if "files_changed" in data and "imports_updated" not in data:
            # RenameResult
            files = data["files_changed"]
            return f"Renamed in {len(files)} file(s):\n" + "\n".join(f"  {f}" for f in files)
        
        if "files_changed" in data and "imports_updated" in data:
            # MoveFileResult
            files = data["files_changed"]
            imports_updated = data["imports_updated"]
            if imports_updated:
                return f"Moved file and updated imports in {len(files)} file(s):\n" + "\n".join(f"  {f}" for f in files)
            else:
                return f"Moved file (imports not updated):\n  {files[0]}" if files else "File moved"

        # Old format: renamed/moved flags
        if "renamed" in data:
            if data["renamed"]:
                files = data.get("files_modified", [])
                return f"Renamed in {len(files)} file(s):\n" + "\n".join(f"  {f}" for f in files)
            return data.get("error", "Rename failed")

        if "moved" in data:
            if data["moved"]:
                files = data.get("files_modified", [])
                imports_updated = data.get("imports_updated", False)
                msg = data.get("message", "")
                if imports_updated:
                    return f"Moved file and updated imports in {len(files)} file(s):\n" + "\n".join(f"  {f}" for f in files)
                elif msg:
                    return msg
                else:
                    return f"Moved file (imports not updated):\n  {files[0]}" if files else "File moved"
            return data.get("error", "Move failed")

        if "replaced" in data:
            if data["replaced"]:
                path = data.get("path", "")
                old_range = data.get("old_range", "")
                new_range = data.get("new_range", "")
                return f"Replaced function in {path} (lines {old_range} -> {new_range})"
            return data.get("error", "Replace failed")

        if "old_signature" in data and "new_signature" in data:
            old_sig = data["old_signature"]
            new_sig = data["new_signature"]
            hint = data.get("hint", "")
            lines = [
                f"Error: {data.get('error', 'Signature mismatch')}",
                f"  Old: {old_sig}",
                f"  New: {new_sig}",
            ]
            if hint:
                lines.append(f"  Hint: {hint}")
            return "\n".join(lines)

        if "restarted" in data:
            # New format: list of server names
            if isinstance(data["restarted"], list):
                servers = data["restarted"]
                return f"Restarted {len(servers)} server(s): {', '.join(servers)}"
            # Old format: boolean
            return "Workspace restarted" if data["restarted"] else "Failed to restart workspace"

        if "status" in data:
            return data["status"]

        if "workspaces" in data:
            return format_session(data)

        if "content" in data and "path" in data:
            # Single line without body - format as location with content
            if data.get("start_line") == data.get("end_line") and "\n" not in data.get("content", ""):
                return f"{data['path']}:{data['start_line']} {data['content']}"
            return format_definition_content(data)

        if "files" in data and "total_files" in data and "total_bytes" in data:
            return format_tree(data)

        if "calls" in data or "called_by" in data:
            return format_call_tree(data)
        
        # New format: CallsResult with root
        if "root" in data and data["root"]:
            return format_call_tree(data["root"])
        
        # New format: CallsResult with path (call path result)
        if "path" in data and isinstance(data.get("path"), list):
            if data["path"]:
                return format_call_path({"found": True, "path": data["path"]})
        
        # CallsResult with message (path not found)
        if "message" in data and data["message"]:
            return data["message"]

        # Old format: found + path/from/to
        if "found" in data and ("path" in data or "from" in data):
            return format_call_path(data)

        if "files_modified" in data:
            files = data["files_modified"]
            return f"Modified {len(files)} file(s):\n" + "\n".join(f"  {f}" for f in files)

        if "command_executed" in data:
            return f"Executed command: {data['command_executed']}"

        return json.dumps(data, indent=2)

    if isinstance(data, list):
        if not data:
            return ""

        first = data[0]

        if "error" in first:
            return f"Error: {first['error']}"



        if "path" in first and "line" in first and "kind" not in first:
            return format_locations(data)

        if "kind" in first:
            return format_symbols(data)

        if "title" in first:
            return format_code_actions(data)

        return "\n".join(format_plain(item) for item in data)

    return str(data)


def format_locations(locations: list[LocationDict]) -> str:
    lines = []
    for loc in locations:
        path = loc["path"]
        line = loc["line"]

        # Check if this is a type hierarchy result with name/kind/detail
        if "name" in loc and "kind" in loc:
            name = loc["name"]
            kind = loc["kind"]
            detail = loc.get("detail", "")
            parts = [f"{path}:{line}", f"[{kind}]" if kind else "", name]
            if detail:
                parts.append(f"({detail})")
            lines.append(" ".join(filter(None, parts)))
        elif "context_lines" in loc:
            context_start = loc.get("context_start", line)
            context_end = context_start + len(loc["context_lines"]) - 1
            lines.append(f"{path}:{context_start}-{context_end}")
            for context_line in loc["context_lines"]:
                lines.append(context_line)
            lines.append("")
        else:
            line_content = _get_line_content(path, line)
            if line_content is not None:
                lines.append(f"{path}:{line} {line_content}")
            else:
                lines.append(f"{path}:{line}")

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


def format_symbols(symbols: list[SymbolDict]) -> str:
    lines = []
    for sym in symbols:
        path = sym.get("path", "")
        line = sym.get("line", 0)
        kind = sym.get("kind", "")
        name = sym.get("name", "")
        detail = sym.get("detail", "")
        container = sym.get("container", "")
        documentation = sym.get("documentation", "")

        location = f"{path}:{line}" if path else ""

        parts = [location, f"[{kind}]", name]
        if detail:
            parts.append(f"({detail})")
        if container:
            parts.append(f"in {container}")

        lines.append(" ".join(filter(None, parts)))
        
        if documentation:
            doc_lines = documentation.strip().split("\n")
            for doc_line in doc_lines:
                lines.append(f"    {doc_line}")
            lines.append("")

    return "\n".join(lines)


def format_code_actions(actions: list[dict[str, Any]]) -> str:
    lines = []
    for action in actions:
        title = action.get("title", "")
        kind = action.get("kind", "")
        preferred = " [preferred]" if action.get("is_preferred") else ""

        if kind:
            lines.append(f"[{kind}] {title}{preferred}")
        else:
            lines.append(f"{title}{preferred}")

    return "\n".join(lines)


def format_session(data: dict[str, Any]) -> str:
    lines = []
    
    daemon_pid = data.get("daemon_pid")
    if daemon_pid:
        lines.append(f"Daemon PID: {daemon_pid}")
    
    caches = data.get("caches", {})
    if caches:
        lines.append("\nCaches:")
        hover = caches.get("hover_cache", {})
        symbol = caches.get("symbol_cache", {})
        if hover:
            lines.append(
                f"  Hover:  {format_size(hover['current_bytes'])} / {format_size(hover['max_bytes'])} "
                f"({hover['entries']} entries)"
            )
        if symbol:
            lines.append(
                f"  Symbol: {format_size(symbol['current_bytes'])} / {format_size(symbol['max_bytes'])} "
                f"({symbol['entries']} entries)"
            )
    
    workspaces = data.get("workspaces", [])
    if not workspaces:
        lines.append("\nNo active workspaces")
        return "\n".join(lines)

    lines.append("\nActive workspaces:")
    for ws in workspaces:
        # Handle both old format (running/server) and new format (language/server_pid)
        if "language" in ws:
            server_name = ws["language"]
            server_pid = ws.get("server_pid")
            status = "running" if server_pid else "stopped"
        else:
            server_name = ws.get("server", "unknown")
            status = "running" if ws.get("running") else "stopped"
            server_pid = ws.get("server_pid")
        pid_str = f", PID {server_pid}" if server_pid else ""
        
        lines.append(f"\n  {ws['root']}")
        lines.append(f"    Server: {server_name} ({status}{pid_str})")
        docs = ws.get("open_documents", [])
        if docs:
            lines.append(f"    Open documents ({len(docs)}):")
            for doc in docs[:5]:
                lines.append(f"      {doc}")
            if len(docs) > 5:
                lines.append(f"      ... and {len(docs) - 5} more")

    return "\n".join(lines)


def format_definition_content(data: dict[str, Any]) -> str:
    start = data['start_line']
    end = data['end_line']
    if start == end:
        location = f"{data['path']}:{start}"
    else:
        location = f"{data['path']}:{start}-{end}"
    
    lines = [location, "", data["content"]]
    
    if data.get("truncated"):
        head = data.get("head", 200)
        total_lines = data.get("total_lines", head)
        symbol = data.get("symbol", "SYMBOL")
        lines.append("")
        lines.append(f"[truncated after {head} lines, use `leta show \"{symbol}\" --head {total_lines}` to show the full {total_lines} lines]")
    
    return "\n".join(lines)


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    else:
        return f"{size / (1024 * 1024):.1f}MB"


def format_tree(data: dict[str, Any]) -> str:
    from pathlib import Path as P
    
    files = data["files"]
    total_files = data["total_files"]
    total_bytes = data["total_bytes"]
    total_lines = data.get("total_lines", 0)
    
    if not files:
        return "0 files, 0B"
    
    tree: dict[str, Any] = {}
    for rel_path, info in files.items():
        # Handle both dict and FileInfo-like objects
        if hasattr(info, "model_dump"):
            info = info.model_dump()
        parts = P(rel_path).parts
        current = tree
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        # Normalize the info dict - new format uses "bytes" instead of "size"
        if "bytes" in info and "size" not in info:
            info = {**info, "size": info["bytes"]}
        current[parts[-1]] = info
    
    lines: list[str] = []
    
    def format_file_info(info: dict) -> str:
        parts = [format_size(info["size"])]
        
        if "lines" in info:
            parts.append(f"{info['lines']} lines")
        
        if "symbols" in info:
            symbol_order = ["class", "struct", "interface", "enum", "function", "method"]
            symbol_parts = []
            for kind in symbol_order:
                count = info["symbols"].get(kind, 0)
                if count > 0:
                    label = kind if count == 1 else (kind + "es" if kind == "class" else kind + "s")
                    symbol_parts.append(f"{count} {label}")
            if symbol_parts:
                parts.extend(symbol_parts)
        
        return ", ".join(parts)
    
    def render_tree(node: dict, prefix: str = "", is_root: bool = True) -> None:
        entries = sorted(node.keys(), key=lambda k: (isinstance(node[k], dict) and "size" not in node[k], k))
        for i, name in enumerate(entries):
            is_last = i == len(entries) - 1
            child = node[name]
            
            if is_root:
                connector = ""
                new_prefix = ""
            else:
                connector = "└── " if is_last else "├── "
                new_prefix = prefix + ("    " if is_last else "│   ")
            
            if isinstance(child, dict) and "size" in child:
                info_str = format_file_info(child)
                lines.append(f"{prefix}{connector}{name} ({info_str})")
            else:
                lines.append(f"{prefix}{connector}{name}")
                render_tree(child, new_prefix, is_root=False)
    
    render_tree(tree)
    lines.append("")
    lines.append(f"{total_files} files, {format_size(total_bytes)}, {total_lines} lines")
    
    return "\n".join(lines)


def format_ambiguous_symbol_error(data: dict) -> str:
    """Format an ambiguous symbol error with match details."""
    lines = [f"Error: {data['error']}"]
    matches = data.get("matches", [])
    
    for m in matches:
        container = f" in {m['container']}" if m.get("container") else ""
        kind = f"[{m['kind']}] " if m.get("kind") else ""
        detail = f" ({m['detail']})" if m.get("detail") else ""
        ref = m.get("ref", "")
        lines.append(f"  {ref}")
        lines.append(f"    {m['path']}:{m['line']} {kind}{m['name']}{detail}{container}")
    
    total = data.get("total_matches", len(matches))
    if total > len(matches):
        lines.append(f"  ... and {total - len(matches)} more")
    
    return "\n".join(lines)


def _is_stdlib_path(path: str) -> bool:
    """Detect if path is a language standard library (not third-party)."""
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


def format_call_tree(data: dict) -> str:
    lines = []

    name = data.get("name", "")
    kind = data.get("kind", "")
    detail = data.get("detail", "")
    path = data.get("path", "")
    line = data.get("line", 0)

    parts = [f"{path}:{line}", f"[{kind}]" if kind else "", name]
    if detail:
        parts.append(f"({detail})")
    lines.append(" ".join(filter(None, parts)))

    if "calls" in data:
        lines.append("")
        lines.append("Outgoing calls:")
        if data["calls"]:
            _render_calls_tree(data["calls"], lines, "  ", is_outgoing=True)
    elif "called_by" in data:
        lines.append("")
        lines.append("Incoming calls:")
        if data["called_by"]:
            _render_calls_tree(data["called_by"], lines, "  ", is_outgoing=False)

    return "\n".join(lines)


def _render_calls_tree(items: list[dict], lines: list[str], prefix: str, is_outgoing: bool) -> None:
    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        name = item.get("name", "")
        kind = item.get("kind", "")
        detail = item.get("detail", "")
        path = item.get("path", "")
        line = item.get("line", 0)

        if _is_stdlib_path(path):
            parts = [f"[{kind}]" if kind else "", name]
        else:
            parts = [f"{path}:{line}", f"[{kind}]" if kind else "", name]
        if detail:
            parts.append(f"({detail})")
        lines.append(f"{prefix}{connector}" + " ".join(filter(None, parts)))

        children_key = "calls" if is_outgoing else "called_by"
        children = item.get(children_key, [])
        if children:
            _render_calls_tree(children, lines, child_prefix, is_outgoing)


def format_call_path(data: dict) -> str:
    if not data.get("found"):
        return data.get("message", "No path found")

    path = data.get("path", [])
    if not path:
        return "Empty path"

    lines = ["Call path:"]
    for i, item in enumerate(path):
        name = item.get("name", "")
        kind = item.get("kind", "")
        detail = item.get("detail", "")
        file_path = item.get("path", "")
        line = item.get("line", 0)

        parts = [f"{file_path}:{line}", f"[{kind}]" if kind else "", name]
        if detail:
            parts.append(f"({detail})")

        if i == 0:
            arrow = ""
        else:
            arrow = "  → "

        lines.append(f"{arrow}" + " ".join(filter(None, parts)))

    return "\n".join(lines)
