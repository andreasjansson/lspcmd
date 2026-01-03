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
    Config,
    get_socket_path,
    get_pid_path,
    get_config_path,
    get_log_dir,
    load_config,
    detect_workspace_root,
    get_known_workspace_root,
    get_best_workspace_root,
    add_workspace_root,
    remove_workspace_root,
)


from typing import Any


class OrderedGroup(click.Group):
    commands_order: list[str]

    def __init__(self, *args: Any, commands_order: list[str] | None = None, **kwargs: Any):  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.commands_order = commands_order or []

    def list_commands(self, ctx: click.Context) -> list[str]:
        commands = super().list_commands(ctx)
        if self.commands_order:
            ordered = [c for c in self.commands_order if c in commands]
            remaining = [c for c in commands if c not in self.commands_order]
            return ordered + remaining
        return commands


def ensure_daemon_running() -> None:
    pid_path = get_pid_path()
    socket_path = get_socket_path()

    if is_daemon_running(pid_path) and socket_path.exists():
        return

    subprocess.Popen(
        [sys.executable, "-m", "leta.daemon_cli"],
        start_new_session=True,
        env=os.environ.copy(),
    )

    for _ in range(50):
        if socket_path.exists():
            return
        time.sleep(0.1)

    raise click.ClickException("Failed to start daemon")


async def send_request(method: str, params: dict[str, object]) -> dict[str, object]:
    socket_path = get_socket_path()

    reader, writer = await asyncio.open_unix_connection(str(socket_path))

    request: dict[str, object] = {"method": method, "params": params}
    writer.write(json.dumps(request).encode())
    await writer.drain()
    writer.write_eof()

    data = await reader.read()
    writer.close()
    await writer.wait_closed()

    result: dict[str, object] = json.loads(data.decode())
    return result


def get_daemon_log_tail(num_lines: int = 10) -> str | None:
    log_path = get_log_dir() / "daemon.log"
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text().splitlines()
        tail = lines[-num_lines:] if len(lines) > num_lines else lines
        return "\n".join(tail)
    except Exception:
        return None


def run_request(method: str, params: dict[str, object]) -> dict[str, object]:
    ensure_daemon_running()
    response = asyncio.run(send_request(method, params))
    if "error" in response:
        error_msg = str(response["error"])
        if "Internal error" in error_msg or "internal error" in error_msg.lower():
            log_dir = get_log_dir()
            tail = get_daemon_log_tail(15)
            msg_parts = [error_msg, ""]
            if tail:
                msg_parts.append("Recent daemon log:")
                msg_parts.append(tail)
                msg_parts.append("")
            msg_parts.append(f"Full logs: {log_dir / 'daemon.log'}")
            raise click.ClickException("\n".join(msg_parts))
        raise click.ClickException(error_msg)
    return response


def output_result(result: object, output_format: str) -> None:
    """Output a result, writing errors/warnings/empty results to stderr."""
    if isinstance(result, dict):
        if "warning" in result:
            click.echo(f"Warning: {result['warning']}", err=True)
            return
    
    if isinstance(result, list) and not result:
        click.echo("No results", err=True)
        return
    
    formatted = format_output(result, output_format)
    if formatted:
        click.echo(formatted)


def get_workspace_root_for_path(path: Path, config: Config) -> Path:
    path = path.resolve()
    cwd = Path.cwd().resolve()

    workspace_root = get_best_workspace_root(path, config, cwd=cwd)
    if workspace_root:
        return workspace_root

    raise click.ClickException(
        f"No workspace found for {path}\n" f"Run: leta workspace add"
    )


def get_workspace_root_for_cwd(config: Config) -> Path:
    cwd = Path.cwd().resolve()

    workspace_root = get_best_workspace_root(cwd, config)
    if workspace_root:
        return workspace_root

    raise click.ClickException(
        f"No workspace found for current directory\n" f"Run: leta workspace add"
    )


