# lspcmd

A command-line wrapper around LSP language servers, inspired by lsp-mode.el.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                           lspcmd CLI                                │
│  (User-facing commands: definition, rename, format, grep...)        │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                     MCP (Model Context Protocol)
                      HTTP Streamable Transport
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    lspcmd Daemon (MCP Server)                       │
│  - Exposes LSP functionality as MCP tools                           │
│  - Manages language server processes                                │
│  - Maintains open documents state                                   │
│  - Handles LSP initialization/shutdown                              │
│  - Caches workspace state                                           │
│  - Supports multiple servers per workspace (one per language)       │
│  - Accessible by external MCP clients (Claude Desktop, etc.)        │
└─────────────────────────────────────────────────────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
   ┌───────────────┐       ┌───────────────┐       ┌───────────────┐
   │  pyright LSP  │       │  rust-analyzer│       │    gopls      │
   │    Server     │       │    Server     │       │    Server     │
   └───────────────┘       └───────────────┘       └───────────────┘
```

The daemon exposes an MCP (Model Context Protocol) server that can be used by:
- The `lspcmd` CLI (the primary interface)
- Claude Desktop and other AI assistants
- Any MCP-compatible client

## Project Structure

```
lspcmd/
├── __init__.py
├── cli.py                   # Click CLI definitions for `lspcmd`
├── daemon_cli.py            # Entry point for `lspcmd-daemon`
├── daemon/
│   ├── __init__.py
│   ├── pidfile.py           # PID file management
│   ├── server.py            # Async daemon server (Unix socket) + request handlers
│   └── session.py           # Session state (workspaces, open docs)
├── lsp/
│   ├── __init__.py
│   ├── capabilities.py      # Client capabilities sent to servers
│   ├── client.py            # Async LSP client implementation
│   ├── protocol.py          # LSP base protocol (JSON-RPC over stdio)
│   └── types.py             # LSP type definitions (SymbolKind, etc.)
├── output/
│   ├── __init__.py
│   └── formatters.py        # Output formatting (plain text, JSON)
├── servers/
│   ├── __init__.py
│   └── registry.py          # Server configurations & detection
└── utils/
    ├── __init__.py
    ├── config.py            # Configuration management & workspace detection
    ├── text.py              # Text document utilities & language detection
    └── uri.py               # File URI handling
```

## Entry Points

Defined in `setup.py`:

```python
entry_points={
    "console_scripts": [
        "lspcmd=lspcmd.cli:cli",
        "lspcmd-daemon=lspcmd.daemon_cli:main",
    ],
}
```

## CLI Commands

### Workspace Management

| Command | Description |
|---------|-------------|
| `lspcmd workspace init [--root PATH]` | Initialize a workspace for LSP operations |
| `lspcmd workspace restart [PATH]` | Restart language servers for a workspace |
| `lspcmd daemon info` | Show daemon state: workspaces, servers, open documents |
| `lspcmd daemon shutdown` | Shutdown the daemon gracefully |
| `lspcmd config` | Print config file location and contents |

### Debugging

| Command | Description |
|---------|-------------|
| `lspcmd raw-lsp-request METHOD [PARAMS] [-l LANGUAGE]` | Send raw LSP request, get JSON response |

The `raw-lsp-request` command is useful for debugging LSP server behavior:
```bash
# Get raw document symbols
lspcmd raw-lsp-request textDocument/documentSymbol \
  '{"textDocument": {"uri": "file:///path/to/file.go"}}' -l go

