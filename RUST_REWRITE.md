# Leta Rust Rewrite Plan

This document outlines the architecture for rewriting leta from Python to Rust,
drawing inspiration from modern Rust tooling projects like `just`, `uv`, and
`ripgrep`.

## Goals

1. **Single binary distribution** - No Python runtime or language server
   installation required for the CLI itself
2. **Fast startup** - Sub-10ms cold start (vs ~200ms+ for Python)
3. **Memory efficient** - Tight control over allocations
4. **Parallel by default** - Leverage Rust's fearless concurrency
5. **Maintain feature parity** - All existing functionality preserved
6. **Clean, testable architecture** - Modular crates with clear boundaries

## Project Structure

Following `uv`'s multi-crate workspace pattern for clean separation:

```
leta/
├── Cargo.toml                 # Workspace manifest
├── crates/
│   ├── leta/                  # Main binary crate
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── main.rs        # Entry point
│   │       ├── cli.rs         # clap CLI definitions
│   │       ├── daemon.rs      # Daemon start/stop/communication
│   │       └── output.rs      # Output formatting dispatch
│   │
│   ├── leta-daemon/           # Daemon binary crate
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── main.rs
│   │       ├── server.rs      # Unix socket server
│   │       ├── session.rs     # LSP session management
│   │       └── handlers/      # Request handlers
│   │           ├── mod.rs
│   │           ├── grep.rs
│   │           ├── show.rs
│   │           ├── refs.rs
│   │           ├── calls.rs
│   │           ├── rename.rs
│   │           └── ...
│   │
│   ├── leta-lsp/              # LSP client library
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── client.rs      # Async LSP client
│   │       ├── protocol.rs    # JSON-RPC encoding/decoding
│   │       ├── types.rs       # LSP type definitions
│   │       └── capabilities.rs
│   │
│   ├── leta-types/            # Shared types and RPC models
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── rpc.rs         # Request/response types
│   │       ├── symbol.rs      # Symbol info types
│   │       └── location.rs    # Location types
│   │
│   ├── leta-config/           # Configuration management
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── config.rs      # Config loading/saving
│   │       ├── paths.rs       # XDG paths
│   │       └── workspace.rs   # Workspace detection
│   │
│   ├── leta-cache/            # Caching layer
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       └── lmdb.rs        # LMDB-backed cache
│   │
│   ├── leta-servers/          # Language server registry
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       └── registry.rs    # Server configs, detection
│   │
│   ├── leta-output/           # Output formatting
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── plain.rs       # Plain text output
│   │       ├── json.rs        # JSON output
│   │       └── tree.rs        # Tree formatting
│   │
│   └── leta-fs/               # File system utilities
│       ├── Cargo.toml
│       └── src/
│           ├── lib.rs
│           ├── text.rs        # Language detection
│           └── uri.rs         # file:// URI handling
│
├── tests/                     # Integration tests (cctr corpus)
│   └── corpus/
│       └── ... (same structure as Python)
│
└── script/
    ├── test
    ├── corpus-test
    └── install
```

## Core Crates

### `leta` (main binary)

The CLI entry point. Minimal logic—just argument parsing and dispatch to daemon.

Dependencies:
- `clap` for argument parsing
- `leta-types` for RPC types
- `leta-config` for configuration
- `leta-output` for formatting

### `leta-daemon`

The background daemon that manages LSP connections.

Dependencies:
- `tokio` for async runtime
- `leta-lsp` for LSP client
- `leta-types` for RPC
- `leta-cache` for caching
- `leta-servers` for server registry

### `leta-lsp`

Type-safe, async LSP client.

Key design decisions:
- Use `tower-lsp` patterns but implement from scratch for full control
- Strongly-typed request/response using Rust enums
- Connection pooling per workspace/server combination

### `leta-types`

Shared types used across crates. No external dependencies except `serde`.

### `leta-cache`

LMDB-backed LRU cache with type-safe keys.

Dependencies:
- `lmdb-rkv` or `heed` for LMDB bindings

## Key Crates/Dependencies

Based on analysis of `just`, `uv`, and `ripgrep`:

### CLI & Terminal

