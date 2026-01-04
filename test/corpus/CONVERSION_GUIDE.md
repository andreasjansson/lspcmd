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

Group related tests into files:
- `grep.txt` - All grep/search tests
- `show.txt` - Symbol display tests
- `refs.txt` - Reference finding tests
- `calls.txt` - Call hierarchy tests
- `rename.txt` - Rename refactoring tests (mutation)
- `mv.txt` - Move file tests (mutation)
- `implementations.txt` - Interface implementation tests
- `types.txt` - Type hierarchy tests (subtypes/supertypes)
- `errors.txt` - Error handling tests

Or combine small related groups:
- `grep_basic.txt`, `grep_filters.txt`, `grep_docs.txt`

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

## Checklist for Each Language

- [ ] Read entire original test file
- [ ] Create corpus directory structure
- [ ] Copy fixture (without .venv)
- [ ] Convert each test methodically
- [ ] Verify outputs make sense (watch for bugs!)
- [ ] Handle mutation tests with state restoration
- [ ] Run corpus tests successfully
- [ ] Verify test count matches original
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