class ResolvedSymbol:
    path: Path
    line: int
    column: int
    range_start_line: int | None
    range_end_line: int | None
    kind: str | None

    def __init__(self, path: Path, line: int, column: int,
                 range_start_line: int | None = None, range_end_line: int | None = None,
                 kind: str | None = None):
        self.path = path
        self.line = line
        self.column = column
        self.range_start_line = range_start_line
        self.range_end_line = range_end_line
        self.kind = kind


def resolve_symbol(symbol_path: str, workspace_root: Path) -> ResolvedSymbol:
    response = run_request("resolve-symbol", {
        "workspace_root": str(workspace_root),
        "symbol_path": symbol_path,
    })

    result_raw = response.get("result", response)
    if not isinstance(result_raw, dict):
        raise click.ClickException("Invalid response from daemon")
    result: dict[str, object] = result_raw

    if "error" in result:
        error_msg = str(result["error"])
        matches_raw = result.get("matches", [])
        matches = matches_raw if isinstance(matches_raw, list) else []

        if matches:
            lines = [error_msg]
            for m_raw in matches:
                if not isinstance(m_raw, dict):
                    continue
                m: dict[str, object] = m_raw
                container = f" in {m['container']}" if m.get("container") else ""
                kind = f"[{m['kind']}] " if m.get("kind") else ""
                detail = f" ({m['detail']})" if m.get("detail") else ""
                ref = m.get("ref", "")
                lines.append(f"  {ref}")
                lines.append(f"    {m['path']}:{m['line']} {kind}{m['name']}{detail}{container}")

            total_raw = result.get("total_matches")
            total = int(total_raw) if isinstance(total_raw, int) else len(matches)
            if total > len(matches):
                lines.append(f"  ... and {total - len(matches)} more")

            raise click.ClickException("\n".join(lines))
        else:
            raise click.ClickException(error_msg)

    path_val = result["path"]
    line_val = result["line"]
    column_val = result.get("column", 0)
    range_start = result.get("range_start_line")
    range_end = result.get("range_end_line")
    kind_val = result.get("kind")

    return ResolvedSymbol(
        path=Path(str(path_val)),
        line=int(line_val) if isinstance(line_val, int) else int(str(line_val)),
        column=int(column_val) if isinstance(column_val, int) else 0,
        range_start_line=int(range_start) if isinstance(range_start, int) else None,
        range_end_line=int(range_end) if isinstance(range_end, int) else None,
        kind=str(kind_val) if kind_val else None,
    )


def expand_path_pattern(pattern: str) -> list[Path]:
    """Expand a path pattern with glob wildcards (* and **) to matching files."""
    if "*" not in pattern and "?" not in pattern:
        path = Path(pattern).resolve()
        if path.exists():
            if path.is_dir():
                matches = glob.glob(str(path / "**" / "*"), recursive=True)
                if matches:
                    return [Path(m).resolve() for m in sorted(matches) if Path(m).is_file()]
                raise click.ClickException(f"No files found in directory: {pattern}")
            return [path]
        if "/" not in pattern:
            matches = glob.glob(f"**/{pattern}", recursive=True)
            if matches:
                return [Path(m).resolve() for m in sorted(matches) if Path(m).is_file()]
        raise click.ClickException(f"Path not found: {pattern}")

    if "/" not in pattern and not pattern.startswith("**"):
        pattern = "**/" + pattern

    matches = glob.glob(pattern, recursive=True)
    if not matches:
        raise click.ClickException(f"No files match pattern: {pattern}")

    return [Path(m).resolve() for m in sorted(matches) if Path(m).is_file()]