```toml
clap = { version = "4.5", features = ["derive", "env", "wrap_help"] }
anstream = "0.6"            # Colored output with auto-detection
owo-colors = "4"            # Color formatting
console = "0.16"            # Terminal utilities
indicatif = "0.18"          # Progress bars (if needed)
```

### Async Runtime

```toml
tokio = { version = "1.40", features = ["full", "fs", "io-util", "macros", "process", "rt-multi-thread", "signal", "sync"] }
tokio-util = { version = "0.7", features = ["compat", "io"] }
futures = "0.3"
async-trait = "0.1"
```

### Serialization

```toml
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
toml = { version = "0.9", features = ["fast_hash"] }
```

### Error Handling

```toml
thiserror = "2.0"
anyhow = "1.0"
miette = { version = "7.2", features = ["fancy-no-backtrace"] }  # Pretty errors
```

### File System

```toml
walkdir = "2.5"
ignore = "0.4"              # From ripgrep - .gitignore support
globset = "0.4"             # Glob matching
dunce = "1.0"               # Canonicalize paths on Windows
fs-err = { version = "3.0", features = ["tokio"] }  # Better error messages
tempfile = "3.14"
```

### Caching

```toml
heed = "0.21"               # LMDB bindings (type-safe)
blake3 = "1.5"              # Fast hashing for cache keys
```

### JSON-RPC / LSP

```toml
lsp-types = "0.97"          # LSP type definitions
# Or implement from scratch for full control
```

### Regex

```toml
regex = "1.10"
regex-automata = { version = "0.4", features = ["dfa-build", "dfa-search"] }
```

### Misc

```toml
tracing = "0.1"             # Structured logging
tracing-subscriber = "0.3"
rustc-hash = "2.0"          # Fast hash maps
dashmap = "6.1"             # Concurrent hash map
parking_lot = "0.12"        # Better mutexes
```

## Daemon Architecture

### Process Model

```
┌─────────────┐     Unix Socket     ┌──────────────────────────┐
│  leta CLI   │ ◄─────────────────► │     leta-daemon          │
│  (short)    │   JSON-RPC          │                          │
└─────────────┘                     │  ┌────────────────────┐  │
                                    │  │ Session Manager    │  │
                                    │  │                    │  │
                                    │  │  ┌──────────────┐  │  │
                                    │  │  │ Workspace 1  │  │  │
                                    │  │  │  ┌─────────┐ │  │  │
                                    │  │  │  │pyright  │ │  │  │
                                    │  │  │  └─────────┘ │  │  │
                                    │  │  │  ┌─────────┐ │  │  │
                                    │  │  │  │gopls    │ │  │  │
                                    │  │  │  └─────────┘ │  │  │
                                    │  │  └──────────────┘  │  │
                                    │  │  ┌──────────────┐  │  │
                                    │  │  │ Workspace 2  │  │  │
                                    │  │  │  ...         │  │  │
                                    │  │  └──────────────┘  │  │
                                    │  └────────────────────┘  │
                                    │                          │
                                    │  ┌────────────────────┐  │
                                    │  │ Symbol Cache       │  │
                                    │  │ (LMDB)            │  │
                                    │  └────────────────────┘  │
                                    │  ┌────────────────────┐  │
                                    │  │ Hover Cache        │  │
                                    │  │ (LMDB)            │  │
                                    │  └────────────────────┘  │
                                    └──────────────────────────┘
```

### Handler Design

Each handler is a standalone async function:

```rust
// crates/leta-daemon/src/handlers/grep.rs

use leta_types::{GrepParams, GrepResult, SymbolInfo};
use crate::context::HandlerContext;

pub async fn handle_grep(
    ctx: &HandlerContext,
    params: GrepParams,
) -> Result<GrepResult, Error> {
    let workspace_root = params.workspace_root.canonicalize()?;
    let regex = Regex::new(&params.pattern)?;
    
    let symbols = if let Some(paths) = params.paths {
        ctx.collect_symbols_for_paths(&paths, &workspace_root).await?
    } else {
        ctx.collect_all_workspace_symbols(&workspace_root).await?
    };
    
    let filtered: Vec<SymbolInfo> = symbols
        .into_par_iter()  // Parallel filtering
        .filter(|s| regex.is_match(&s.name))
        .filter(|s| params.kinds.as_ref().map_or(true, |k| k.contains(&s.kind)))
        .collect();
    
    Ok(GrepResult { symbols: filtered, warning: None })
}
```

