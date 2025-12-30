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
        if "error" in data:
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

        if "restarted" in data:
            return "Workspace restarted" if data["restarted"] else "Failed to restart workspace"

        if "status" in data:
            return data["status"]

        if "workspaces" in data:
            return format_session(data)

        if "content" in data and "path" in data:
            return format_definition_content(data)

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
        col = loc.get("column", 0)

        if "context_lines" in loc:
            lines.append(f"{path}:{line}:{col}")
            context_start = loc.get("context_start", line)
            for i, context_line in enumerate(loc["context_lines"]):
                line_num = context_start + i
                marker = ">" if line_num == line else " "
                lines.append(f"{marker} {line_num:4d} | {context_line}")
            lines.append("")
        else:
            line_content = _get_line_content(path, line)
            if line_content is not None:
                lines.append(f"{path}:{line}:{col}: {line_content}")
            else:
                lines.append(f"{path}:{line}:{col}")

    return "\n".join(lines)


def _get_line_content(path: str, line: int) -> str | None:
    from pathlib import Path
    try:
        file_path = Path(path)
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
    workspaces = data.get("workspaces", [])
    if not workspaces:
        return "No active workspaces"

    lines = ["Active workspaces:"]
    for ws in workspaces:
        status = "running" if ws.get("running") else "stopped"
        lines.append(f"\n  {ws['root']}")
        lines.append(f"    Server: {ws['server']} ({status})")
        docs = ws.get("open_documents", [])
        if docs:
            lines.append(f"    Open documents ({len(docs)}):")
            for doc in docs[:5]:
                lines.append(f"      {doc}")
            if len(docs) > 5:
                lines.append(f"      ... and {len(docs) - 5} more")

    return "\n".join(lines)


def format_definition_content(data: dict) -> str:
    lines = [
        f"{data['path']}:{data['start_line']}-{data['end_line']}",
        "",
        data["content"],
    ]
    return "\n".join(lines)