CLI_HELP = """\
Leta (LSP Enabled Tools for Agents) is a command line LSP client. It can quickly
search for symbols across large code bases with regular expressions, print full
function and method bodies, find references, implementations, subtypes, etc. It
also has refactoring tools, like renaming symbols across the entire code base.

`leta grep` can be much better than naive text search tools when you want to
understand a code base. Note that `leta grep` only exposes symbols that are
declared in its workspace, so use (rip)grep or other search tools when you're
looking for specific multi-symbol strings, puncuation, or library functions.
`leta grep PATTERN [PATH] --docs` prints function and method documentation
for all matching symbols.

`leta files` is a good starting point when starting work on a project.

Use `leta show SYMBOL` to print the full body of a symbol. Use
`leta refs SYMBOL` to find all uses of a symbol. These two (and other)
commands accept `--context N` for surrounding lines.

See `leta COMMAND --help` for more documentation and command-specific options.
"""


@click.group(
    cls=OrderedGroup,
    commands_order=[
        "grep",
        "files",
        "show",
        "refs",
        "calls",
        "implementations",
        "supertypes",
        "subtypes",
        "declaration",
        "rename",
        "mv",
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
def cli(ctx: click.Context, json_output: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output


@cli.group()
@click.pass_context
def daemon(ctx: click.Context) -> None:
    """Manage the leta daemon."""
    pass


@daemon.command("info")
@click.pass_context
def daemon_info(ctx: click.Context) -> None:
    """Show current daemon state."""
    response = run_request("describe-session", {})
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response.get("result"), output_format)


@daemon.command("start")
@click.pass_context
def daemon_start(ctx: click.Context) -> None:
    """Start the leta daemon."""
    _ = ctx
    pid_path = get_pid_path()
    socket_path = get_socket_path()

    if is_daemon_running(pid_path) and socket_path.exists():
        click.echo("Daemon already running")
        return

    ensure_daemon_running()
    click.echo("Daemon started")


@daemon.command("stop")
@click.pass_context
def daemon_stop(ctx: click.Context) -> None:
    """Stop the leta daemon."""
    _ = ctx
    if not is_daemon_running(get_pid_path()):
        click.echo("Daemon is not running")
        return

    run_request("shutdown", {})
    click.echo("Daemon stopped")


@daemon.command("restart")
@click.pass_context
def daemon_restart(ctx: click.Context) -> None:
    """Restart the leta daemon."""
    _ = ctx
    socket_path = get_socket_path()
    
    if is_daemon_running(get_pid_path()):
        run_request("shutdown", {})
        for _ in range(50):
            if not socket_path.exists():
                break
            time.sleep(0.1)
    
    ensure_daemon_running()
    click.echo("Daemon restarted")


@cli.group()
@click.pass_context
def workspace(ctx: click.Context) -> None:
    """Manage workspaces."""
    _ = ctx


def _is_interactive() -> bool:
    """Check if we're running in an interactive terminal."""
    if not sys.stdin.isatty():
        return False
    try:
        size = os.get_terminal_size()
        if size.columns == 0 or size.lines == 0:
            return False
    except OSError:
        return False
    return True


@workspace.command("add")
@click.option("--root", type=click.Path(exists=True), help="Workspace root directory")
@click.pass_context
def workspace_add(ctx: click.Context, root: str | None) -> None:
    """Add a workspace for LSP operations."""
    _ = ctx
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

        if _is_interactive():
            workspace_root_str: str = click.prompt(
                "Workspace root",
                default=str(default_root),
                type=click.Path(exists=True),
            )
            workspace_root = Path(workspace_root_str).resolve()
        else:
            raise click.ClickException(
                f"Cannot prompt for workspace root in non-interactive mode.\n"
                f"Use: leta workspace add --root {default_root}"
            )

    workspaces_config = config.get("workspaces", {})
    roots = workspaces_config.get("roots", []) if isinstance(workspaces_config, dict) else []
    if str(workspace_root) in roots:
        click.echo(f"Workspace already added: {workspace_root}")
        return

    add_workspace_root(workspace_root, config)
    click.echo(f"Added workspace: {workspace_root}")


@workspace.command("remove")
@click.argument("path", type=click.Path(exists=True), required=False)
@click.pass_context
def workspace_remove(ctx: click.Context, path: str | None) -> None:
    """Remove a workspace and stop its language servers."""
    _ = ctx
    config = load_config()

    if path:
        workspace_root = Path(path).resolve()
    else:
        workspace_root = get_workspace_root_for_cwd(config)

    if not remove_workspace_root(workspace_root, config):
        raise click.ClickException(f"Workspace not found: {workspace_root}")

    if is_daemon_running(get_pid_path()):
        response = run_request("remove-workspace", {
            "workspace_root": str(workspace_root),
        })
        result = response.get("result")
        if isinstance(result, dict):
            servers_stopped = result.get("servers_stopped", [])
            if isinstance(servers_stopped, list) and servers_stopped:
                click.echo(f"Removed workspace: {workspace_root}")
                click.echo(f"Stopped servers: {', '.join(str(s) for s in servers_stopped)}")
                return
        click.echo(f"Removed workspace: {workspace_root}")
    else:
        click.echo(f"Removed workspace: {workspace_root}")


@workspace.command("restart")
@click.argument("path", type=click.Path(exists=True), required=False)
@click.pass_context
def workspace_restart(ctx: click.Context, path: str | None) -> None:
    """Restart the language server for a workspace."""
    config = load_config()

    if path:
        workspace_root = Path(path).resolve()
    else:
        workspace_root = get_workspace_root_for_cwd(config)

    response = run_request("restart-workspace", {
        "workspace_root": str(workspace_root),
    })
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response.get("result"), output_format)


@cli.command()
@click.pass_context
def config(ctx: click.Context) -> None:
    """Print config file location and contents."""
    _ = ctx
    config_path = get_config_path()
    click.echo(f"Config file: {config_path}")
    click.echo()

    if config_path.exists():
        click.echo(config_path.read_text())
    else:
        click.echo("(file does not exist, using defaults)")


@cli.command("help-all")
@click.pass_context
def help_all(ctx: click.Context) -> None:
    """Print help for all commands."""
    click.echo("=" * 70)
    click.echo("LETA - Command Line LSP Client")
    click.echo("=" * 70)
    click.echo()
    
    with click.Context(cli, info_name="leta") as main_ctx:
        click.echo(cli.get_help(main_ctx))
    
    click.echo()
    click.echo("=" * 70)
    click.echo("COMMAND DETAILS")
    click.echo("=" * 70)
    
    def print_command_help(cmd: click.Command, name: str, prefix: str = "") -> None:
        full_name = f"{prefix}{name}" if prefix else name
        click.echo()
        click.echo("-" * 70)
        click.echo(f"leta {full_name}")
        click.echo("-" * 70)
        click.echo()
        
        with click.Context(cmd, info_name=f"leta {full_name}") as cmd_ctx:
            click.echo(cmd.get_help(cmd_ctx))
        
        if isinstance(cmd, click.Group):
            for subname in cmd.list_commands(cmd_ctx):
                subcmd = cmd.get_command(cmd_ctx, subname)
                if subcmd:
                    print_command_help(subcmd, subname, prefix=f"{full_name} ")
    
    for name in cli.list_commands(ctx):
        if name == "help-all":
            continue
        cmd = cli.get_command(ctx, name)
        if cmd:
            print_command_help(cmd, name)


SYMBOL_FORMATS = """\b
SYMBOL formats:
  SymbolName            find symbol by name
  Parent.Symbol         find symbol in parent (Class.method, module.function)
  path:Symbol           filter by file path pattern
  path:Parent.Symbol    combine path filter with qualified name
  path:line:Symbol      exact file + line number + symbol (for edge cases)"""


from typing import TypeVar, Callable

F = TypeVar("F", bound=Callable[..., object])


def with_symbol_help(func: F) -> F:
    """Decorator that appends SYMBOL format help to a command's docstring."""
    if func.__doc__:
        func.__doc__ = func.__doc__.rstrip() + "\n\n" + SYMBOL_FORMATS
    return func


@cli.command("show")
@click.argument("symbol")
@click.option("-n", "--context", default=0, help="Lines of context around definition")
@click.option("--head", default=200, help="Maximum lines to show (default: 200)")
@click.pass_context
@with_symbol_help
def show_cmd(ctx: click.Context, symbol: str, context: int, head: int) -> None:
    """Print the definition of a symbol. Shows the full body.

    \b
    Examples:
      leta show UserRepository
      leta show UserRepository.add_user
      leta show "*.py:User"
      leta show storage:MemoryStorage -n 2
      leta show COUNTRY_CODES           # shows full multi-line dict/object

    Use -n/--context to show surrounding lines.
    Use --head N to limit output to N lines.
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)

    resolved = resolve_symbol(symbol, workspace_root)

    response = run_request("show", {
        "path": str(resolved.path),
        "workspace_root": str(workspace_root),
        "line": resolved.line,
        "column": resolved.column,
        "context": context,
        "body": True,
        "direct_location": True,
        "range_start_line": resolved.range_start_line,
        "range_end_line": resolved.range_end_line,
        "head": head,
        "symbol": symbol,
        "kind": resolved.kind,
    })
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response["result"], output_format)


@cli.command("declaration")
@click.argument("symbol")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
@with_symbol_help
def declaration(ctx: click.Context, symbol: str, context: int) -> None:
    """Find declaration of a symbol."""
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)

    resolved = resolve_symbol(symbol, workspace_root)

    response = run_request("declaration", {
        "path": str(resolved.path),
        "workspace_root": str(workspace_root),
        "line": resolved.line,
        "column": resolved.column,
        "context": context,
    })
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response["result"], output_format)


@cli.command("refs")
@click.argument("symbol")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
@with_symbol_help
def refs(ctx: click.Context, symbol: str, context: int) -> None:
    """Find all references to a symbol.

    \b
    Examples:
      leta refs UserRepository
      leta refs UserRepository.add_user
      leta refs "*.py:validate_email"
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)

    resolved = resolve_symbol(symbol, workspace_root)

    response = run_request("references", {
        "path": str(resolved.path),
        "workspace_root": str(workspace_root),
        "line": resolved.line,
        "column": resolved.column,
        "context": context,
    })
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response["result"], output_format)


