## lspcmd Integration Test Coverage by Language

| Command | Python | Go | Rust | TypeScript | Java | C++ | Zig | Lua | Ruby | PHP |
|---------|:------:|:--:|:----:|:----------:|:----:|:---:|:---:|:---:|:----:|:---:|
| **grep** | | | | | | | | | | |
| └ single file | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| └ pattern filter | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| └ kind filter | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| └ case sensitive | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | | | |
| └ combined filters | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | | | |
| └ multiple files | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | | | |
| └ workspace-wide | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | | | |
| └ exclude pattern | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | | | |
| └ with docs | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | | | |
| **show (definition)** | | | | | | | | | | |
| └ basic | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| └ with context | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | | | |
| └ with body | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️¹ | ✅ |
| └ body + context | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | | | |
| **ref (references)** | | | | | | | | | | |
| └ basic | ✅ | ✅ | ✅ | ✅ | ✅ | ✅² | ✅ | ✅ | ✅ | ✅ |
| └ with context | ✅ | ✅ | ✅ | ✅ | ✅ | | | | | |
| **implementations** | | | | | | | | | | |
| └ basic | ✅ | ✅ | | ✅ | ✅ | ✅ | | | | ⚠️³ |
| └ with context | | ✅ | | ✅ | | | | | | |
| **subtypes** | ❌⁴ | | | | | | | | | |
| **supertypes** | ❌⁴ | ❌⁵ | | | | | | | | |
| **describe (hover)** | ✅ | ✅ | | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **diagnostics** | | | | | | | | | | |
| └ single file | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| └ undefined var | ✅ | ✅ | | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| └ type error | ✅ | ✅ | | ✅ | ✅ | ✅ | ✅ | | | ✅ |
| └ workspace-wide | | | ✅ | | | | | | | |
| **rename** | ✅ | ✅ | ✅ | ✅ | | ✅ | | | | |
| **move-file** | ✅ | ❌⁶ | ✅ | ✅ | ✅ | ❌⁶ | ❌⁶ | ❌⁶ | ❌⁶ | ❌⁶ |
| **replace-function** | | | | | | | | | | |
| └ basic | ✅ | ✅ | | ✅ | | | | | | |
| └ sig mismatch | ✅ | ✅ | | ✅ | | | | | | |
| └ no-check-sig | ✅ | ✅ | | ✅ | | | | | | |
| └ method replace | ✅ | | | | | | | | | |
| └ non-func error | ✅ | ✅ | | ✅ | | | | | | |
| └ revert on error | ✅ | ✅ | | ✅ | | | | | | |
| └ symbol not found | ✅ | ✅ | | ✅ | | | | | | |
| └ empty content | ✅ | | | | | | | | | |
| **resolve-symbol** | | | | | | | | | | |
| └ unique name | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| └ ambiguous refs | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | | | ✅ |
| └ qualified name | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | ⚠️⁷ | ✅ |
| └ file filter | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | |

### Legend
- ✅ = Tested and working
- ❌ = Tested, not supported by LSP server
- ⚠️ = Limited/partial support
- (blank) = Not tested

### Notes
1. **Ruby show body**: Solargraph doesn't provide symbol ranges needed for body extraction
2. **C++ references**: Uses set comparison instead of exact string match due to non-deterministic ordering from clangd
3. **PHP implementations**: Intelephense requires a license for implementation lookup
4. **Python subtypes/supertypes**: basedpyright doesn't support `prepareTypeHierarchy`
5. **Go declaration**: gopls doesn't support `textDocument/declaration`
6. **move-file not supported**: These LSP servers don't implement `workspace/willRenameFiles`
7. **Ruby qualified name**: Solargraph may not index instance methods with `Class.method` notation

### Multi-Language Project Tests
There's also a `TestMultiLanguageIntegration` class that tests:
- Python grep in mixed project ✅
- Go grep in mixed project ✅
- Both languages workspace-wide search ✅

### Test Count Summary
- **Total tests**: 238 (all passing)
- **Languages with full grep coverage**: Python, Go, Rust, TypeScript, Java, C++
- **Languages with full definition coverage**: Python, Go, Rust, TypeScript, Java, C++
- **Languages with references context**: Python, Go, Rust, TypeScript, Java