## LSP Client Design

Type-safe LSP requests using Rust's type system:

```rust
// crates/leta-lsp/src/client.rs

pub struct LspClient {
    process: Child,
    stdin: ChildStdin,
    pending: DashMap<u64, oneshot::Sender<Value>>,
    request_id: AtomicU64,
    capabilities: ServerCapabilities,
}

impl LspClient {
    pub async fn definition(
        &self,
        params: TextDocumentPositionParams,
    ) -> Result<DefinitionResponse, LspError> {
        self.send_request("textDocument/definition", params).await
    }
    
    pub async fn references(
        &self,
        params: ReferenceParams,
    ) -> Result<Vec<Location>, LspError> {
        self.send_request("textDocument/references", params).await
    }
    
    // Generic typed request
    async fn send_request<P: Serialize, R: DeserializeOwned>(
        &self,
        method: &str,
        params: P,
    ) -> Result<R, LspError> {
        let id = self.request_id.fetch_add(1, Ordering::SeqCst);
        let (tx, rx) = oneshot::channel();
        
        self.pending.insert(id, tx);
        
        let msg = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params,
        });
        
        self.write_message(&msg).await?;
        
        let response = tokio::time::timeout(
            Duration::from_secs(30),
            rx
        ).await??;
        
        serde_json::from_value(response).map_err(Into::into)
    }
}
```

## Symbol Resolution

Port the disambiguation logic:

```rust
// crates/leta-daemon/src/handlers/resolve_symbol.rs

pub fn resolve_symbol(
    symbol_path: &str,
    all_symbols: &[SymbolInfo],
) -> Result<ResolvedSymbol, ResolveError> {
    let (path_filter, line_filter, name_parts) = parse_symbol_path(symbol_path)?;
    
    let mut candidates: Vec<&SymbolInfo> = all_symbols
        .iter()
        .filter(|s| matches_path_filter(s, path_filter.as_deref()))
        .filter(|s| matches_line_filter(s, line_filter))
        .filter(|s| matches_name(&s.name, &name_parts))
        .collect();
    
    match candidates.len() {
        0 => Err(ResolveError::NotFound(symbol_path.to_string())),
        1 => Ok(candidates.remove(0).into()),
        _ => {
            // Try to disambiguate by preferring types over variables
            let types: Vec<_> = candidates
                .iter()
                .filter(|s| PREFERRED_KINDS.contains(&s.kind))
                .collect();
            
            if types.len() == 1 {
                return Ok(types[0].clone().into());
            }
            
            Err(ResolveError::Ambiguous {
                symbol: symbol_path.to_string(),
                matches: candidates.iter().map(|s| generate_ref(s, &candidates)).collect(),
            })
        }
    }
}
```

## Testing Strategy

### Unit Tests

Inline in source files following Rust convention:

```rust
// crates/leta-lsp/src/protocol.rs

pub fn encode_message(msg: &Value) -> Vec<u8> {
    let content = serde_json::to_vec(msg).unwrap();
    let header = format!("Content-Length: {}\r\n\r\n", content.len());
    [header.as_bytes(), &content].concat()
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_encode_message() {
        let msg = json!({"jsonrpc": "2.0", "method": "test"});
        let encoded = encode_message(&msg);
        assert!(encoded.starts_with(b"Content-Length: "));
    }
    
    #[test]
    fn test_decode_roundtrip() {
        let original = json!({"id": 1, "result": null});
        let encoded = encode_message(&original);
        let decoded = decode_message(&mut &encoded[..]).unwrap();
        assert_eq!(original, decoded);
    }
}
```

### Integration Tests

Use cctr for corpus tests (same test files as Python):

```
tests/
└── corpus/
    └── languages/
        ├── python/
        │   ├── _setup.txt
        │   ├── grep_case_sensitive.txt
        │   └── fixture/
        │       └── ...
        ├── go/
        └── ...
```

Test file format unchanged:

```
===
grep case sensitive
===
leta grep "User" --case-sensitive
---
src/main.py:15 [Class] User
src/main.py:42 [Function] UserFactory
```

## Migration Plan

