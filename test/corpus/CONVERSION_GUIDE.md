# Integration Test to Corpus Test Conversion Guide

This guide explains how to convert existing integration tests from `test/integration/test_*.py` to the corpus test format in `test/corpus/`.

## Overview

The corpus test format is inspired by tree-sitter's testing approach:
- Tests are plain text files with a simple format
- Each test has a name, command, and expected output
- Tests run the actual `leta` CLI, making them excellent documentation
- Multi-step tests (like rename, mv) can verify state changes using shell commands

## Conversion Workflow for Each Language

### Step 1: Read the Existing Test File COMPLETELY

**CRITICAL**: Read the ENTIRE existing test file first. Do not skim or skip tests.

```
leta show test/integration/test_<language>.py
```

Or if the file is large:
```
read-file test/integration/test_<language>.py
```

Make a mental note of:
- Every `def test_*` method
- What each test is checking
- The exact expected outputs
- Any edge cases or error conditions being tested

### Step 2: Set Up the Corpus Directory

1. Create the language directory if it doesn't exist:
```bash
mkdir -p test/corpus/<language>
```

2. Copy the fixture:
```bash
cp -r test/fixtures/<language>_project test/corpus/<language>/fixture
rm -rf test/corpus/<language>/fixture/.venv  # Remove any venv
```

3. Verify the fixture is complete:
```bash
ls -la test/corpus/<language>/fixture/
```

4. **Add the workspace to leta** (required for leta to index it):
```bash
cd test/corpus/<language>/fixture
leta workspace add --root $(pwd)
```

This step is essential - without it, leta won't know about the workspace and will either fail or search in the wrong directories.

### Step 3: Convert Each Test Methodically

For EACH test in the original file:

#### 3a. Understand What the Test Does

Read the test method. Identify:
- What leta command(s) it runs
- What parameters it uses
- What output it expects
- Why this test exists (what behavior is it verifying?)

#### 3b. Run the Command Manually

**IMPORTANT**: Don't just copy the expected output from the old test! Run the actual command:

```bash
cd test/corpus/<language>/fixture
leta <command> <args>
```

#### 3c. Verify the Output Makes Sense

**BE VIGILANT FOR BUGS!** Ask yourself:
- Does this output look correct?
- Are line numbers reasonable?
- Are symbol names correct?
- Is the output format consistent with other tests?
- If it's an error message, is it the RIGHT error?

**Red flags that indicate potential bugs:**
- Empty output when you expect results
- Line numbers that seem wrong
- Missing symbols that should be found
- Incorrect symbol kinds
- Garbled or truncated output
- Different results on repeated runs

If something looks wrong, investigate! You may have found a bug in leta.

#### 3d. Write the Corpus Test

Create or append to the appropriate `.txt` file:

```
==================
descriptive test name
==================
leta <command> <args>
---
<expected output exactly as produced>
```

### Step 4: Handle Multi-Step Tests (Mutations)

For tests that modify state (rename, mv):

1. **Verify state before** using shell commands (grep, cat, ls)
2. **Run the mutation** command
3. **Verify state after** 
4. **RESTORE STATE** so subsequent tests aren't affected

Example:
```
==================
check before rename
==================
grep "class OldName" file.py
---
class OldName:

==================
rename OldName to NewName
==================
leta rename OldName NewName
---
Renamed in 2 file(s):
  file.py
  consumer.py

==================
verify rename worked
==================
grep "class.*Name" file.py
---
class NewName:

==================
restore original name
==================
leta rename NewName OldName
---
Renamed in 2 file(s):
  file.py
  consumer.py
```

### Step 5: Run and Verify

Run the corpus tests for your language:

```bash
python -m test.corpus_runner <language> --sequential
```

If tests fail:
1. Check if the expected output in the corpus file is correct
2. Check if leta is producing wrong output (bug!)
3. Use `--update` ONLY if you're sure the actual output is correct

### Step 6: Compare Test Coverage

Verify you haven't missed any tests:

```bash
# Count original tests
grep -c "def test_" test/integration/test_<language>.py

# List corpus tests
python -m test.corpus_runner <language> --list
```

Make sure every original test has a corresponding corpus test.

## File Organization

**IMPORTANT: Each test case MUST have its own file with exactly ONE command/expectation pair.**

