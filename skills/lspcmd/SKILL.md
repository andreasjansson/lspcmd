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
| Use `read-file` with specific start and end line ranges in order to view a specific function | `lspcmd show <symbol_name>` |
| Use `read-file` to "browse" or "understand" a file | `lspcmd grep ".*" path/to/file -k function` to list functions, or `lspcmd show <symbol>` |
| Use ripgrep-like tools to find where a function is defined | `lspcmd grep "<function_name>" -k function` |
| Use ripgrep-like tools to find usages/references of a symbol | `lspcmd refs <symbol_name>` |
| Use ripgrep-like tools to find code related to a concept (e.g. "billing") | `lspcmd grep "<concept>" -k function` |
| Use `list-directory` to explore project structure | `lspcmd files` |
| Manually search for interface implementations | `lspcmd implementations <interface>` |
| Grep for function calls to trace code flow | `lspcmd calls --to/--from <function>` |
| Read a function's implementation to understand what it depends on | `lspcmd calls --from <function>` first for overview |
| Read multiple files to understand how functions connect | `lspcmd calls --from <function>` to see the call graph |

**The Golden Rule:** If you know the symbol name, **always** use lspcmd. Only use ripgrep when searching for things that aren't symbols (string literals, comments, config values).

**DON'T fall back to old habits.** If you know a symbol name, use lspcmd.

### ⚠️ Anti-pattern: "Browsing" Files

**Don't** read a whole file just "to understand it" or "see the context." This is a common mistake.

If you're tempted to do this, ask yourself: *What symbol am I actually looking for?* Then use:
- `lspcmd show <symbol>` if you know the symbol name
- `lspcmd grep ".*" path/to/file -k function` to see what functions exist in a file
- `lspcmd refs <symbol>` to find where something is used

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
- Searching for **literal strings in comments, docs, or config files** (not code)
- Multi-word phrase search in non-code content
- Searching for library/external symbols not defined in your code
- Pattern matching in string literals or configuration
- Searching in file types lspcmd doesn't understand (markdown, yaml, etc.)

**Don't use ripgrep-like tools for:**
- Finding where a function/class is defined → use `lspcmd grep`
- Finding where a symbol is used → use `lspcmd refs`
- Finding code related to a concept (e.g. "billing", "auth") → use `lspcmd grep "<concept>" -k function`

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

### `lspcmd refs` - Find All References ⭐ USE THIS INSTEAD OF RIPGREP FOR USAGES

**This is the correct way to find where a symbol is used.** Don't use ripgrep to search for a function name - use `lspcmd refs` instead. It understands code structure and won't give you false positives from comments or similarly-named symbols.

```bash
# Find all usages of a function
lspcmd refs validate_email

# Find with context lines
lspcmd refs UserRepository.save -n 2

# Find where a class is instantiated or referenced
lspcmd refs UserRepository
```

### `lspcmd calls` - Call Hierarchy ⭐ USE THIS TO UNDERSTAND FUNCTION DEPENDENCIES

**Before reading a function's implementation, use `calls` to get the architectural overview.** This shows you what a function depends on or what depends on it - much faster than reading code to figure out the call graph.

```bash
# What does main() call? (understand dependencies before reading code)
lspcmd calls --from main

# What calls validate_email()? (find all callers)
lspcmd calls --to validate_email

# Find path from one function to another
lspcmd calls --from main --to save_to_db

# Include stdlib/dependency calls
lspcmd calls --from process_request --include-non-workspace
```

**When to use `calls`:**
- You found a function and want to understand what it does at a high level → `--from`
- You want to know where/how a function is used → `--to`
- You're tracing data flow through a system → combine `--from` and `--to`
- You want to understand the architecture before diving into implementation details

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
# 1. Get the high-level overview: what does it call?
lspcmd calls --from process_request

# 2. Who calls this function?
lspcmd calls --to process_request

# 3. NOW read the implementation (with context from steps 1-2)
lspcmd show process_request

# 4. Find all usages/references
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

6. **Don't redirect stderr** (e.g., `2>/dev/null`) - when a symbol is ambiguous, lspcmd outputs disambiguation options to stderr showing how to qualify the symbol name. You need to see this to know how to fix the command.
