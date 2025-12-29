import asyncio
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import click

from .daemon.pidfile import is_daemon_running
from .output.formatters import format_output
from .utils.config import (
    get_socket_path,
    get_pid_path,
    get_config_path,
    load_config,
    detect_workspace_root,
    get_known_workspace_root,
    add_workspace_root,
)


def ensure_daemon_running() -> None:
    pid_path = get_pid_path()

    if is_daemon_running(pid_path):
        return

    subprocess.Popen(
        [sys.executable, "-m", "lspcmd.daemon_cli"],
        start_new_session=True,
        env=os.environ.copy(),
    )

    socket_path = get_socket_path()
    for _ in range(50):
        if socket_path.exists():
            return
        time.sleep(0.1)

    raise click.ClickException("Failed to start daemon")


async def send_request(method: str, params: dict) -> dict:
    socket_path = get_socket_path()

    reader, writer = await asyncio.open_unix_connection(str(socket_path))

    request = {"method": method, "params": params}
    writer.write(json.dumps(request).encode())
    await writer.drain()
    writer.write_eof()

    data = await reader.read()
    writer.close()
    await writer.wait_closed()

    return json.loads(data.decode())


def run_request(method: str, params: dict) -> dict:
    ensure_daemon_running()
    return asyncio.run(send_request(method, params))


def get_workspace_root_for_path(path: Path, config: dict) -> Path:
    path = path.resolve()
    known_root = get_known_workspace_root(path, config)
    if known_root:
        return known_root

    detected_root = detect_workspace_root(path)
    if detected_root:
        known = get_known_workspace_root(detected_root, config)
        if known:
            return known

    raise click.ClickException(
        f"No workspace initialized for {path}\n"
        f"Run: lspcmd init-workspace"
    )


def get_workspace_root_for_cwd(config: dict) -> Path:
    cwd = Path.cwd().resolve()

    known_root = get_known_workspace_root(cwd, config)
    if known_root:
        return known_root

    detected_root = detect_workspace_root(cwd)
    if detected_root:
        known = get_known_workspace_root(detected_root, config)
        if known:
            return known

    raise click.ClickException(
        f"No workspace initialized for current directory\n"
        f"Run: lspcmd init-workspace"
    )


def parse_position(position: str) -> tuple[int, int]:
    parts = position.split(",")
    if len(parts) != 2:
        raise click.BadParameter("Position must be in LINE,COLUMN format")
    return int(parts[0]), int(parts[1])


def expand_path_pattern(pattern: str) -> list[Path]:
    """Expand a path pattern with glob wildcards (* and **) to matching files.
    
    Simple patterns without a directory (e.g. '*.go') are treated as recursive.
    """
    if "*" not in pattern and "?" not in pattern:
        path = Path(pattern).resolve()
        if not path.exists():
            raise click.ClickException(f"Path not found: {pattern}")
        return [path]
    
    # Make simple patterns like "*.go" recursive (search from current dir down)
    if "/" not in pattern and not pattern.startswith("**"):
        pattern = "**/" + pattern
    
    matches = glob.glob(pattern, recursive=True)
    if not matches:
        raise click.ClickException(f"No files match pattern: {pattern}")
    
    return [Path(m).resolve() for m in sorted(matches) if Path(m).is_file()]


def expand_exclude_pattern(pattern: str) -> set[Path]:
    """Expand an exclude pattern to a set of paths to exclude.
    
    Same logic as expand_path_pattern but returns a set and doesn't error on no matches.
    """
    if "*" not in pattern and "?" not in pattern:
        path = Path(pattern).resolve()
        return {path} if path.exists() else set()
    
    if "/" not in pattern and not pattern.startswith("**"):
        pattern = "**/" + pattern
    
    matches = glob.glob(pattern, recursive=True)
    return {Path(m).resolve() for m in matches if Path(m).is_file()}


@click.group()
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.pass_context
def cli(ctx, json_output):
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output


@cli.command("init-workspace")
@click.option("--root", type=click.Path(exists=True), help="Workspace root directory")
@click.pass_context
def init_workspace(ctx, root):
    """Initialize a workspace for LSP operations."""
    config = load_config()

    if root:
        workspace_root = Path(root).resolve()
    else:
        cwd = Path.cwd().resolve()
        detected = detect_workspace_root(cwd)

        if detected:
            default_root = detected
        else:
            default_root = cwd

        if sys.stdin.isatty():
            workspace_root = click.prompt(
                "Workspace root",
                default=str(default_root),
                type=click.Path(exists=True),
            )
            workspace_root = Path(workspace_root).resolve()
        else:
            workspace_root = default_root

    known = get_known_workspace_root(workspace_root, config)
    if known:
        click.echo(f"Workspace already initialized: {known}")
        return

    add_workspace_root(workspace_root, config)
    click.echo(f"Initialized workspace: {workspace_root}")