This rule makes tests:
- Easy to understand at a glance
- Simple to debug when they fail
- Trivial to update with `--update`

### Directory Structure

```
test/corpus/<language>/
├── fixture/                    # The test project files
├── grep_pattern.txt            # ONE test: grep with pattern
├── grep_kind_class.txt         # ONE test: grep filtering by class
├── grep_kind_function.txt      # ONE test: grep filtering by function
├── show_function.txt           # ONE test: show a function
├── show_with_context.txt       # ONE test: show with -n context
├── refs_basic.txt              # ONE test: basic references
├── calls_outgoing.txt          # ONE test: outgoing calls
├── declaration_not_supported.txt  # ONE test: error case
└── rename_class.txt            # EXCEPTION: multi-step mutation
```

### Example: Standard Test File

Each file has exactly one test block (`show_function.txt`):

```
==================
show function definition
==================
leta show create_sample_user
---
main.py:114-115

def create_sample_user() -> User:
    return User(name="John Doe", email="john@example.com", age=30)
```

### Exception: Mutating Commands

Tests for commands that **modify state** (rename, mv) are the **only exception**. These need multiple steps in a single file to:
1. Verify state before mutation
2. Run the mutation command
3. Verify state after mutation
4. **Restore state** so the test can run again

Example from Python corpus (`rename_class.txt`):

```
==================
check class exists before rename
==================
grep "class.*Person" editable.py
---
class EditablePerson:

==================
rename EditablePerson to RenamedPerson
==================
leta rename EditablePerson RenamedPerson
---
Renamed in 2 file(s):
  editable_consumer.py
  editable.py

==================
verify class was renamed
==================
grep "class.*Person" editable.py
---
class RenamedPerson:

==================
verify import was updated
==================
grep "from editable import" editable_consumer.py
---
from editable import RenamedPerson, editable_create_sample
```

Example from Python corpus (`mv_file.txt`):

```
==================
check import before move
==================
grep "from editable import" editable_consumer.py
---
from editable import EditablePerson, editable_create_sample

==================
move file and update imports
==================
leta mv editable.py editable_renamed.py
---
Moved file and updated imports in 2 file(s):
  editable_consumer.py
  editable_renamed.py

==================
verify import was updated
==================
grep "from editable_renamed import" editable_consumer.py
---
from editable_renamed import EditablePerson, editable_create_sample

==================
restore file back
==================
leta mv editable_renamed.py editable.py
---
Moved file and updated imports in 2 file(s):
  editable_consumer.py
  editable.py

==================
verify import was restored
==================
grep "from editable import" editable_consumer.py
---
from editable import EditablePerson, editable_create_sample
```

Note how the mv test explicitly restores the file so the test is idempotent.

## Common Patterns

### Testing Error Messages

```
==================
error when symbol not found
==================
leta show NonExistentSymbol
---
Error: Symbol 'NonExistentSymbol' not found
```

### Testing Disambiguation

```
==================
ambiguous symbol shows options
==================
leta show save
---
Error: Symbol 'save' is ambiguous (3 matches)
  Class1.save
    file1.py:10 [Method] save in Class1
  Class2.save
    file2.py:20 [Method] save in Class2
  Class3.save
    file3.py:30 [Method] save in Class3
```

### Testing with Filters

```
==================
grep with kind filter
==================
leta grep . --kind function
---
file.py:10 [Function] func1
file.py:20 [Function] func2
```

### Testing Context Lines

```
==================
show with context
==================
leta show MyFunc -n 2
---
file.py:8-14

# preceding context

def MyFunc():
    pass

# following context
```

## Language-Specific Notes

### Python
- Uses basedpyright
- Subtypes/supertypes NOT supported
- Implementations work via Protocol

### Go
- Uses gopls
- Has good type hierarchy support
- Interface implementations work well

### TypeScript
- Uses typescript-language-server
- Good rename support
- Watch for node_modules issues

### Java
- Uses jdtls
- Needs .classpath/.project files
- Slower startup

### Rust
- Uses rust-analyzer
- Needs Cargo.toml
- Good trait implementation support

### C++
- Uses clangd
- Needs compile_commands.json
- Header/source separation matters

## Canonical Test Cases

Every language should have the following test cases. Some may have different expected outputs (e.g., error messages for unsupported features), but every language needs a test file for each case.