@cli.command("implementations")
@click.argument("symbol")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
@with_symbol_help
def implementations(ctx: click.Context, symbol: str, context: int) -> None:
    """Find implementations of an interface or abstract method.

    \b
    Examples:
      leta implementations Storage
      leta implementations Storage.save
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)

    resolved = resolve_symbol(symbol, workspace_root)

    response = run_request("implementations", {
        "path": str(resolved.path),
        "workspace_root": str(workspace_root),
        "line": resolved.line,
        "column": resolved.column,
        "context": context,
    })
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response["result"], output_format)


@cli.command("subtypes")
@click.argument("symbol")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
@with_symbol_help
def subtypes(ctx: click.Context, symbol: str, context: int) -> None:
    """Find direct subtypes of a type.

    Returns types that directly extend/implement the given type.
    Use 'implementations' to find all implementations transitively.
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)

    resolved = resolve_symbol(symbol, workspace_root)

    response = run_request("subtypes", {
        "path": str(resolved.path),
        "workspace_root": str(workspace_root),
        "line": resolved.line,
        "column": resolved.column,
        "context": context,
    })
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response["result"], output_format)


@cli.command("supertypes")
@click.argument("symbol")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
@with_symbol_help
def supertypes(ctx: click.Context, symbol: str, context: int) -> None:
    """Find direct supertypes of a type.

    Returns types that the given type directly extends/implements.
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)

    resolved = resolve_symbol(symbol, workspace_root)

    response = run_request("supertypes", {
        "path": str(resolved.path),
        "workspace_root": str(workspace_root),
        "line": resolved.line,
        "column": resolved.column,
        "context": context,
    })
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response["result"], output_format)


@cli.command("rename")
@click.argument("symbol")
@click.argument("new_name")
@click.pass_context
@with_symbol_help
def rename(ctx: click.Context, symbol: str, new_name: str) -> None:
    """Rename a symbol across the workspace.

    \b
    Examples:
      leta rename old_function new_function
      leta rename UserRepository.add_user add_new_user
      leta rename "user.py:User" Person
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)

    resolved = resolve_symbol(symbol, workspace_root)

    response = run_request("rename", {
        "path": str(resolved.path),
        "workspace_root": str(workspace_root),
        "line": resolved.line,
        "column": resolved.column,
        "new_name": new_name,
    })
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response["result"], output_format)