# Query workspace symbols
lspcmd raw-lsp-request workspace/symbol '{"query": "Handler"}' -l typescript
```

### Navigation Commands

All navigation commands use symbol-based lookup:

| Command | Description |
|---------|-------------|
| `lspcmd show SYMBOL [-n CONTEXT]` | Show symbol definition (full body) |
| `lspcmd ref SYMBOL [-n CONTEXT]` | Find all references to a symbol |
| `lspcmd implementations SYMBOL [-n CONTEXT]` | Find implementations of interface/method |
| `lspcmd subtypes SYMBOL [-n CONTEXT]` | Find direct subtypes of a type |
| `lspcmd supertypes SYMBOL [-n CONTEXT]` | Find direct supertypes of a type |
| `lspcmd declaration SYMBOL [-n CONTEXT]` | Find declaration of a symbol |

#### Symbol Format

Symbols can be specified in several formats:

| Format | Example | Description |
|--------|---------|-------------|
| `Name` | `UserRepository` | Find symbol by name |
| `Parent.Name` | `UserRepository.save` | Find symbol in parent (class, module) |
| `path:Name` | `*.py:User` | Filter by file path pattern |
| `path:Parent.Name` | `user.py:User.save` | Combine path filter with qualified name |
| `path:line:Name` | `user.py:42:save` | Exact file + line + name (for edge cases) |

The parent hierarchy follows LSP document symbol containers:
- `module.Class.method.variable` (Python, TypeScript, etc.)
- `MemoryStorage.Save` matches Go method `(*MemoryStorage).Save`

When a symbol is ambiguous, lspcmd shows all matches with copy-pasteable references:

```
$ lspcmd show PredictionPayload
Error: Symbol 'PredictionPayload' is ambiguous (3 matches)
  internal_types.py:PredictionPayload
    mocks/web/internal_types.py:37 [Class] PredictionPayload
  prediction.go:PredictionPayload
    internal/predictions/prediction.go:205 [Struct] PredictionPayload
  TrainingPayload.PredictionPayload
    internal/predictions/training.go:72 [Field] PredictionPayload in TrainingPayload
```

Examples:
```bash
# Find definition by symbol name (shows full body)
lspcmd show UserRepository

# Find definition of a method within a class
lspcmd show UserRepository.add_user

# Filter by file pattern
lspcmd show "*.py:User"

# Find references to a symbol
lspcmd ref Counter.increment