### grep tests
| File | Description |
|------|-------------|
| `grep_pattern.txt` | Filter symbols by regex pattern |
| `grep_kind_class.txt` | Filter by kind (class/struct) |
| `grep_kind_function.txt` | Filter by kind (function) |
| `grep_case_sensitive.txt` | Case-sensitive matching (finds match) |
| `grep_case_insensitive.txt` | Case-insensitive matching (default) |
| `grep_combined_filters.txt` | Pattern + kind filter together |
| `grep_multiple_files.txt` | Glob pattern for multiple files |
| `grep_workspace_wide.txt` | Search entire workspace |
| `grep_exclude.txt` | Exclude pattern |
| `grep_exclude_multiple.txt` | Multiple exclude patterns |
| `grep_with_docs.txt` | Include documentation |

### show tests
| File | Description |
|------|-------------|
| `show_function.txt` | Show function/method definition |
| `show_class.txt` | Show class/struct definition |
| `show_with_context.txt` | Show with `-n` context lines |
| `show_multiline_var.txt` | Multi-line variable/constant |

### refs tests
| File | Description |
|------|-------------|
| `refs_basic.txt` | Find all references |
| `refs_with_context.txt` | References with context lines |

### implementations tests
| File | Description |
|------|-------------|
| `implementations_basic.txt` | Find implementations of interface/protocol |
| `implementations_with_context.txt` | Implementations with context lines |

### calls tests
| File | Description |
|------|-------------|
| `calls_outgoing.txt` | Outgoing calls from function |
| `calls_incoming.txt` | Incoming calls to function |
| `calls_path.txt` | Find call path between functions |
| `calls_path_not_found.txt` | Call path not found |
| `calls_include_non_workspace.txt` | Include stdlib/external calls |
| `calls_excludes_stdlib.txt` | Verify stdlib excluded by default |

### resolve_symbol tests
| File | Description |
|------|-------------|
| `resolve_symbol_unique.txt` | Resolve unique symbol |
| `resolve_symbol_ambiguous.txt` | Ambiguous symbol shows matches |
| `resolve_symbol_qualified.txt` | Container.name qualified lookup |
| `resolve_symbol_file_filter.txt` | file.ext:symbol filter |

### type hierarchy tests
| File | Description |
|------|-------------|
| `subtypes.txt` | Find subtypes (or `subtypes_not_supported.txt`) |
| `supertypes.txt` | Find supertypes (or `supertypes_not_supported.txt`) |

### declaration tests
| File | Description |
|------|-------------|
| `declaration.txt` | Find declaration (or `declaration_not_supported.txt`) |

### mutation tests (multi-step)
| File | Description |
|------|-------------|
| `rename.txt` | Rename symbol with verification and restore |
| `mv.txt` | Move file (or `mv_not_supported.txt`) |

### Language-specific tests

Some languages may have additional tests for language-specific features:
- Go: `resolve_symbol_value_receiver.txt` (method receivers)
- Go: `grep_kind_struct.txt`, `grep_kind_interface.txt`
- TypeScript: `grep_kind_interface.txt`
- etc.

## Checklist for Each Language

- [ ] Read entire original test file
- [ ] Create corpus directory structure
- [ ] Copy fixture (without .venv)
- [ ] Add workspace with `leta workspace add --root $(pwd)`
- [ ] Create ALL canonical test cases (see list above)
- [ ] Add language-specific tests as needed
- [ ] Verify outputs make sense (watch for bugs!)
- [ ] Handle mutation tests with state restoration
- [ ] Run corpus tests successfully
- [ ] Commit with descriptive message

## Running Tests

```bash
# Run single language
python -m test.corpus_runner <language>

# Run with verbose output
python -m test.corpus_runner <language> -v

# Run sequentially (for debugging)
python -m test.corpus_runner <language> --sequential

# Update expected outputs (USE WITH CAUTION)
python -m test.corpus_runner <language> --update

# List all tests
python -m test.corpus_runner <language> --list

# Run all languages in parallel
python -m test.corpus_runner
```

## After All Languages Converted

Once all languages are converted:

1. Run the full corpus test suite:
   ```bash
   ./script/corpus-test
   ```

2. Delete the old integration tests:
   ```bash
   rm test/integration/test_*.py
   rm test/integration/conftest.py
   ```

3. Update `./script/integration-test` to use corpus runner

4. Update CI configuration if needed