@cli.command("mv")
@click.argument("old_path", type=click.Path(exists=True))
@click.argument("new_path", type=click.Path())
@click.pass_context
def mv(ctx: click.Context, old_path: str, new_path: str) -> None:
    """Move/rename a file and update all imports.

    Moves OLD_PATH to NEW_PATH and asks the language server to update
    all import statements across the workspace.

    This uses the LSP workspace/willRenameFiles request, which is supported
    by language servers like typescript-language-server, rust-analyzer, and
    metals (Scala). Servers that don't support this will just move the file
    without updating imports.

    Examples:

      leta mv src/user.ts src/models/user.ts

      leta mv lib/utils.rs lib/helpers.rs
    """
    old_path_resolved = Path(old_path).resolve()
    new_path_resolved = Path(new_path).resolve()
    config = load_config()
    workspace_root = get_workspace_root_for_path(old_path_resolved, config)

    response = run_request("move-file", {
        "old_path": str(old_path_resolved),
        "new_path": str(new_path_resolved),
        "workspace_root": str(workspace_root),
    })
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response["result"], output_format)


VALID_SYMBOL_KINDS = {
    "file",
    "module",
    "namespace",
    "package",
    "class",
    "method",
    "property",
    "field",
    "constructor",
    "enum",
    "interface",
    "function",
    "variable",
    "constant",
    "string",
    "number",
    "boolean",
    "array",
    "object",
    "key",
    "null",
    "enummember",
    "struct",
    "event",
    "operator",
    "typeparameter",
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


GREP_HELP = """\
Search for symbols matching a regex pattern.

PATTERN is a regex matched against symbol names (case-insensitive by default).

PATH supports wildcards. Simple patterns like '*.go' search recursively.
Directories are automatically expanded to include all files recursively.

\b
IMPORTANT: leta grep searches SYMBOL NAMES only (functions, classes,
methods, variables, etc.). It does NOT search file contents like ripgrep.
Use ripgrep/grep when searching for:
  - String literals, comments, or documentation
  - Multi-word phrases or sentences
  - Symbols from external libraries (not defined in your code)
  - Punctuation or operators

\b
WHY USE leta grep INSTEAD OF ripgrep?
  - Semantic search: finds symbol definitions, not just text matches
  - No false positives: "User" won't match "UserError" or "getUser"
  - Filter by kind: find only classes, only functions, etc.
  - Get documentation: -d flag shows docstrings/comments
  - Understands scope: MyClass.method vs OtherClass.method

\b
COOKBOOK EXAMPLES:
\b
  Find all test functions across the project:
    leta grep "^Test" -k function
    leta grep "^test_" "*.py" -k function
\b
  Find a class and all its methods:
    leta grep "UserRepository" -k class
    leta grep ".*" -k method | grep UserRepository
\b
  Find all implementations of an interface pattern:
    leta grep "Storage$" -k class,struct
    leta grep "Handler$" -k class -d  # with docs
\b
  Explore unfamiliar code - what's in this file?
    leta grep "." src/server.py
    leta grep "." src/server.py -k function,method
\b
  Find all public functions (Go convention):
    leta grep "^[A-Z]" "*.go" -k function
\b
  Find all private methods (Python convention):
    leta grep "^_[^_]" "*.py" -k method
\b
  Find constants and configuration:
    leta grep ".*" -k constant
    leta grep "^(CONFIG|DEFAULT|MAX|MIN)" -k variable
\b
  Search with documentation to understand purpose:
    leta grep "parse" -k function -d
    leta grep "validate" -d
\b
  Exclude test files and vendor directories:
    leta grep "Handler" -x test -x vendor -x mock
\b
  Find symbols in a specific package/module:
    leta grep ".*" internal/auth -k function
    leta grep ".*" "src/models/*.py" -k class

\b
COMPARISON WITH ripgrep:
\b
  ripgrep: finds TEXT anywhere in files
    rg "UserRepository"  →  matches comments, strings, imports, usages
\b
  leta grep: finds SYMBOL DEFINITIONS only
    leta grep "UserRepository"  →  matches only where it's defined
\b
  Use ripgrep for: "find all files mentioning 'deprecated'"
  Use leta grep for: "find the deprecated functions"
"""


@cli.command("grep", help=GREP_HELP)
@click.argument("pattern")
@click.argument("path", required=False)
@click.option("-k", "--kind", default="", help=KIND_HELP)
@click.option(
    "-x",
    "--exclude",
    multiple=True,
    help="Exclude files matching glob pattern or directory (repeatable)",
)
@click.option("-d", "--docs", is_flag=True, help="Include documentation for each symbol")
@click.option("-C", "--case-sensitive", is_flag=True, help="Case-sensitive pattern matching")
@click.pass_context
def grep(ctx: click.Context, pattern: str, path: str | None, kind: str, exclude: tuple[str, ...], docs: bool, case_sensitive: bool) -> None:
    if " " in pattern:
        click.echo(
            f"Warning: Pattern contains a space. leta grep searches symbol names, "
            f"not file contents. Use ripgrep or grep for text search.",
            err=True,
        )
    config = load_config()
    kinds = parse_kinds(kind)
    exclude_patterns = list(exclude)

    if path:
        files = expand_path_pattern(path)
        if not files:
            click.echo("No results", err=True)
            return
        workspace_root = get_workspace_root_for_path(files[0], config)
        paths = [str(f) for f in files]
    else:
        paths = None
        workspace_root = get_workspace_root_for_cwd(config)

    response = run_request("grep", {
        "workspace_root": str(workspace_root),
        "pattern": pattern,
        "kinds": kinds,
        "case_sensitive": case_sensitive,
        "include_docs": docs,
        "paths": paths,
        "exclude_patterns": exclude_patterns,
    })
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response["result"], output_format)