# Rename a symbol across the workspace
lspcmd rename old_function_name new_name
```

### Diagnostics Commands

| Command | Description |
|---------|-------------|
| `lspcmd diagnostics [PATH] [-s SEVERITY]` | Show errors/warnings for a file or workspace |

When `PATH` is omitted, shows diagnostics for all files in the current workspace.
The `-s/--severity` option filters by minimum severity level (error, warning, info, hint).

Examples:
```bash
lspcmd diagnostics                        # All diagnostics in workspace
lspcmd diagnostics src/main.py            # Single file
lspcmd diagnostics -s error               # Errors only (no warnings)
lspcmd --json diagnostics                 # JSON output
```

### Symbol Commands

| Command | Description |
|---------|-------------|
| `lspcmd grep PATTERN [PATH] [-k KIND] [-x EXCLUDE] [-d] [-C]` | Search symbols by regex pattern |

The `grep` command is the primary way to search symbols. All filtering is done server-side in the daemon for performance:
- `PATTERN`: Regex matched against symbol names (case-insensitive by default)
- `PATH`: Optional file path, directory, or glob pattern (e.g., `*.py`, `src/`, `src/**/*.go`, or bare filename like `server.py`)
- `-k/--kind`: Filter by kind (class, function, method, variable, etc.)
- `-x/--exclude`: Exclude files matching glob pattern or directory
- `-d/--docs`: Include documentation for each symbol (uses LRU cache for performance)
- `-C/--case-sensitive`: Case-sensitive pattern matching

Path patterns without a `/` are searched recursively (e.g., `server.py` finds `src/daemon/server.py`).
Directories are automatically expanded to include all files recursively (e.g., `src` becomes `src/**`).

Examples:
```bash
lspcmd grep "Test.*" "*.py" -k function      # Find test functions
lspcmd grep "^User" -k class                  # Find classes starting with User
lspcmd grep "Handler$" internal -d            # Find handlers with docs in internal/
lspcmd grep ".*" "*.go" -x tests              # All symbols excluding tests/ directory
lspcmd grep "." server.py                     # All symbols in any server.py file
```

### Code Actions

| Command | Description |
|---------|-------------|
| `lspcmd format PATH` | Format a file |
| `lspcmd organize-imports PATH` | Organize imports in a file |
| `lspcmd rename SYMBOL NEW_NAME` | Rename symbol across the workspace |
| `lspcmd move-file OLD_PATH NEW_PATH` | Move/rename file and update imports |
| `echo CONTENT \| lspcmd replace-function SYMBOL` | Replace function/method body |

The `replace-function` command reads new function contents from stdin and replaces
the existing function/method. By default, it validates that the function signature
matches (name and parameters). Use `--no-check-signature` to allow signature changes.

The command:
1. Resolves the symbol (same as `lspcmd show`)
2. Verifies it's a Function or Method
3. Creates a backup of the file (`.lspcmd.bkup`)
4. Replaces the function in the file
5. Asks the LSP server for the new signature via hover
6. If signature check fails, reverts to the backup
7. Cleans up the backup file

Examples:
```bash
# Replace a function with matching signature
echo 'def greet(name: str) -> str:
    return f"Hi, {name}!"' | lspcmd replace-function greet

# Replace a method in a class
echo '    def save(self, key: str, value: str) -> None:
        self._data[key] = value' | lspcmd replace-function MyClass.save

# Allow signature changes
echo 'func NewUser(name string) *User {
    return &User{Name: name}
}' | lspcmd replace-function NewUser --no-check-signature
```

The `move-file` command uses `workspace/willRenameFiles` to ask the language server
to update all import statements across the workspace. Supported by:
- **typescript-language-server**: Updates TypeScript/JavaScript imports
- **rust-analyzer**: Updates mod declarations
- **metals** (Scala): Updates imports

Servers that don't support this will just move the file without updating imports.

Examples:
```bash
# Traditional line,column format
lspcmd definition src/main.py 42,10

# Search for unique pattern on a specific line
lspcmd definition src/main.py "42:UserRepository"

# Search for unique pattern in the whole file
lspcmd definition src/main.py "class UserRepository:"

# Regex with special characters (escaped)
lspcmd definition src/main.py "def __init__\\(self\\)"

# Print full definition body
lspcmd show src/main.py "class UserRepository:"

# Print full definition body with 2 lines of context
lspcmd show src/main.py "class UserRepository:" -n 2
```

If a regex matches multiple times, you'll get a helpful error showing all locations:
```
Error: Pattern 'self' matches 15 times in file:
  line 13: def __init__(self):
  line 17: self._users[user.email] = user
  line 20: return self._users.get(email)
  ... and 12 more matches
Use LINE:REGEX or LINE,COLUMN to specify which one.
```

### Output Format

All commands support `--json` flag for JSON output:
```bash
lspcmd --json def UserRepository
```

## Daemon Methods

The CLI communicates with the daemon via JSON over Unix socket. Each CLI command maps to a daemon method:

| CLI Command | Daemon Method |
|-------------|---------------|
| `show` | `definition` |
| `declaration` | `declaration` |
| `ref` | `references` |
| `implementations` | `implementations` |
| `subtypes` | `subtypes` |
| `supertypes` | `supertypes` |
| `diagnostics` (single file) | `diagnostics` |
| `diagnostics` (workspace) | `workspace-diagnostics` |
| `grep` | `grep` |
| `format` | `format` |
| `organize-imports` | `organize-imports` |
| `rename` | `rename` |
| `move-file` | `move-file` |
| `replace-function` | `replace-function` |
| `daemon info` | `describe-session` |
| `daemon shutdown` | `shutdown` |
| `workspace restart` | `restart-workspace` |
| `raw-lsp-request` | `raw-lsp-request` |

## Configuration

### File Locations

| Path | Description |
|------|-------------|
| `~/.config/lspcmd/config.toml` | Configuration file |
| `~/.cache/lspcmd/mcp.port` | MCP server port file |
| `~/.cache/lspcmd/lspcmd.pid` | Daemon PID file |
| `~/.cache/lspcmd/log/daemon.log` | Daemon log file |
| `~/.cache/lspcmd/log/{server}.log` | Per-server log files |

Respects `XDG_CONFIG_HOME` and `XDG_CACHE_HOME` environment variables.

### MCP Server

The daemon exposes an MCP server on `http://127.0.0.1:<port>/mcp`. The port is
written to `~/.cache/lspcmd/mcp.port` when the daemon starts.

**Available MCP Tools:**

| Tool | Description |
|------|-------------|
| `grep` | Search for symbols matching a regex pattern |
| `show` | Print the definition of a symbol (full body) |
| `ref` | Find all references to a symbol |
| `implementations` | Find implementations of an interface |
| `subtypes` | Find direct subtypes of a type |
| `supertypes` | Find direct supertypes of a type |
| `declaration` | Find declaration of a symbol |
| `diagnostics` | Show diagnostics for a file or workspace |
| `rename` | Rename a symbol across the workspace |
| `move_file` | Move/rename a file and update imports |
| `replace_function` | Replace a function/method body with new contents |
| `format_file` | Format a file |
| `organize_imports` | Organize imports in a file |
| `tree` | Show source file tree with sizes |
| `daemon_info` | Show daemon state |
| `daemon_shutdown` | Shutdown the daemon |
| `workspace_restart` | Restart language servers |
| `raw_lsp_request` | Send raw LSP request (debugging) |

All tools accept an `output_format` parameter (`"plain"` or `"json"`).

### Configuration Options

```toml
[daemon]
log_level = "info"        # debug, info, warning, error
request_timeout = 30      # seconds

[workspaces]
roots = [                 # Registered workspace roots
    "/path/to/project1",
    "/path/to/project2",
]
excluded_languages = ["json", "yaml", "html"]  # Skip these for workspace symbols

[formatting]
tab_size = 4
insert_spaces = true

[servers.python]
preferred = "pyright"     # or "pylsp", "ruff-lsp"

[servers.rust]
preferred = "rust-analyzer"
```

### Workspace Root Detection

When a command targets a file, lspcmd determines the workspace root by:
1. Checking if file is under a known workspace root (from config)
2. Detecting via markers: `.git`, `pyproject.toml`, `Cargo.toml`, `package.json`, `go.mod`, etc.

Initialize a workspace with:
```bash
lspcmd workspace init --root=/path/to/project
# or interactively:
lspcmd workspace init
```

## Supported Language Servers

| Language | Server | Install Command |
|----------|--------|-----------------|
| Python | basedpyright | `npm install -g @anthropic/basedpyright` |
| Python | pylsp | `pip install python-lsp-server` |
| Python | ruff-lsp | `pip install ruff-lsp` |
| Rust | rust-analyzer | `rustup component add rust-analyzer` |
| TypeScript/JavaScript | typescript-language-server | `npm install -g typescript-language-server typescript` |
| Go | gopls | `go install golang.org/x/tools/gopls@latest` |
| C/C++ | clangd | (system package) |
| Java | jdtls | (manual install) |
| Ruby | solargraph | `gem install solargraph` |
| Elixir | elixir-ls | (manual install) |
| Haskell | haskell-language-server | `ghcup install hls` |
| OCaml | ocamllsp | `opam install ocaml-lsp-server` |
| Lua | lua-language-server | (manual install) |
| Zig | zls | (manual install) |
| YAML | yaml-language-server | `npm install -g yaml-language-server` |
| JSON | vscode-json-languageserver | `npm install -g vscode-langservers-extracted` |
| HTML | vscode-html-languageserver | `npm install -g vscode-langservers-extracted` |
| CSS | vscode-css-languageserver | `npm install -g vscode-langservers-extracted` |

## Development

### Setup

```bash
cd /path/to/lspcmd

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies with uv
uv pip install -e .

# Or with pip
pip install -e .
```

### Running Commands

```bash
# Activate the virtual environment first
source .venv/bin/activate

# Run lspcmd
lspcmd --help
lspcmd workspace init --root=.
lspcmd grep ".*" lspcmd/cli.py -k function

# Run the daemon directly (usually auto-started)
python -m lspcmd.daemon_cli
```

### Running Tests

```bash
source .venv/bin/activate

# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_cli.py -v

# Run with coverage
python -m pytest tests/ --cov=lspcmd --cov-report=term-missing

# Run only unit tests (fast, no LSP servers needed)
python -m pytest tests/ -v --ignore=tests/test_integration.py

# Run integration tests (requires language servers installed)
python -m pytest tests/test_integration.py -v
```

### Test Structure

```
tests/
├── conftest.py              # Pytest fixtures
├── fixtures/                # Test project fixtures
│   ├── python_project/
│   ├── go_project/
│   ├── rust_project/
│   ├── typescript_project/
│   ├── java_project/
│   └── multi_language_project/
├── test_cli.py              # CLI command tests
├── test_config.py           # Configuration tests
├── test_formatters.py       # Output formatter tests
├── test_integration.py      # Integration tests with real LSP servers
├── test_protocol.py         # LSP protocol tests
├── test_registry.py         # Server registry tests
├── test_text.py             # Text utility tests
└── test_uri.py              # URI handling tests
```

### Debugging

View daemon logs:
```bash
tail -f ~/.cache/lspcmd/log/daemon.log
```

View language server logs:
```bash
tail -f ~/.cache/lspcmd/log/pyright.log
tail -f ~/.cache/lspcmd/log/gopls.log
```

Restart with fresh state:
```bash
lspcmd daemon shutdown
rm -rf ~/.cache/lspcmd/
```

## Architecture Details

### Daemon Lifecycle

1. First CLI command checks for PID file
2. If no daemon or stale PID, spawns `lspcmd-daemon` in background
3. CLI connects via Unix socket
4. CLI sends JSON request, waits for JSON response
5. Daemon keeps running indefinitely, managing servers
6. User runs `lspcmd daemon shutdown` to stop daemon

### Session State

The daemon maintains:
- **Workspaces**: Keyed by root path, containing per-language servers
- **Open Documents**: Tracked with version numbers for sync (closed after symbol queries to keep servers responsive)
- **Server Capabilities**: Cached per workspace
- **Hover Cache**: LRU cache (50k entries) for `--docs` flag, keyed by (file_path, line, column, file_sha) for automatic invalidation on file changes

Multiple language servers can run simultaneously for the same workspace (e.g., pyright + gopls for a mixed Python/Go project).

### LSP Client Implementation

Key features:
- Async JSON-RPC over stdio
- Handles `Content-Length` headers per LSP spec
- Manages request IDs and pending responses
- Handles server-to-client requests (currently minimal)
- Careful capability negotiation to avoid blocking issues

### Important: Capability Negotiation

Some LSP capabilities cause servers to send requests to the client and block waiting for responses. The current `lspcmd/lsp/capabilities.py` is carefully curated to avoid these issues. Notable exclusions:
- `workspaceFolders: True` - causes pyright to block
- `window.workDoneProgress: True` - causes progress notifications
- `workspace.configuration: True` - requires handling config requests

## Known Limitations

1. **Workspace symbols with empty query**: Many LSP servers (pyright, gopls, rust-analyzer) don't return consistent results for `workspace/symbol` queries, especially with empty queries. The `grep` command uses `textDocument/documentSymbol` on each file instead, which provides reliable and complete results.

2. **No auto-installation**: Language servers must be installed manually. The registry provides install commands as hints.

3. **Single-user**: The daemon uses a Unix socket without authentication, suitable for single-user workstations.

4. **No incremental sync**: Document changes always send full content (simpler, works reliably for CLI use case).

5. **First `--docs` query is slow**: The hover cache starts empty, so the first `grep --docs` query fetches documentation for all symbols. Subsequent queries are fast (cache hit). The cache is invalidated per-file when file content changes (detected via SHA256 hash).
