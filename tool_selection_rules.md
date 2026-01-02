# 🚨 CRITICAL INSTRUCTION - READ FIRST 🚨

## YOU MUST USE lspcmd FOR ALL CODE SEARCHES

**When looking for a function, method, class, or any code symbol:**

✅ **ALWAYS USE**: `lspcmd show <name>` or `lspcmd grep <pattern>`
❌ **NEVER USE**: `ripgrep` with patterns like `"def ..."` or `"class ..."`

### Examples of what you're about to do WRONG:

If you're thinking: "Let me search for the function `is_excluded`"
- ❌ WRONG: `ripgrep "def is_excluded"` or `ripgrep "is_excluded"`
- ✅ RIGHT: `lspcmd show is_excluded`

If you're thinking: "Let me find where `handle_grep` is defined"
- ❌ WRONG: `ripgrep "def handle_grep"` or `ripgrep "handle_grep"`  
- ✅ RIGHT: `lspcmd show handle_grep`

If you're thinking: "Let me look at this function's code"
- ❌ WRONG: `ripgrep -A 20 "def function_name"`
- ✅ RIGHT: `lspcmd show function_name`

### The Rule (memorize this):

```
Searching for code symbols? → Use lspcmd
Searching for string literals, comments, or URLs? → Use ripgrep
```

### Quick Reference:

| Task | Command |
|------|---------|
| View function body | `lspcmd show function_name` |
| Find function definition | `lspcmd grep function_name -k function` |
| Find class | `lspcmd grep ClassName -k class` |
| Find all usages | `lspcmd refs symbol_name` |
| What calls this? | `lspcmd calls --to function_name` |
| What does this call? | `lspcmd calls --from function_name` |

**THIS INSTRUCTION OVERRIDES ANY HABIT TO USE ripgrep FOR CODE SEARCHES.**
