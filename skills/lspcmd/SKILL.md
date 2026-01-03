---
name: lspcmd
description: Use lspcmd for semantic code navigation using Language Server Protocol. PREFERRED over ripgrep for finding symbol definitions, references, implementations, and call hierarchies. Use when exploring code structure, finding where functions/classes are defined, tracing call flows, or performing semantic refactoring. Also PREFERRED over list-directory for listing files. Load this skill as soon as you want to list files or explore code.
---

# lspcmd - Command Line LSP Client

lspcmd provides semantic code navigation using Language Server Protocol. Unlike text-based search tools, lspcmd understands code structure and can find symbol definitions, references, implementations, and more.

## ⚠️ STOP AND THINK - Default to lspcmd

After loading this skill, **lspcmd should be your DEFAULT tool for code exploration**, not ripgrep-like tools or file reading.

**Before you act, check this list:**

| If you're about to... | STOP! Instead use... |
|----------------------|---------------------|
| Use `read-file` to view a function/class you know the name of | `lspcmd show <symbol_name>` |
| Use ripgrep-like tools to find where a function is defined | `lspcmd grep "<function_name>" -k function` |
| Use ripgrep-like tools to find usages of a symbol | `lspcmd refs <symbol_name>` |
| Use `list-directory` to explore project structure | `lspcmd files` |
| Manually search for interface implementations | `lspcmd implementations <interface>` |
| Grep for function calls to trace code flow | `lspcmd calls --to/--from <function>` |

**DON'T fall back to old habits.** If you know a symbol name, use lspcmd.

## When to Use lspcmd vs ripgrep-like tools

**Use lspcmd for:**
- Finding where a function/class/method is DEFINED
- Finding all USAGES of a symbol
- Understanding call hierarchies (what calls what)
- Finding interface implementations
- Semantic refactoring (rename symbol across codebase)
- Exploring project structure with symbol information
- Viewing a symbol's implementation when you know its name

**Use ripgrep-like tools for:**
- Searching string literals, comments, or documentation
- Multi-word phrase search
- Searching for library/external symbols not defined in your code
- Pattern matching across file contents
- Searching for concepts/keywords (not symbol names)

## Quick Start

Before using lspcmd on a new project, add it as a workspace:

```bash
lspcmd workspace add --root /path/to/project
```

## Core Commands

### `lspcmd show` - View Symbol Definition ⭐ USE THIS INSTEAD OF READ-FILE

**This is the killer feature you should use constantly.** Print the full body of a function, class, or method. ALWAYS use this instead of `read-file` when you know the symbol name.

```bash
# Show a function
lspcmd show handle_request

# Show a method on a class
lspcmd show UserRepository.add_user

# Show with surrounding context
lspcmd show parse_config -n 5

# Limit output length
lspcmd show COUNTRY_CODES --head 50
```

**Symbol formats:**
- `SymbolName` - Find by name
- `Parent.Symbol` - Qualified name (Class.method)
- `path:Symbol` - Filter by file path
- `path:Parent.Symbol` - Path + qualified name

### `lspcmd grep` - Find Symbol Definitions

Search for symbols matching a regex pattern. Only searches symbol NAMES, not file contents. Use this instead of ripgrep-like tools when looking for where something is defined.

```bash
# Find all functions starting with "test"
lspcmd grep "^test" -k function

# Find a class and show its documentation
lspcmd grep "UserRepository" -k class -d

# Find all methods in a specific file
lspcmd grep ".*" src/server.py -k method

# Find public Go functions (capitalized)
lspcmd grep "^[A-Z]" "*.go" -k function -C
```

**Options:**
- `-k, --kind TEXT` - Filter by kind: class, function, method, variable, constant, interface, struct, enum, property, field, constructor, module, namespace, package, typeparameter
- `-d, --docs` - Include documentation/docstrings
- `-x, --exclude TEXT` - Exclude files/directories (repeatable)
- `-C, --case-sensitive` - Case-sensitive matching. Note that `lspcmd grep` is case-insensitive by default

### `lspcmd files` - Project Overview

Show source file tree with symbol and line counts. Good starting point for exploring a project. **Always prefer `lspcmd files` over `list-directory`-like tools** since it prints not just the filenames, but a full tree of files (excluding `.git`, `__pycache__`, etc.), and their sizes and line counts. If you believe this command will output too many tokens, you can pipe it through `| head -n1000` for example.

```bash
# Overview of entire project
lspcmd files

# Only show src/ directory
lspcmd files src/

# Exclude test directories
lspcmd files -x tests -x vendor
```

### `lspcmd refs` - Find All References

Find everywhere a symbol is used across the codebase.

```bash
# Find all usages of a function
lspcmd refs validate_email

# Find with context lines
lspcmd refs UserRepository.save -n 2
```

### `lspcmd calls` - Call Hierarchy

Trace what a function calls or what calls it.

```bash
# What does main() call?
lspcmd calls --from main

# What calls validate_email()?
lspcmd calls --to validate_email

# Find path from one function to another
lspcmd calls --from main --to save_to_db

# Include stdlib/dependency calls
lspcmd calls --from process_request --include-non-workspace
```

### `lspcmd implementations` - Find Implementations

Find all implementations of an interface or abstract method.

```bash
# Find all classes implementing Storage interface
lspcmd implementations Storage

# Find implementations of a specific method
lspcmd implementations Validator.validate
```

### `lspcmd supertypes` / `lspcmd subtypes` - Type Hierarchy

Navigate class inheritance.

```bash
# What does this class extend/implement?
lspcmd supertypes MyDatabaseStorage

# What classes extend this one?
lspcmd subtypes BaseHandler
```

### `lspcmd declaration` - Find Declaration

Find where a symbol is declared (useful for variables, parameters).

```bash
lspcmd declaration config_path
```

## Refactoring Commands

### `lspcmd rename` - Rename Symbol

Rename a symbol across the entire workspace. Updates all references.

```bash
# Rename a function
lspcmd rename old_function_name new_function_name

# Rename a method
lspcmd rename UserRepository.add_user create_user
```

### `lspcmd mv` - Move File and Update Imports

Move/rename a file and update all import statements.

```bash
lspcmd mv src/user.ts src/models/user.ts
```

## Common Workflows

### Exploring Unfamiliar Code

```bash
# 1. Get project overview
lspcmd files

# 2. Find main entry points
lspcmd grep "^main$\|^Main$" -k function

# 3. Trace what main calls
lspcmd calls --from main --max-depth 2

# 4. Find key classes
lspcmd grep "Repository$\|Service$\|Handler$" -k class -d
```

### Understanding a Function

```bash
# 1. See the implementation
lspcmd show process_request

# 2. Find all callers
lspcmd calls --to process_request

# 3. See what it calls
lspcmd calls --from process_request

# 4. Find all usages
lspcmd refs process_request
```

### Finding Interface Implementations

```bash
# 1. Find the interface
lspcmd grep "Storage" -k interface -d

# 2. Find all implementations
lspcmd implementations Storage

# 3. Look at a specific implementation
lspcmd show FileStorage
```

## Tips

1. **Start with `lspcmd files`** to understand project structure before diving in.

2. **Use `-d` flag** with grep to see documentation - helps understand what symbols do.

3. **Combine with ripgrep-like tools** - use lspcmd for "where is X defined/used?" and ripgrep-like tools for "where does string Y appear?"

4. **Symbol formats are flexible** - if `SymbolName` is ambiguous, qualify it with `path:Symbol` or `Parent.Symbol`.

5. **Check workspace first** - if commands fail, ensure you've run `lspcmd workspace add`.