@cli.command("files")
@click.argument("path", required=False)
@click.option(
    "-x",
    "--exclude",
    multiple=True,
    help="Exclude files matching glob pattern or directory (repeatable)",
)
@click.option(
    "-i",
    "--include",
    multiple=True,
    help="Include default-excluded directories (e.g., -i .git -i node_modules)",
)
@click.pass_context
def files(ctx: click.Context, path: str | None, exclude: tuple[str, ...], include: tuple[str, ...]) -> None:
    """Show source file tree with symbol and line counts.

    Lists all files in the workspace (or PATH if specified) with line counts.
    For files tracked by language servers, also shows counts of classes,
    functions, methods, etc.

    By default excludes common non-source directories like .git, __pycache__,
    node_modules, etc. Use -i/--include to include them.

    Examples:

      leta files                       # current workspace

      leta files src/                  # only src/ directory

      leta files -x tests -x vendor    # exclude additional directories

      leta files -i .git               # include .git directory

      leta --json files                # JSON output
    """
    config = load_config()
    
    if path:
        target_path = Path(path).resolve()
        workspace_root = get_workspace_root_for_path(target_path, config)
        subpath = str(target_path)
    else:
        workspace_root = get_workspace_root_for_cwd(config)
        subpath = None

    response = run_request("files", {
        "workspace_root": str(workspace_root),
        "subpath": subpath,
        "exclude_patterns": list(exclude),
        "include_patterns": list(include),
    })
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response["result"], output_format)


