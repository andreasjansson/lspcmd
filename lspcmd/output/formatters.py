import json
from pathlib import Path
from typing import Any


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
        if "warning" in data:
            return f"Warning: {data['warning']}"

        if "error" in data:
            # Handle ambiguous symbol errors with matches
            if "matches" in data:
                return format_ambiguous_symbol_error(data)
            return f"Error: {data['error']}"

        if "contents" in data:
            return data["contents"] or "No information available"

        if "formatted" in data:
            if data["formatted"]:
                return f"Formatted ({data.get('edits_applied', 0)} edits applied)"
            return "No formatting changes"

        if "organized" in data:
            return "Imports organized" if data["organized"] else data.get("error", "Failed to organize imports")

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
            return "Workspace restarted" if data["restarted"] else "Failed to restart workspace"

        if "status" in data:
            return data["status"]

        if "workspaces" in data:
            return format_session(data)

        if "content" in data and "path" in data:
            return format_definition_content(data)

        if "files" in data and "total_files" in data and "total_bytes" in data:
            return format_tree(data)

        if "files_modified" in data:
            files = data["files_modified"]
            return f"Modified {len(files)} file(s):\n" + "\n".join(f"  {f}" for f in files)

        if "command_executed" in data:
            return f"Executed command: {data['command_executed']}"

        return json.dumps(data, indent=2)

    if isinstance(data, list):
        if not data:
            return "No results"

        first = data[0]

        if "error" in first:
            return f"Error: {first['error']}"

        if "severity" in first and "message" in first:
            return format_diagnostics(data)

        if "path" in first and "line" in first and "kind" not in first:
            return format_locations(data)

        if "kind" in first:
            return format_symbols(data)

        if "title" in first:
            return format_code_actions(data)

        return "\n".join(format_plain(item) for item in data)

    return str(data)


def format_locations(locations: list[dict]) -> str:
    lines = []
    for loc in locations:
        path = loc["path"]
        line = loc["line"]

        if "context_lines" in loc:
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


def format_symbols(symbols: list[dict]) -> str:
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


def format_code_actions(actions: list[dict]) -> str:
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


def format_session(data: dict) -> str:
    lines = []
    
    daemon_pid = data.get("daemon_pid")
    if daemon_pid:
        lines.append(f"Daemon PID: {daemon_pid}")
    
    workspaces = data.get("workspaces", [])
    if not workspaces:
        lines.append("No active workspaces")
        return "\n".join(lines)

    lines.append("\nActive workspaces:")
    for ws in workspaces:
        status = "running" if ws.get("running") else "stopped"
        server_pid = ws.get("server_pid")
        pid_str = f", PID {server_pid}" if server_pid else ""
        
        lines.append(f"\n  {ws['root']}")
        lines.append(f"    Server: {ws['server']} ({status}{pid_str})")
        docs = ws.get("open_documents", [])
        if docs:
            lines.append(f"    Open documents ({len(docs)}):")
            for doc in docs[:5]:
                lines.append(f"      {doc}")
            if len(docs) > 5:
                lines.append(f"      ... and {len(docs) - 5} more")

    return "\n".join(lines)


def format_definition_content(data: dict) -> str:
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
        lines.append(f"[truncated after {head} lines, use `lspcmd show \"{symbol}\" --head {total_lines}` to show the full {total_lines} lines]")
    
    return "\n".join(lines)


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    else:
        return f"{size / (1024 * 1024):.1f}MB"


def format_tree(data: dict) -> str:
    from pathlib import Path as P
    
    files = data["files"]
    total_files = data["total_files"]
    total_bytes = data["total_bytes"]
    
    if not files:
        return "0 files, 0B"
    
    tree: dict = {}
    for rel_path, info in files.items():
        parts = P(rel_path).parts
        current = tree
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = info
    
    lines: list[str] = []
    
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
                size_str = format_size(child["size"])
                lines.append(f"{prefix}{connector}{name} ({size_str})")
            else:
                lines.append(f"{prefix}{connector}{name}")
                render_tree(child, new_prefix, is_root=False)
    
    render_tree(tree)
    lines.append("")
    lines.append(f"{total_files} files, {format_size(total_bytes)}")
    
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


def format_diagnostics(diagnostics: list[dict]) -> str:
    severity_symbols = {
        "error": "✗",
        "warning": "⚠",
        "info": "ℹ",
        "hint": "💡",
    }
    
    lines = []
    for diag in diagnostics:
        path = diag.get("path", "")
        line = diag.get("line", 0)
        column = diag.get("column", 0)
        severity = diag.get("severity", "error")
        message = diag.get("message", "")
        code = diag.get("code")
        source = diag.get("source")
        
        symbol = severity_symbols.get(severity, "?")
        location = f"{path}:{line}:{column}"
        
        # Build the diagnostic line
        parts = [location, symbol, severity]
        if source:
            parts.append(f"[{source}]")
        if code:
            parts.append(f"({code})")
        
        header = " ".join(parts)
        
        # Handle multi-line messages
        message_lines = message.split("\n")
        lines.append(f"{header}: {message_lines[0]}")
        for extra_line in message_lines[1:]:
            lines.append(f"  {extra_line}")
    
    return "\n".join(lines)
