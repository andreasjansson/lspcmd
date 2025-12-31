import asyncio
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import click
import httpx

from .daemon.pidfile import is_daemon_running
from .utils.config import (
    get_pid_path,
    get_config_path,
    get_log_dir,
    get_mcp_port_path,
    get_mcp_url,
    load_config,
    detect_workspace_root,
    get_known_workspace_root,
    get_best_workspace_root,
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


def ensure_daemon_running() -> str:
    """Ensure daemon is running and return the MCP URL."""
    pid_path = get_pid_path()
    mcp_url = get_mcp_url()

    if is_daemon_running(pid_path) and mcp_url:
        return mcp_url

    subprocess.Popen(
        [sys.executable, "-m", "lspcmd.daemon_cli"],
        start_new_session=True,
        env=os.environ.copy(),
    )

    port_path = get_mcp_port_path()
    for _ in range(50):
        if port_path.exists():
            mcp_url = get_mcp_url()
            if mcp_url:
                return mcp_url
        time.sleep(0.1)

    raise click.ClickException("Failed to start daemon")


def call_mcp_tool(tool_name: str, arguments: dict) -> str:
    """Call an MCP tool and return the result."""
    mcp_url = ensure_daemon_running()
    return asyncio.run(_call_mcp_tool_async(mcp_url, tool_name, arguments))


async def _call_mcp_tool_async(mcp_url: str, tool_name: str, arguments: dict) -> str:
    """Async implementation of MCP tool call using Streamable HTTP."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx.AsyncClient(timeout=120.0, headers=headers) as client:
        # Initialize session
        init_response = await client.post(
            mcp_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "lspcmd-cli", "version": "0.1.0"},
                },
            },
        )
        init_response.raise_for_status()
        
        # Get session ID for subsequent requests
        session_id = init_response.headers.get("mcp-session-id")
        if session_id:
            client.headers["mcp-session-id"] = session_id

        # Send initialized notification
        await client.post(
            mcp_url,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        # Call the tool
        tool_response = await client.post(
            mcp_url,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            },
        )
        tool_response.raise_for_status()

        result = tool_response.json()
        if "error" in result:
            error = result["error"]
            msg = error.get("message", str(error))
            raise click.ClickException(msg)

        # Extract text content from MCP response
        content = result.get("result", {}).get("content", [])
        if content and isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            return "\n".join(text_parts)

        return ""


def strip_mcp_error_prefix(msg: str) -> str:
    """Strip MCP 'Error executing tool X: ' prefix from error messages."""
    import re
    match = re.match(r'^Error executing tool \w+: (.+)$', msg)
    if match:
        return match.group(1)
    return msg


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


def get_workspace_root_for_path(path: Path, config: dict) -> Path:
    path = path.resolve()
    cwd = Path.cwd().resolve()

    workspace_root = get_best_workspace_root(path, config, cwd=cwd)
    if workspace_root:
        return workspace_root

    raise click.ClickException(
        f"No workspace initialized for {path}\n" f"Run: lspcmd workspace init"
    )


def get_workspace_root_for_cwd(config: dict) -> Path:
    cwd = Path.cwd().resolve()

    workspace_root = get_best_workspace_root(cwd, config)
    if workspace_root:
        return workspace_root

    raise click.ClickException(
        f"No workspace initialized for current directory\n" f"Run: lspcmd workspace init"
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

Use `lspcmd show SYMBOL` to print the full body of a symbol. Use
`lspcmd ref SYMBOL` to find all uses of a symbol. These two (and other)
commands accept `--context N` for surrounding lines.

See `lspcmd COMMAND --help` for more documentation and command-specific options.
"""


@click.group(
    cls=OrderedGroup,
    commands_order=[
        "grep",
        "tree",
        "show",
        "ref",
        "implementations",
        "supertypes",
        "subtypes",
        "declaration",
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
    output_format = "json" if ctx.obj["json"] else "plain"
    result = call_mcp_tool("daemon_info", {"output_format": output_format})
    click.echo(result)


@daemon.command("shutdown")
@click.pass_context
def daemon_shutdown(ctx):
    """Shutdown the lspcmd daemon."""
    if not is_daemon_running(get_pid_path()):
        click.echo("Daemon is not running")
        return

    result = call_mcp_tool("daemon_shutdown", {})
    click.echo(result)


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

    output_format = "json" if ctx.obj["json"] else "plain"
    result = call_mcp_tool(
        "workspace_restart",
        {
            "workspace_root": str(workspace_root),
            "output_format": output_format,
        },
    )
    click.echo(result)


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


SYMBOL_FORMATS = """\b
SYMBOL formats:
  SymbolName            find symbol by name
  Parent.Symbol         find symbol in parent (Class.method, module.function)
  path:Symbol           filter by file path pattern
  path:Parent.Symbol    combine path filter with qualified name
  path:line:Symbol      exact file + line number + symbol (for edge cases)"""


def with_symbol_help(func):
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
def show_cmd(ctx, symbol, context, head):
    """Print the definition of a symbol. Shows the full body.

    \b
    Examples:
      lspcmd show UserRepository
      lspcmd show UserRepository.add_user
      lspcmd show "*.py:User"
      lspcmd show storage:MemoryStorage -n 2

    Use -n/--context to show surrounding lines.
    Use --head N to limit output to N lines.
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)
    output_format = "json" if ctx.obj["json"] else "plain"

    result = call_mcp_tool(
        "show",
        {
            "workspace_root": str(workspace_root),
            "symbol": symbol,
            "context": context,
            "head": head,
            "output_format": output_format,
        },
    )
    click.echo(result)


@cli.command("declaration")
@click.argument("symbol")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
@with_symbol_help
def declaration(ctx, symbol, context):
    """Find declaration of a symbol."""
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)
    output_format = "json" if ctx.obj["json"] else "plain"

    result = call_mcp_tool(
        "declaration",
        {
            "workspace_root": str(workspace_root),
            "symbol": symbol,
            "context": context,
            "output_format": output_format,
        },
    )
    click.echo(result)


@cli.command("ref")
@click.argument("symbol")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
@with_symbol_help
def ref(ctx, symbol, context):
    """Find all references to a symbol.

    \b
    Examples:
      lspcmd ref UserRepository
      lspcmd ref UserRepository.add_user
      lspcmd ref "*.py:validate_email"
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)
    output_format = "json" if ctx.obj["json"] else "plain"

    result = call_mcp_tool(
        "ref",
        {
            "workspace_root": str(workspace_root),
            "symbol": symbol,
            "context": context,
            "output_format": output_format,
        },
    )
    click.echo(result)


@cli.command("implementations")
@click.argument("symbol")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
@with_symbol_help
def implementations(ctx, symbol, context):
    """Find implementations of an interface or abstract method.

    \b
    Examples:
      lspcmd implementations Storage
      lspcmd implementations Storage.save
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)
    output_format = "json" if ctx.obj["json"] else "plain"

    result = call_mcp_tool(
        "implementations",
        {
            "workspace_root": str(workspace_root),
            "symbol": symbol,
            "context": context,
            "output_format": output_format,
        },
    )
    click.echo(result)


@cli.command("subtypes")
@click.argument("symbol")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
@with_symbol_help
def subtypes(ctx, symbol, context):
    """Find direct subtypes of a type.

    Returns types that directly extend/implement the given type.
    Use 'implementations' to find all implementations transitively.
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)
    output_format = "json" if ctx.obj["json"] else "plain"

    result = call_mcp_tool(
        "subtypes",
        {
            "workspace_root": str(workspace_root),
            "symbol": symbol,
            "context": context,
            "output_format": output_format,
        },
    )
    click.echo(result)


@cli.command("supertypes")
@click.argument("symbol")
@click.option("-n", "--context", default=0, help="Lines of context")
@click.pass_context
@with_symbol_help
def supertypes(ctx, symbol, context):
    """Find direct supertypes of a type.

    Returns types that the given type directly extends/implements.
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)
    output_format = "json" if ctx.obj["json"] else "plain"

    result = call_mcp_tool(
        "supertypes",
        {
            "workspace_root": str(workspace_root),
            "symbol": symbol,
            "context": context,
            "output_format": output_format,
        },
    )
    click.echo(result)


@cli.command("diagnostics")
@click.argument("path", type=click.Path(exists=True), required=False)
@click.option(
    "-s",
    "--severity",
    default=None,
    type=click.Choice(["error", "warning", "info", "hint"]),
    help="Filter by minimum severity level",
)
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
    output_format = "json" if ctx.obj["json"] else "plain"

    if path:
        path = str(Path(path).resolve())
        workspace_root = get_workspace_root_for_path(Path(path), config)
    else:
        path = None
        workspace_root = get_workspace_root_for_cwd(config)

    result = call_mcp_tool(
        "diagnostics",
        {
            "workspace_root": str(workspace_root),
            "path": path,
            "severity": severity,
            "output_format": output_format,
        },
    )
    click.echo(result)


@cli.command("format")
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
def format_buffer(ctx, path):
    """Format a file."""
    path = Path(path).resolve()
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)
    output_format = "json" if ctx.obj["json"] else "plain"

    result = call_mcp_tool(
        "format_file",
        {
            "workspace_root": str(workspace_root),
            "path": str(path),
            "output_format": output_format,
        },
    )
    click.echo(result)


@cli.command("organize-imports")
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
def organize_imports(ctx, path):
    """Organize imports in a file."""
    path = Path(path).resolve()
    config = load_config()
    workspace_root = get_workspace_root_for_path(path, config)
    output_format = "json" if ctx.obj["json"] else "plain"

    result = call_mcp_tool(
        "organize_imports",
        {
            "workspace_root": str(workspace_root),
            "path": str(path),
            "output_format": output_format,
        },
    )
    click.echo(result)


@cli.command("rename")
@click.argument("symbol")
@click.argument("new_name")
@click.pass_context
@with_symbol_help
def rename(ctx, symbol, new_name):
    """Rename a symbol across the workspace.

    \b
    Examples:
      lspcmd rename old_function new_function
      lspcmd rename UserRepository.add_user add_new_user
      lspcmd rename "user.py:User" Person
    """
    config = load_config()
    workspace_root = get_workspace_root_for_cwd(config)
    output_format = "json" if ctx.obj["json"] else "plain"

    result = call_mcp_tool(
        "rename",
        {
            "workspace_root": str(workspace_root),
            "symbol": symbol,
            "new_name": new_name,
            "output_format": output_format,
        },
    )
    click.echo(result)


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
    output_format = "json" if ctx.obj["json"] else "plain"

    result = call_mcp_tool(
        "move_file",
        {
            "workspace_root": str(workspace_root),
            "old_path": str(old_path),
            "new_path": str(new_path),
            "output_format": output_format,
        },
    )
    click.echo(result)


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


@cli.command("grep")
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
    if " " in pattern:
        click.echo(
            f"Warning: Pattern contains a space. lspcmd grep searches symbol names, "
            f"not file contents. Use ripgrep or grep for text search.",
            err=True,
        )
    config = load_config()
    kinds = parse_kinds(kind)
    exclude_patterns = list(exclude)
    output_format = "json" if ctx.obj["json"] else "plain"

    if path:
        files = expand_path_pattern(path)
        if not files:
            click.echo("No results")
            return
        workspace_root = get_workspace_root_for_path(files[0], config)
        paths = [str(f) for f in files]
    else:
        paths = None
        workspace_root = get_workspace_root_for_cwd(config)

    result = call_mcp_tool(
        "grep",
        {
            "workspace_root": str(workspace_root),
            "pattern": pattern,
            "kinds": kinds,
            "case_sensitive": case_sensitive,
            "include_docs": docs,
            "paths": paths,
            "exclude_patterns": exclude_patterns,
            "output_format": output_format,
        },
    )
    click.echo(result)


@cli.command("tree")
@click.option(
    "-x",
    "--exclude",
    multiple=True,
    help="Exclude files matching glob pattern or directory (repeatable)",
)
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
    output_format = "json" if ctx.obj["json"] else "plain"

    result = call_mcp_tool(
        "tree",
        {
            "workspace_root": str(workspace_root),
            "exclude_patterns": list(exclude),
            "output_format": output_format,
        },
    )
    click.echo(result)


@cli.command("raw-lsp-request")
@click.argument("method")
@click.argument("params", required=False)
@click.option(
    "-l", "--language", default="python", help="Language server to use (python, go, typescript, etc.)"
)
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

    lsp_params = params or "{}"

    result = call_mcp_tool(
        "raw_lsp_request",
        {
            "workspace_root": str(workspace_root),
            "method": method,
            "params": lsp_params,
            "language": language,
        },
    )
    click.echo(result)


if __name__ == "__main__":
    cli()
