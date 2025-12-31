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


class OrderedGroup(click.Group):
    def __init__(self, *args, commands_order: list[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.commands_order = commands_order or []

    def list_commands(self, ctx):
        commands = super().list_commands(ctx)
        if self.commands_order:
            ordered = [c for c in self.commands_order if c in commands]
            remaining = [c for c in commands if c not in self.commands_order]
            return ordered + remaining
        return commands


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
    response = asyncio.run(send_request(method, params))
    if "error" in response:
        raise click.ClickException(response["error"])
    return response


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
        f"Run: lspcmd workspace init"
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
        f"Run: lspcmd workspace init"
    )


def resolve_symbol(symbol_path: str, workspace_root: Path) -> tuple[Path, int, int]:
    """Resolve a symbol path to (file_path, line, column).
    
    Symbol path formats:
      - SymbolName              find symbol by name
      - Parent.Symbol           find symbol with parent (class.method, module.class, etc.)
      - path:Symbol             filter by file path pattern  
      - path:Parent.Symbol      combine path filter with qualified name
      - path:line:Symbol        exact file, line number, and symbol name (for edge cases)
    
    The hierarchy follows LSP document symbol containers:
      - module.Class.method.variable
      - module.function.variable
    
    Where 'module' is derived from the file name (e.g., user.py -> user).
    
    Returns:
        Tuple of (file_path, line, column) where line is 1-based, column is 0-based
        
    Raises:
        click.ClickException if symbol not found or ambiguous
    """
    response = run_request("resolve-symbol", {
        "workspace_root": str(workspace_root),
        "symbol_path": symbol_path,
    })
    
    result = response.get("result", response)
    
    if "error" in result:
        error_msg = result["error"]
        matches = result.get("matches", [])
        hint = result.get("hint")
        
        if matches:
            lines = [error_msg + ":"]
            for m in matches:
                container = f" in {m['container']}" if m.get("container") else ""
                kind = f" [{m['kind']}]" if m.get("kind") else ""
                detail = f" ({m['detail']})" if m.get("detail") else ""
                lines.append(f"  {m['path']}:{m['line']}{kind} {m['name']}{detail}{container}")
            
            total = result.get("total_matches", len(matches))
            if total > len(matches):
                lines.append(f"  ... and {total - len(matches)} more")
            
            if hint:
                lines.append("")
                lines.append(hint)
            
            raise click.ClickException("\n".join(lines))
        else:
            raise click.ClickException(error_msg)
    
    return (
        Path(result["path"]),
        result["line"],
        result.get("column", 0),
    )


def expand_path_pattern(pattern: str) -> list[Path]:
    """Expand a path pattern with glob wildcards (* and **) to matching files.
    
    Simple patterns without a directory (e.g. '*.go' or 'server.py') are treated as recursive.
    Directories are automatically treated as directory/** (recursive search).
    """
    if "*" not in pattern and "?" not in pattern:
        path = Path(pattern).resolve()
        if path.exists():
            if path.is_dir():
                matches = glob.glob(str(path / "**" / "*"), recursive=True)
                if matches:
                    return [Path(m).resolve() for m in sorted(matches) if Path(m).is_file()]
                raise click.ClickException(f"No files found in directory: {pattern}")
            return [path]
        # Bare filename without path separator - search recursively
        if "/" not in pattern:
            matches = glob.glob(f"**/{pattern}", recursive=True)
            if matches:
                return [Path(m).resolve() for m in sorted(matches) if Path(m).is_file()]
        raise click.ClickException(f"Path not found: {pattern}")
    
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
    Directories are automatically treated as directory/** (recursive exclusion).
    """
    if "*" not in pattern and "?" not in pattern:
        path = Path(pattern).resolve()
        if path.exists():
            if path.is_dir():
                matches = glob.glob(str(path / "**" / "*"), recursive=True)
                return {Path(m).resolve() for m in matches if Path(m).is_file()}
            return {path}
        return set()
    
    if "/" not in pattern and not pattern.startswith("**"):
        pattern = "**/" + pattern
    
    matches = glob.glob(pattern, recursive=True)
    return {Path(m).resolve() for m in matches if Path(m).is_file()}


CLI_HELP = """\
lspcmd is a command line LSP client. It can quickly search for symbols across
large code bases with regular expressions, print full function and method bodies,
find references, implementations, subtypes, etc. It also has refactoring tools,
like renaming symbols across the entire code base or formatting files.

`lspcmd grep` can be much better than naive text search tools when you want to
understand a code base. Note that `lspcmd grep` only exposes symbols that are
declared in its workspace, so use (rip)grep or other search tools when you're
looking for specific multi-symbol strings, puncuation, or library functions.
`lspcmd grep PATTERN [PATH] --docs` prints function and method documentation
for all matching symbols.

`lspcmd tree` is a good starting point when starting work on a project.

Use `lspcmd definition POSITION` to jump to the definition of a symbol that is
used at `POSITION`, and use `lspcmd references POSITION` to find all the uses
of a symbol at POSITION. These two (and other) commands accept `--context N`.
`lspcmd definition POSITION --body` prints the full body of a function/method.

See `lspcmd COMMAND --help` for more documentation and command-specific options.
"""


@click.group(
    cls=OrderedGroup,
    commands_order=[
        "grep",
        "tree",
        "definition",
        "references",
        "implementations",
        "supertypes",
        "subtypes",
        "declaration",
        "describe",
        "diagnostics",
        "rename",
        "move-file",
        "format",
        "organize-imports",
        "raw-lsp-request",
        "workspace",
        "daemon",
        "config",
    ],
    help=CLI_HELP,
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 120},
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.pass_context
def cli(ctx, json_output):
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output


@cli.group()
@click.pass_context
def daemon(ctx):
    """Manage the lspcmd daemon."""
    pass


@daemon.command("info")
@click.pass_context
def daemon_info(ctx):
    """Show current daemon state."""
    response = run_request("describe-session", {})
    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@daemon.command("shutdown")
@click.pass_context
def daemon_shutdown(ctx):
    """Shutdown the lspcmd daemon."""
    if not is_daemon_running(get_pid_path()):
        click.echo("Daemon is not running")
        return

    response = run_request("shutdown", {})
    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.group()
@click.pass_context
def workspace(ctx):
    """Manage workspaces."""
    pass


@workspace.command("init")
@click.option("--root", type=click.Path(exists=True), help="Workspace root directory")
@click.pass_context
def workspace_init(ctx, root):
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


@workspace.command("restart")
@click.argument("path", type=click.Path(exists=True), required=False)
@click.pass_context
def workspace_restart(ctx, path):
    """Restart the language server for a workspace."""
    config = load_config()

    if path:
        workspace_root = Path(path).resolve()
    else:
        workspace_root = get_workspace_root_for_cwd(config)

    response = run_request("restart-workspace", {
        "workspace_root": str(workspace_root),
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


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


@cli.command("describe")
@click.argument("symbol")
@click.pass_context
def describe(ctx, symbol):
    """Show hover information (type signature, documentation) for a symbol.
    
    \b
    SYMBOL formats:
      SymbolName            find symbol by name
      Parent.Symbol         find symbol in parent (Class.method, module.function)
      path:Symbol           filter by file path pattern
      path:Parent.Symbol    combine path filter with qualified name
      path:line:Symbol      exact file + line number + symbol (for edge cases)
    
    \b
    Examples:
      lspcmd describe UserRepository
      lspcmd describe UserRepository.add_user
      lspcmd describe user:User
      lspcmd describe "*.py:validate_email"
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)
    path, line, column = resolve_symbol(symbol, workspace_root)

    response = run_request("describe", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("definition")
@click.argument("path_or_symbol")
@click.argument("position", required=False)
@click.option("-n", "--context", default=0, help="Lines of context")
@click.option("-b", "--body", is_flag=True, help="Print full definition body")
@click.pass_context
def definition(ctx, path_or_symbol, position, context, body):
    """Find definition at position.
    
    \b
    Usage:
      lspcmd definition PATH POSITION      # traditional file+position
      lspcmd definition @Symbol            # symbol lookup
    
    \b
    POSITION can be:
      - LINE,COLUMN (e.g. 42,10)
      - LINE:REGEX (e.g. 42:def foo)
      - REGEX (e.g. def foo) to search the whole file
    
    \b
    @Symbol syntax (symbol lookup):
      - @SymbolName          # find a symbol by name
      - @Class.method        # find method in Class
      - @path:Symbol         # find Symbol in files matching path
      - @*.py:MyClass        # find MyClass in Python files
    
    Use -b/--body to print the full definition body (for functions, classes, etc.).
    """
    config = load_config()
    
    if is_symbol_path(path_or_symbol):
        workspace_root = get_workspace_root_for_cwd(config)
        path, line, column = resolve_symbol_path(path_or_symbol, workspace_root)
    else:
        path = Path(path_or_symbol).resolve()
        if not path.exists():
            raise click.ClickException(f"File not found: {path_or_symbol}")
        if position is None:
            raise click.ClickException(
                "POSITION is required when using PATH.\n"
                "Use @Symbol syntax for symbol lookup (e.g., @ClassName.method)"
            )
        line, column = parse_position(position, path)
        workspace_root = get_workspace_root_for_path(path, config)

    response = run_request("definition", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
        "context": context,
        "body": body,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


def _run_location_command(ctx, path_or_symbol: str, position: str | None, context: int, request_name: str):
    """Helper for location-based commands (definition, references, implementations, etc.)."""
    config = load_config()
    
    if is_symbol_path(path_or_symbol):
        workspace_root = get_workspace_root_for_cwd(config)
        path, line, column = resolve_symbol_path(path_or_symbol, workspace_root)
    else:
        path = Path(path_or_symbol).resolve()
        if not path.exists():
            raise click.ClickException(f"File not found: {path_or_symbol}")
        if position is None:
            raise click.ClickException(
                "POSITION is required when using PATH.\n"
                "Use @Symbol syntax for symbol lookup (e.g., @ClassName.method)"
            )
        line, column = parse_position(position, path)
        workspace_root = get_workspace_root_for_path(path, config)

    response = run_request(request_name, {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
        "context": context,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("declaration")
@click.argument("path_or_symbol")
@click.argument("position", required=False)
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
def declaration(ctx, path_or_symbol, position, context):
    """Find declaration at position.
    
    \b
    Usage:
      lspcmd declaration PATH POSITION      # traditional file+position
      lspcmd declaration @Symbol            # symbol lookup
    
    \b
    POSITION formats:
      LINE,COLUMN    e.g. 42,10
      LINE:REGEX     e.g. 42:def foo
      REGEX          search whole file for unique match
    
    \b
    @Symbol formats:
      @SymbolName          find a symbol by name
      @Class.method        find method in Class
      @path:Symbol         find Symbol in files matching path
    """
    _run_location_command(ctx, path_or_symbol, position, context, "declaration")


@cli.command("references")
@click.argument("path_or_symbol")
@click.argument("position", required=False)
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
def references(ctx, path_or_symbol, position, context):
    """Find references at position.
    
    \b
    Usage:
      lspcmd references PATH POSITION       # traditional file+position
      lspcmd references @Symbol             # symbol lookup
    
    \b
    POSITION formats:
      LINE,COLUMN    e.g. 42,10
      LINE:REGEX     e.g. 42:def foo
      REGEX          search whole file for unique match
    
    \b
    @Symbol formats:
      @SymbolName          find a symbol by name
      @Class.method        find method in Class
      @path:Symbol         find Symbol in files matching path
    """
    _run_location_command(ctx, path_or_symbol, position, context, "references")


@cli.command("implementations")
@click.argument("path_or_symbol")
@click.argument("position", required=False)
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
def implementations(ctx, path_or_symbol, position, context):
    """Find implementations of an interface or abstract method.
    
    \b
    Usage:
      lspcmd implementations PATH POSITION  # traditional file+position
      lspcmd implementations @Symbol        # symbol lookup
    
    \b
    POSITION formats:
      LINE,COLUMN    e.g. 42,10
      LINE:REGEX     e.g. 42:def foo
      REGEX          search whole file for unique match
    
    \b
    @Symbol formats:
      @SymbolName          find a symbol by name
      @Class.method        find method in Class
      @path:Symbol         find Symbol in files matching path
    """
    _run_location_command(ctx, path_or_symbol, position, context, "implementations")


@cli.command("subtypes")
@click.argument("path_or_symbol")
@click.argument("position", required=False)
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
def subtypes(ctx, path_or_symbol, position, context):
    """Find direct subtypes of a type at position.
    
    Returns types that directly extend/implement the type at position.
    Use 'implementations' to find all implementations transitively.
    
    \b
    Usage:
      lspcmd subtypes PATH POSITION         # traditional file+position
      lspcmd subtypes @Symbol               # symbol lookup
    
    \b
    POSITION formats:
      LINE,COLUMN    e.g. 42,10
      LINE:REGEX     e.g. 42:def foo
      REGEX          search whole file for unique match
    
    \b
    @Symbol formats:
      @SymbolName          find a symbol by name
      @Class.method        find method in Class
      @path:Symbol         find Symbol in files matching path
    """
    _run_location_command(ctx, path_or_symbol, position, context, "subtypes")


@cli.command("supertypes")
@click.argument("path_or_symbol")
@click.argument("position", required=False)
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
def supertypes(ctx, path_or_symbol, position, context):
    """Find direct supertypes of a type at position.
    
    Returns types that the type at position directly extends/implements.
    
    \b
    Usage:
      lspcmd supertypes PATH POSITION       # traditional file+position
      lspcmd supertypes @Symbol             # symbol lookup
    
    \b
    POSITION formats:
      LINE,COLUMN    e.g. 42,10
      LINE:REGEX     e.g. 42:def foo
      REGEX          search whole file for unique match
    
    \b
    @Symbol formats:
      @SymbolName          find a symbol by name
      @Class.method        find method in Class
      @path:Symbol         find Symbol in files matching path
    """
    _run_location_command(ctx, path_or_symbol, position, context, "supertypes")


@cli.command("diagnostics")
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option("-s", "--severity", default=None, 
              type=click.Choice(["error", "warning", "info", "hint"]),
              help="Filter by minimum severity level")
@click.pass_context
def diagnostics(ctx, path, severity):
    """Show diagnostics for a file or workspace.
    
    If PATH is provided, shows diagnostics for that file.
    If PATH is omitted, shows diagnostics for all files in the workspace.
    
    Note: Some language servers (e.g. typescript-language-server) push
    diagnostics asynchronously. After a workspace restart or on first run,
    diagnostics may take a few seconds to become fully available.
    
    Examples:
    
      lspcmd diagnostics                       # all files in workspace
    
      lspcmd diagnostics src/main.py           # single file
    
      lspcmd diagnostics -s error              # errors only
    
      lspcmd --json diagnostics                # JSON output
    """
    config = load_config()
    
    if path:
        path = Path(path).resolve()
        workspace_root = get_workspace_root_for_path(path, config)
        response = run_request("diagnostics", {
            "path": str(path),
            "workspace_root": str(workspace_root),
        })
        result = response.get("result", [])
    else:
        workspace_root = get_workspace_root_for_cwd(config)
        response = run_request("workspace-diagnostics", {
            "workspace_root": str(workspace_root),
        })
        result = response.get("result", [])
    
    if severity:
        severity_order = {"error": 0, "warning": 1, "info": 2, "hint": 3}
        min_level = severity_order[severity]
        result = [d for d in result if severity_order.get(d.get("severity", "error"), 0) <= min_level]

    click.echo(format_output(result, "json" if ctx.obj["json"] else "plain"))


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
@click.argument("path_or_symbol")
@click.argument("position_or_new_name")
@click.argument("new_name", required=False)
@click.pass_context
def rename(ctx, path_or_symbol, position_or_new_name, new_name):
    """Rename symbol at position.
    
    \b
    Usage:
      lspcmd rename PATH POSITION NEW_NAME  # traditional file+position
      lspcmd rename @Symbol NEW_NAME        # symbol lookup
    
    \b
    POSITION formats:
      LINE,COLUMN    e.g. 42,10
      LINE:REGEX     e.g. 42:def foo
      REGEX          search whole file for unique match
    
    \b
    @Symbol formats:
      @SymbolName          find a symbol by name
      @Class.method        find method in Class
      @path:Symbol         find Symbol in files matching path
    """
    config = load_config()
    
    if is_symbol_path(path_or_symbol):
        workspace_root = get_workspace_root_for_cwd(config)
        path, line, column = resolve_symbol_path(path_or_symbol, workspace_root)
        actual_new_name = position_or_new_name
    else:
        path = Path(path_or_symbol).resolve()
        if not path.exists():
            raise click.ClickException(f"File not found: {path_or_symbol}")
        if new_name is None:
            raise click.ClickException(
                "NEW_NAME is required when using PATH POSITION.\n"
                "Use @Symbol syntax for simpler usage (e.g., lspcmd rename @OldName NewName)"
            )
        line, column = parse_position(position_or_new_name, path)
        workspace_root = get_workspace_root_for_path(path, config)
        actual_new_name = new_name

    response = run_request("rename", {
        "path": str(path),
        "workspace_root": str(workspace_root),
        "line": line,
        "column": column,
        "new_name": actual_new_name,
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("move-file")
@click.argument("old_path", type=click.Path(exists=True))
@click.argument("new_path", type=click.Path())
@click.pass_context
def move_file(ctx, old_path, new_path):
    """Move/rename a file and update all imports.
    
    Moves OLD_PATH to NEW_PATH and asks the language server to update
    all import statements across the workspace.
    
    This uses the LSP workspace/willRenameFiles request, which is supported
    by language servers like typescript-language-server, rust-analyzer, and
    metals (Scala). Servers that don't support this will just move the file
    without updating imports.
    
    Examples:
    
      lspcmd move-file src/user.ts src/models/user.ts
    
      lspcmd move-file lib/utils.rs lib/helpers.rs
    """
    old_path = Path(old_path).resolve()
    new_path = Path(new_path).resolve()
    config = load_config()
    workspace_root = get_workspace_root_for_path(old_path, config)

    response = run_request("move-file", {
        "old_path": str(old_path),
        "new_path": str(new_path),
        "workspace_root": str(workspace_root),
    })

    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


VALID_SYMBOL_KINDS = {
    "file", "module", "namespace", "package", "class", "method", "property",
    "field", "constructor", "enum", "interface", "function", "variable",
    "constant", "string", "number", "boolean", "array", "object", "key",
    "null", "enummember", "struct", "event", "operator", "typeparameter",
}


def parse_kinds(kinds_str: str) -> list[str] | None:
    """Parse comma-separated kinds into a list of normalized kind names."""
    if not kinds_str:
        return None
    kinds = []
    for k in kinds_str.split(","):
        k = k.strip().lower()
        if k and k not in VALID_SYMBOL_KINDS:
            raise click.BadParameter(
                f"Unknown kind '{k}'. Valid kinds: {', '.join(sorted(VALID_SYMBOL_KINDS))}"
            )
        if k:
            kinds.append(k)
    return kinds if kinds else None


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
@click.option("-x", "--exclude", multiple=True, help="Exclude files matching glob pattern or directory (repeatable)")
@click.option("-d", "--docs", is_flag=True, help="Include documentation for each symbol")
@click.option("-C", "--case-sensitive", is_flag=True, help="Case-sensitive pattern matching")
@click.pass_context
def grep(ctx, pattern, path, kind, exclude, docs, case_sensitive):
    """Search for symbols matching a regex pattern.
    
    PATTERN is a regex matched against symbol names (case-insensitive by default).
    
    PATH supports wildcards. Simple patterns like '*.go' search recursively.
    Directories are automatically expanded to include all files recursively.
    
    Examples:
    
      lspcmd grep "Test.*" "*.go" -k function
    
      lspcmd grep "^User" -k class,struct
    
      lspcmd grep "Handler$" internal -d  # search internal/ recursively
    
      lspcmd grep "URL" -C  # case-sensitive
    
      lspcmd grep ".*" "*.go" -x tests -x vendor  # exclude multiple directories
    """
    config = load_config()
    kinds = parse_kinds(kind)
    exclude_patterns = list(exclude)

    if path:
        files = expand_path_pattern(path)
        if not files:
            click.echo(format_output([], "json" if ctx.obj["json"] else "plain"))
            return
        workspace_root = get_workspace_root_for_path(files[0], config)
    else:
        files = None
        workspace_root = get_workspace_root_for_cwd(config)

    response = run_request("grep", {
        "workspace_root": str(workspace_root),
        "pattern": pattern,
        "kinds": kinds,
        "case_sensitive": case_sensitive,
        "include_docs": docs,
        "paths": [str(f) for f in files] if files else None,
        "exclude_patterns": exclude_patterns,
    })

    click.echo(format_output(response.get("result", []), "json" if ctx.obj["json"] else "plain"))


@cli.command("tree")
@click.option("-x", "--exclude", multiple=True, help="Exclude files matching glob pattern or directory (repeatable)")
@click.pass_context
def tree(ctx, exclude):
    """Show source file tree with file sizes.
    
    Only includes files that have an associated language server
    (i.e., source files the LSP understands).
    
    Examples:
    
      lspcmd tree                       # current workspace
    
      lspcmd tree -x tests -x vendor    # exclude directories
    
      lspcmd --json tree                # JSON output
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)
    
    response = run_request("tree", {
        "workspace_root": str(workspace_root),
        "exclude_patterns": list(exclude),
    })
    
    click.echo(format_output(response.get("result", response), "json" if ctx.obj["json"] else "plain"))


@cli.command("raw-lsp-request")
@click.argument("method")
@click.argument("params", required=False)
@click.option("-l", "--language", default="python", help="Language server to use (python, go, typescript, etc.)")
@click.pass_context
def raw_lsp_request(ctx, method, params, language):
    """Send a raw LSP request (for debugging).
    
    METHOD is the LSP method (e.g. textDocument/documentSymbol).
    PARAMS is optional JSON parameters for the request.
    
    Examples:
    
      lspcmd raw-lsp-request textDocument/documentSymbol \\
        '{"textDocument": {"uri": "file:///path/to/file.py"}}'
    
      lspcmd raw-lsp-request workspace/symbol '{"query": ""}' -l go
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)
    
    lsp_params = {}
    if params:
        lsp_params = json.loads(params)
    
    response = run_request("raw-lsp-request", {
        "workspace_root": str(workspace_root),
        "method": method,
        "params": lsp_params,
        "language": language,
    })
    
    click.echo(json.dumps(response.get("result", response), indent=2))


if __name__ == "__main__":
    cli()
