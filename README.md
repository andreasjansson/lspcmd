# leta - LSP Enabled Tools for Agents

leta is a command-line LSP client for semantic code navigation. It provides
fast symbol search, reference finding, call hierarchy analysis, and refactoring
operations by leveraging language server protocols across multiple programming
languages.

```
$ leta grep "Handler$" -k class
src/handlers/auth.py:15 [Class] AuthHandler
src/handlers/user.py:22 [Class] UserHandler
src/handlers/admin.py:8 [Class] AdminHandler

$ leta show UserHandler
src/handlers/user.py:22-67

class UserHandler:
    def __init__(self, db: Database):
        self.db = db

    def get_user(self, user_id: int) -> User:
        return self.db.query(User).get(user_id)
    ...
```

## Table of contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Commands](#commands)
  - [grep](#grep)
  - [files](#files)
  - [show](#show)
  - [refs](#refs)
  - [calls](#calls)
  - [implementations](#implementations)
  - [supertypes / subtypes](#supertypes--subtypes)
  - [declaration](#declaration)
  - [rename](#rename)
  - [mv](#mv)
- [Symbol formats](#symbol-formats)
- [Daemon management](#daemon-management)
- [Workspace management](#workspace-management)
- [Configuration](#configuration)
- [Supported languages](#supported-languages)
- [Development](#development)
- [License](#license)

## Installation

```bash
# Install with uv (recommended)
uv tool install -e . --python 3.13

# Or with pip
pip install -e .
```

Ensure you have language servers installed for your target languages:

```bash
# Python
npm install -g @anthropic/basedpyright

# TypeScript/JavaScript
npm install -g typescript-language-server typescript

# Go
go install golang.org/x/tools/gopls@latest

# Rust
rustup component add rust-analyzer

# Ruby
gem install ruby-lsp

# C/C++
brew install llvm  # macOS
apt install clangd  # Ubuntu
```

## Quick start

Initialize a workspace before using leta:

```bash
cd /path/to/your/project
leta workspace add
```

Search for symbols:

```bash
leta grep "User"               # Find symbols matching "User"
leta grep "^Test" -k function  # Find test functions
```

Show symbol definitions:

```bash
leta show UserRepository           # Show full class body
leta show UserRepository.add_user  # Show method body
```

Find references:

```bash
leta refs validate_email      # Find all uses of validate_email
leta refs UserRepository -n 2 # With 2 lines of context
```

## Commands

### grep

Search for symbols by regex pattern. Unlike text search tools, `leta grep`
searches *symbol names* semantically—it finds function definitions, class
declarations, method names, etc.

```bash
leta grep PATTERN [PATH_REGEX] [OPTIONS]

Options:
  -k, --kind KIND       Filter by symbol kind (class, function, method, etc.)
  -x, --exclude PAT     Exclude files matching regex (repeatable)
  -d, --docs            Include documentation for each symbol
  -C, --case-sensitive  Case-sensitive matching
  --head N              Maximum results to return (default: 200)
```

The optional PATH_REGEX argument filters files by matching a regex against
the relative file path. This is simpler and more powerful than glob patterns.

Examples:

```bash
# Find all classes ending with "Handler"
leta grep "Handler$" -k class

# Find functions in Python files only
leta grep "validate" '\.py$' -k function

# Find symbols in a specific directory
leta grep "User" "models/"

# Find symbols in test files
leta grep "test" "test/"

# Search with documentation
leta grep "parse" -k function -d

# Exclude test files
leta grep "User" -x test -x mock
```

**When to use leta grep vs ripgrep:**

- Use `leta grep` for: finding symbol definitions, filtering by kind, getting
  semantic matches
- Use ripgrep for: searching file contents, string literals, comments,
  multi-word phrases

### files

Show source file tree with line counts.

```bash
leta files [PATH] [OPTIONS]

Options:
  -x, --exclude PAT  Exclude files matching regex (repeatable)
  -i, --include PAT  Include default-excluded dirs (repeatable)
  -f, --filter PAT   Only include files matching regex
```

Example output:

```
src
├── handlers
│   ├── auth.py (2.3KB, 89 lines, 1 class, 5 methods)
│   └── user.py (3.1KB, 112 lines, 2 classes, 8 methods)
├── models
│   └── user.py (1.8KB, 67 lines, 1 class, 4 methods)
└── main.py (845B, 32 lines, 2 functions)

4 files, 8.0KB, 300 lines
```

### show

Print the full definition of a symbol.

```bash
leta show SYMBOL [OPTIONS]

Options:
  -n, --context N  Lines of context around definition
  --head N         Maximum lines to show (default: 200)
```

Examples:

```bash
leta show UserRepository           # Show full class
leta show UserRepository.add_user  # Show method
leta show "*.py:User"              # Filter by file
leta show COUNTRY_CODES            # Multi-line constants work too
```

### refs

Find all references to a symbol.

```bash
leta refs SYMBOL [OPTIONS]

Options:
  -n, --context N  Lines of context around each reference
```

Examples:

```bash
leta refs UserRepository
leta refs validate_email -n 2
leta refs "models.py:User"
```

### calls

Show call hierarchy for a symbol.

```bash
leta calls [OPTIONS]

Options:
  --from SYMBOL    Show what SYMBOL calls (outgoing)
  --to SYMBOL      Show what calls SYMBOL (incoming)
  --max-depth N    Maximum recursion depth (default: 3)
  --include-non-workspace  Include stdlib/dependency calls
```

At least one of `--from` or `--to` is required. Use both to find a path.

Examples:

```bash
# What does main() call?
leta calls --from main

# What calls validate_email()?
leta calls --to validate_email

# Find call path from main to save
leta calls --from main --to save --max-depth 5
```

### implementations

Find implementations of an interface or abstract method.

```bash
leta implementations SYMBOL [OPTIONS]

Options:
  -n, --context N  Lines of context
```

Examples:

```bash
leta implementations Storage
leta implementations Storage.save
```

### supertypes / subtypes

Navigate type hierarchies.

```bash
leta supertypes SYMBOL  # Find parent types
leta subtypes SYMBOL    # Find child types
```

### declaration

Find the declaration of a symbol (useful for languages that separate
declaration from definition).

```bash
leta declaration SYMBOL [OPTIONS]
```

### rename

Rename a symbol across the entire workspace.

```bash
leta rename SYMBOL NEW_NAME
```

Examples:

```bash
leta rename old_function new_function
leta rename UserRepository.add_user insert_user
leta rename "user.py:User" Person
```

### mv

Move/rename a file and update all imports.

```bash
leta mv OLD_PATH NEW_PATH
```

Supported by: TypeScript, Rust, Python (via basedpyright).

Examples:

```bash
leta mv src/user.ts src/models/user.ts
leta mv lib/utils.rs lib/helpers.rs
```

## Symbol formats

Most commands accept symbols in these formats:

| Format | Description |
|--------|-------------|
| `SymbolName` | Find symbol by name |
| `Parent.Symbol` | Qualified name (Class.method, module.function) |
| `path:Symbol` | Filter by file path pattern |
| `path:Parent.Symbol` | Combine path filter with qualified name |
| `path:line:Symbol` | Exact file + line number (for edge cases) |

Examples:

```bash
leta show UserRepository            # By name
leta show UserRepository.add_user   # Qualified
leta show "*.py:User"               # Path filter
leta show "models/user.py:User"     # Specific file
```

## Daemon management

leta runs a background daemon that manages LSP server connections. The daemon
starts automatically on first command and persists to make subsequent commands
fast.

```bash
leta daemon start    # Start daemon
leta daemon stop     # Stop daemon
leta daemon restart  # Restart daemon
leta daemon info     # Show daemon status and active workspaces
```

## Workspace management

Workspaces must be explicitly added before using leta:

```bash
leta workspace add              # Add current directory (interactive)
leta workspace add --root /path # Add specific path
leta workspace remove           # Remove current workspace
leta workspace restart          # Restart language servers
```

## Configuration

Configuration is stored in `~/.config/leta/config.toml`:

```toml
[daemon]
log_level = "info"
request_timeout = 30
hover_cache_size = 268435456   # 256MB
symbol_cache_size = 268435456  # 256MB

[workspaces]
roots = ["/home/user/projects/myapp"]
excluded_languages = ["json", "yaml", "html"]

[formatting]
tab_size = 4
insert_spaces = true

[servers.python]
preferred = "basedpyright"
```

View configuration:

```bash
leta config
```

Logs are stored in `~/.cache/leta/log/`.

## Supported languages

| Language | Server | Install |
|----------|--------|---------|
| Python | basedpyright | `npm install -g @anthropic/basedpyright` |
| TypeScript/JavaScript | typescript-language-server | `npm install -g typescript-language-server typescript` |
| Go | gopls | `go install golang.org/x/tools/gopls@latest` |
| Rust | rust-analyzer | `rustup component add rust-analyzer` |
| Java | jdtls | `brew install jdtls` |
| Ruby | ruby-lsp | `gem install ruby-lsp` |
| C/C++ | clangd | `brew install llvm` |
| PHP | intelephense | `npm install -g intelephense` |
| Lua | lua-language-server | `brew install lua-language-server` |
| Zig | zls | `brew install zls` |

## Development

```bash
# Run unit tests
./script/unit-test

# Run corpus tests
./script/corpus-test

# Run linter
./script/lint

# Format code
./script/format
```

### Architecture

```
leta/
├── cli.py              # CLI entry point and argument parsing
├── cache.py            # LMDB-backed LRU cache
├── daemon/
│   ├── server.py       # Unix socket server
│   ├── session.py      # LSP session and workspace management
│   ├── rpc.py          # Request/response Pydantic models
│   └── handlers/       # Request handlers (grep, show, refs, etc.)
├── lsp/
│   ├── client.py       # LSP client with typed requests
│   ├── protocol.py     # JSON-RPC message encoding
│   ├── types.py        # LSP type definitions
│   └── capabilities.py # Client capability declarations
├── output/
│   └── formatters.py   # Output formatting (plain, JSON, tree)
├── servers/
│   └── registry.py     # Language server configurations
└── utils/
    ├── config.py       # Configuration loading/saving
    ├── text.py         # Language detection, file reading
    └── uri.py          # file:// URI handling
```

## License

MIT