@cli.command()
@click.pass_context
def config(ctx):
    """Print config file location and contents."""
    config_path = get_config_path()
    click.echo(f"Config file: {config_path}")
    click.echo()

    if config_path.exists():
        click.echo(config_path.read_text())
    else:
        click.echo("(file does not exist, using defaults)")


@cli.command()
@click.pass_context
def shutdown(ctx):
    """Shutdown the lspcmd daemon."""
    if not is_daemon_running(get_pid_path()):
        click.echo("Daemon is not running")
        return

    response = run_request("shutdown", {})
    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("describe-session")
@click.pass_context
def describe_session(ctx):
    """Show current daemon state."""
    response = run_request("describe-session", {})
    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("describe-thing-at-point")
@click.argument("path", type=click.Path(exists=True))
@click.argument("position")
@click.pass_context
def describe_thing_at_point(ctx, path, position):
    """Show hover information at position (LINE,COLUMN)."""
    path = Path(path).resolve()
    line, column = parse_position(position)
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("describe-thing-at-point", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("find-definition")
@click.argument("path", type=click.Path(exists=True))
@click.argument("position")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
def find_definition(ctx, path, position, context):
    """Find definition at position (LINE,COLUMN)."""
    path = Path(path).resolve()
    line, column = parse_position(position)
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("find-definition", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
        "context": context,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("find-declaration")
@click.argument("path", type=click.Path(exists=True))
@click.argument("position")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
def find_declaration(ctx, path, position, context):
    """Find declaration at position (LINE,COLUMN)."""
    path = Path(path).resolve()
    line, column = parse_position(position)
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("find-declaration", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
        "context": context,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("find-implementation")
@click.argument("path", type=click.Path(exists=True))
@click.argument("position")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
def find_implementation(ctx, path, position, context):
    """Find implementation at position (LINE,COLUMN)."""
    path = Path(path).resolve()
    line, column = parse_position(position)
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("find-implementation", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
        "context": context,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("find-type-definition")
@click.argument("path", type=click.Path(exists=True))
@click.argument("position")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
def find_type_definition(ctx, path, position, context):
    """Find type definition at position (LINE,COLUMN)."""
    path = Path(path).resolve()
    line, column = parse_position(position)
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("find-type-definition", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
        "context": context,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("find-references")
@click.argument("path", type=click.Path(exists=True))
@click.argument("position")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
def find_references(ctx, path, position, context):
    """Find references at position (LINE,COLUMN)."""
    path = Path(path).resolve()
    line, column = parse_position(position)
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("find-references", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
        "context": context,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("print-definition")
@click.argument("path", type=click.Path(exists=True))
@click.argument("position")
@click.pass_context
def print_definition(ctx, path, position):
    """Print the full definition at position (LINE,COLUMN)."""
    path = Path(path).resolve()
    line, column = parse_position(position)
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("print-definition", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("list-code-actions")
@click.argument("path", type=click.Path(exists=True))
@click.argument("position")
@click.pass_context
def list_code_actions(ctx, path, position):
    """List code actions at position (LINE,COLUMN)."""
    path = Path(path).resolve()
    line, column = parse_position(position)
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("list-code-actions", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("execute-code-action")
@click.argument("path", type=click.Path(exists=True))
@click.argument("position")
@click.argument("action_title")
@click.pass_context
def execute_code_action(ctx, path, position, action_title):
    """Execute a code action at position (LINE,COLUMN)."""
    path = Path(path).resolve()
    line, column = parse_position(position)
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("execute-code-action", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
        "action_title": action_title,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("format")
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
def format_buffer(ctx, path):
    """Format a file."""
    path = Path(path).resolve()
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("format", {
        "path": str(path),
        "workspace_root": str(workspace_root),
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("organize-imports")
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
def organize_imports(ctx, path):
    """Organize imports in a file."""
    path = Path(path).resolve()
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("organize-imports", {
        "path": str(path),
        "workspace_root": str(workspace_root),
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("rename")
@click.argument("path", type=click.Path(exists=True))
@click.argument("position")
@click.argument("new_name")
@click.pass_context
def rename(ctx, path, position, new_name):
    """Rename symbol at position (LINE,COLUMN)."""
    path = Path(path).resolve()
    line, column = parse_position(position)
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("rename", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
        "new_name": new_name,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


VALID_SYMBOL_KINDS = {
    "file", "module", "namespace", "package", "class", "method", "property",
    "field", "constructor", "enum", "interface", "function", "variable",
    "constant", "string", "number", "boolean", "array", "object", "key",
    "null", "enummember", "struct", "event", "operator", "typeparameter",
}


def parse_kinds(kinds_str: str) -> set[str] | None:
    """Parse comma-separated kinds into a set of normalized kind names."""
    if not kinds_str:
        return None
    kinds = set()
    for k in kinds_str.split(","):
        k = k.strip().lower()
        if k and k not in VALID_SYMBOL_KINDS:
            raise click.BadParameter(
                f"Unknown kind '{k}'. Valid kinds: {', '.join(sorted(VALID_SYMBOL_KINDS))}"
            )
        if k:
            kinds.add(k)
    return kinds if kinds else None


def filter_symbols(symbols: list[dict], pattern: str, kinds: set[str] | None, case_sensitive: bool = False) -> list[dict]:
    """Filter symbols by regex pattern and/or kinds."""
    import re
    
    flags = 0 if case_sensitive else re.IGNORECASE
    regex = re.compile(pattern, flags)
    result = [s for s in symbols if regex.search(s.get("name", ""))]
    
    if kinds:
        result = [s for s in result if s.get("kind", "").lower() in kinds]
    
    return result


KIND_HELP = (
    "Filter by kind (comma-separated). Valid kinds: "
    "array, boolean, class, constant, constructor, enum, enummember, event, "
    "field, file, function, interface, key, method, module, namespace, null, "
    "number, object, operator, package, property, string, struct, typeparameter, variable"
)


@cli.command("grep")
@click.argument("pattern")
@click.argument("path", required=False)
@click.option("-k", "--kind", default="", help=KIND_HELP)
@click.option("-x", "--exclude", default="", help="Exclude files matching glob pattern (e.g. '*_test.go')")
@click.option("-d", "--docs", is_flag=True, help="Include documentation for each symbol")
@click.option("-C", "--case-sensitive", is_flag=True, help="Case-sensitive pattern matching")
@click.pass_context
def grep(ctx, pattern, path, kind, exclude, docs, case_sensitive):
    """Search for symbols matching a regex pattern.
    
    PATTERN is a regex matched against symbol names (case-insensitive by default).
    
    PATH supports wildcards. Simple patterns like '*.go' search recursively.
    Use 'dir/*.go' for non-recursive, or 'dir/**/*.go' for explicit recursive.
    
    Examples:
    
      lspcmd grep "Test.*" "*.go" -k function
    
      lspcmd grep "^User" -k class,struct
    
      lspcmd grep "Handler$" "internal/**/*.go" -d
    
      lspcmd grep "URL" -C  # case-sensitive
    
      lspcmd grep ".*" "*.go" -x "*_test.go"  # exclude tests
    """
    config = load_config()
    kinds = parse_kinds(kind)
    excluded_paths = expand_exclude_pattern(exclude) if exclude else set()

    if path:
        files = expand_path_pattern(path)
        if excluded_paths:
            files = [f for f in files if f not in excluded_paths]
        
        if not files:
            click.echo(format_output([], "json" if ctx.obj["json"] else "plain"))
            return
        
        all_symbols = []
        for file_path in files:
            workspace_root = get_workspace_root_for_path(file_path, config)
            response = run_request("list-symbols", {
                "path": str(file_path),
                "workspace_root": str(workspace_root),
            })
            result = response.get("result", [])
            if isinstance(result, list):
                all_symbols.extend(result)
        
        all_symbols = filter_symbols(all_symbols, pattern, kinds, case_sensitive)
        
        if docs and all_symbols:
            workspace_root = get_workspace_root_for_path(files[0], config)
            all_symbols = fetch_docs_for_symbols(all_symbols, workspace_root)
        
        click.echo(format_output(all_symbols, "json" if ctx.obj["json"] else "plain"))
    else:
        workspace_root = get_workspace_root_for_cwd(config)
        response = run_request("list-symbols", {
            "workspace_root": str(workspace_root),
        })
        result = response.get("result", [])
        if isinstance(result, list):
            if excluded_paths:
                result = [s for s in result if (workspace_root / s.get("path", "")).resolve() not in excluded_paths]
            result = filter_symbols(result, pattern, kinds, case_sensitive)
            if docs and result:
                result = fetch_docs_for_symbols(result, workspace_root)
        click.echo(format_output(result, "json" if ctx.obj["json"] else "plain"))


def fetch_docs_for_symbols(symbols: list[dict], workspace_root: Path) -> list[dict]:
    """Fetch documentation for a list of symbols via the daemon."""
    response = run_request("fetch-symbol-docs", {
        "symbols": symbols,
        "workspace_root": str(workspace_root),
    })
    return response.get("result", symbols)


@cli.command("restart-workspace")
@click.argument("workspace", type=click.Path(exists=True), required=False)
@click.pass_context
def restart_workspace(ctx, workspace):
    """Restart the language server for a workspace."""
    config = load_config()

    if workspace:
        workspace_root = Path(workspace).resolve()
    else:
        workspace_root = get_workspace_root_for_cwd(config)

    response = run_request("restart-workspace", {
        "workspace_root": str(workspace_root),
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


if __name__ == "__main__":
    cli()
