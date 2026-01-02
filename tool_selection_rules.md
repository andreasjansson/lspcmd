# ⚠️ STOP: READ THIS BEFORE USING ripgrep ⚠️

**MANDATORY RULE: When searching for functions, classes, methods, or any code symbol, you MUST use `lspcmd`, NOT ripgrep.**

This is NOT optional. Using ripgrep for symbol searches is ALWAYS WRONG.

## Quick Decision Guide

| Looking for... | Use THIS | NOT this |
|----------------|----------|----------|
| Function `is_excluded` | `lspcmd show is_excluded` | ~~`ripgrep "def is_excluded"`~~ |
| Function `handle_grep` | `lspcmd show handle_grep` | ~~`ripgrep "def handle_grep"`~~ |
| Class `UserService` | `lspcmd grep UserService -k class` | ~~`ripgrep "class UserService"`~~ |
| Method body | `lspcmd show ClassName.method` | ~~`ripgrep "def method"`~~ |
| All functions in file | `lspcmd grep "." file.py -k function` | ~~`ripgrep "def " file.py`~~ |
| Where symbol is used | `lspcmd refs symbol_name` | ~~`ripgrep "symbol_name"`~~ |

## THE RULE

```
IF searching for: function, method, class, struct, symbol, definition
THEN use: lspcmd (show, grep, refs, calls, implementations)
NEVER use: ripgrep
```

## Examples - WRONG vs RIGHT

### Finding a function definition
```bash
# WRONG - DO NOT DO THIS:
ripgrep "def is_excluded"
ripgrep "^def handle_"
ripgrep "func.*Handler"

# RIGHT - DO THIS INSTEAD:
lspcmd show is_excluded
lspcmd grep "handle_" -k function
lspcmd grep "Handler$" -k function
```

### Viewing a function body
```bash
# WRONG:
ripgrep -A 20 "def calculate_total"
read-file path/to/file.py --start-line 45 --end-line 60

# RIGHT:
lspcmd show calculate_total
lspcmd show OrderService.calculate_total
```

### Finding all usages of a symbol
```bash
# WRONG:
ripgrep "validate_email"
ripgrep "UserRepository"

# RIGHT:
lspcmd refs validate_email
lspcmd refs UserRepository
```

## When ripgrep IS appropriate (rare cases only)

- String literals: `ripgrep '"Connection refused"'`
- Comments/TODOs: `ripgrep "TODO|FIXME"`
- URLs: `ripgrep "https://api\.example\.com"`
- Non-code files: logs, configs, documentation

## Pre-flight Check

**BEFORE calling ripgrep, ask yourself:**
> "Am I looking for a function, class, method, or symbol name?"

If YES → **STOP** → Use lspcmd instead.