### Phase 1: Core Infrastructure

1. Set up workspace with all crates
2. Implement `leta-types` with all RPC models
3. Implement `leta-config` for configuration
4. Implement `leta-fs` for file utilities
5. Implement `leta-lsp` protocol layer

### Phase 2: Daemon

1. Implement `leta-daemon` server skeleton
2. Port session management
3. Port cache layer
4. Implement handlers one by one:
   - `grep` (validates symbol collection works)
   - `show` (validates definition lookup)
   - `refs` (validates references)
   - `calls` (validates call hierarchy)
   - `rename` (validates workspace edits)

### Phase 3: CLI

1. Implement `leta` CLI with clap
2. Unix socket communication
3. Output formatting
4. Daemon management commands

### Phase 4: Polish

1. Error messages and help text
2. Shell completions
3. Performance optimization
4. Binary distribution (cross-compile, releases)

## Performance Considerations

### Parallel Symbol Collection

```rust
use rayon::prelude::*;

async fn collect_all_workspace_symbols(
    &self,
    workspace_root: &Path,
) -> Result<Vec<SymbolInfo>> {
    let files = self.find_source_files(workspace_root);
    
    // Group files by language for batching
    let by_language = self.group_by_language(&files);
    
    // Process each language's files in parallel
    let results: Vec<_> = by_language
        .into_par_iter()
        .map(|(lang, files)| {
            let workspace = self.get_workspace_for_language(lang)?;
            files.par_iter()
                .filter_map(|f| self.get_file_symbols_cached(workspace, f).ok())
                .flatten()
                .collect::<Vec<_>>()
        })
        .collect();
    
    Ok(results.into_iter().flatten().collect())
}
```

### Zero-Copy Where Possible

Use `Cow<'a, str>` and borrowed references in hot paths:

```rust
pub struct SymbolInfo<'a> {
    pub name: Cow<'a, str>,
    pub kind: SymbolKind,
    pub path: &'a Path,
    pub line: u32,
    pub column: u32,
}
```

### Memory-Mapped File Reading

For large files in grep operations:

```rust
use memmap2::Mmap;

fn read_file_mmap(path: &Path) -> Result<Mmap> {
    let file = File::open(path)?;
    unsafe { Mmap::map(&file) }
}
```

## Binary Size Optimization

Release profile optimizations (from `uv`):

```toml
[profile.release]
strip = true
lto = "fat"
codegen-units = 1
opt-level = "z"  # For minimal size
panic = "abort"
```

Expected binary size: ~5-10MB (vs ~30MB for Python+dependencies).

## Distribution

### Single Binary

Build statically-linked binaries for each platform:

```bash
# Linux (musl for static linking)
cargo build --release --target x86_64-unknown-linux-musl

# macOS
cargo build --release --target x86_64-apple-darwin
cargo build --release --target aarch64-apple-darwin

# Windows
cargo build --release --target x86_64-pc-windows-msvc
```

### Installation

```bash
# Cargo (for Rust users)
cargo install leta

# Homebrew
brew install leta

# Direct download
curl -fsSL https://github.com/your/leta/releases/download/v0.1.0/leta-$(uname -s)-$(uname -m) -o leta
chmod +x leta
```

## Timeline Estimate

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Phase 1 | 2 weeks | Core crates, LSP protocol |
| Phase 2 | 3 weeks | Working daemon with all handlers |
| Phase 3 | 1 week | CLI and output formatting |
| Phase 4 | 1 week | Polish, testing, distribution |

**Total: ~7 weeks** for feature parity with Python implementation.

## Risks and Mitigations

### Risk: LSP Type Complexity

LSP has many optional fields and union types. Mitigation:
- Use `lsp-types` crate as reference
- Define only types we actually use
- Liberal use of `Option<T>` and `#[serde(default)]`

### Risk: Platform-Specific Behavior

Unix sockets don't exist on Windows. Mitigation:
- Use named pipes on Windows
- Abstract via `leta-daemon` crate's platform module
- Follow `just`'s platform abstraction pattern

### Risk: Language Server Quirks

Each LSP server has quirks. Mitigation:
- Port all existing workarounds from Python
- Maintain comprehensive test corpus
- Server-specific handling in `leta-servers` crate