CALLS_HELP = """\
Show call hierarchy for a symbol.

At least one of --from or --to must be specified.

\b
Modes:
  --from SYMBOL         Show what SYMBOL calls (outgoing calls, top-down)
  --to SYMBOL           Show what calls SYMBOL (incoming calls, bottom-up)
  --from A --to B       Find call path from A to B

Use --max-depth to limit recursion depth (default: 3).

\b
Examples:
  leta calls --from main              # what does main() call?
  leta calls --to validate_email      # what calls validate_email()?
  leta calls --from main --to save    # find path from main to save
  leta calls --from UserRepo.add --max-depth 5

\b
SYMBOL formats:
  SymbolName            find symbol by name
  Parent.Symbol         find symbol in parent (Class.method, module.function)
  path:Symbol           filter by file path pattern
"""


@cli.command("calls", help=CALLS_HELP)
@click.option("--from", "from_symbol", default=None, help="Starting symbol (outgoing calls)")
@click.option("--to", "to_symbol", default=None, help="Target symbol (incoming calls)")
@click.option("--max-depth", default=3, help="Maximum recursion depth (default: 3)")
@click.option("--include-non-workspace", is_flag=True, help="Include calls to symbols outside the workspace (stdlib, dependencies)")
@click.pass_context
def calls(ctx: click.Context, from_symbol: str | None, to_symbol: str | None, max_depth: int, include_non_workspace: bool) -> None:
    if not from_symbol and not to_symbol:
        raise click.ClickException("At least one of --from or --to must be specified")

    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)

    params: dict[str, object] = {
        "workspace_root": str(workspace_root),
        "max_depth": max_depth,
        "include_non_workspace": include_non_workspace,
    }

    if from_symbol and to_symbol:
        from_resolved = resolve_symbol(from_symbol, workspace_root)
        to_resolved = resolve_symbol(to_symbol, workspace_root)
        params["from_path"] = str(from_resolved.path)
        params["from_line"] = from_resolved.line
        params["from_column"] = from_resolved.column
        params["from_symbol"] = from_symbol
        params["to_path"] = str(to_resolved.path)
        params["to_line"] = to_resolved.line
        params["to_column"] = to_resolved.column
        params["to_symbol"] = to_symbol
        params["mode"] = "path"
    elif from_symbol:
        resolved = resolve_symbol(from_symbol, workspace_root)
        params["from_path"] = str(resolved.path)
        params["from_line"] = resolved.line
        params["from_column"] = resolved.column
        params["from_symbol"] = from_symbol
        params["mode"] = "outgoing"
    else:
        assert to_symbol is not None
        resolved = resolve_symbol(to_symbol, workspace_root)
        params["to_path"] = str(resolved.path)
        params["to_line"] = resolved.line
        params["to_column"] = resolved.column
        params["to_symbol"] = to_symbol
        params["mode"] = "incoming"

    response = run_request("calls", params)
    output_format = "json" if ctx.obj["json"] else "plain"
    output_result(response["result"], output_format)


@cli.command("raw-lsp-request")
@click.argument("method")
@click.argument("params", required=False)
@click.option(
    "-l", "--language", default="python", help="Language server to use (python, go, typescript, etc.)"
)
@click.pass_context
def raw_lsp_request(ctx: click.Context, method: str, params: str | None, language: str) -> None:
    """Send a raw LSP request.

    METHOD is the LSP method (e.g. textDocument/documentSymbol).
    PARAMS is optional JSON parameters for the request.

    Examples:

      \b
      leta raw-lsp-request textDocument/documentSymbol \\
        '{"textDocument": {"uri": "file:///path/to/file.py"}}'

      leta raw-lsp-request workspace/symbol '{"query": ""}' -l go
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)

    try:
        lsp_params = json.loads(params) if params else {}
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON params: {e}")

    response = run_request("raw-lsp-request", {
        "workspace_root": str(workspace_root),
        "method": method,
        "params": lsp_params,
        "language": language,
    })
    click.echo(json.dumps(response["result"], indent=2))


if __name__ == "__main__":
    cli()
