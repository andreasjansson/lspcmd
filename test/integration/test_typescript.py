import os
import shutil
import time

import pytest

from lspcmd.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
    _call_replace_function_request,
    format_output,
    requires_typescript_lsp,
    run_request,
)


class TestTypeScriptIntegration:
    """Integration tests for TypeScript using typescript-language-server."""

    @pytest.fixture(autouse=True)
    def check_typescript_lsp(self):
        requires_typescript_lsp()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "typescript_project"
        dst = class_temp_dir / "typescript_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("grep", {
            "paths": [str(project / "src" / "main.ts")],
            "workspace_root": str(project),
            "pattern": ".*",
        })
        time.sleep(1.0)
        return project

    # =========================================================================
    # grep tests
    # =========================================================================

    def test_grep_pattern_filter(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["class", "interface"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:62 [Class] FileStorage
src/user.ts:39 [Class] MemoryStorage
src/user.ts:29 [Interface] Storage"""

    def test_grep_kind_filter_class(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:62 [Class] FileStorage
src/user.ts:39 [Class] MemoryStorage
src/user.ts:4 [Class] User
src/user.ts:92 [Class] UserRepository"""

    def test_grep_kind_filter_interface(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["interface"],
        })
        output = format_output(response["result"], "plain")
        assert output == "src/user.ts:29 [Interface] Storage"

    def test_grep_case_sensitive(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": "^User$",
            "case_sensitive": False,
        })
        insensitive_output = format_output(response["result"], "plain")
        assert insensitive_output == "src/user.ts:4 [Class] User"
        
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": "^user$",
            "case_sensitive": True,
        })
        lowercase_output = format_output(response["result"], "plain")
        assert lowercase_output == "No results"

    def test_grep_combined_filters(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:62 [Class] FileStorage
src/user.ts:39 [Class] MemoryStorage"""

    def test_grep_multiple_files(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main.ts"), str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": "^validate",
            "case_sensitive": False,
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:20 [Function] validateEmail
src/user.ts:119 [Function] validateUser"""

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": "validate",
            "case_sensitive": False,
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:20 [Function] validateEmail
src/user.ts:119 [Function] validateUser"""

    def test_grep_exclude_pattern(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        all_output = format_output(response["result"], "plain")
        assert all_output == """\
src/main.ts:6 [Function] createSampleUser
src/main.ts:55 [Function] main
src/main.ts:75 [Function] names.forEach() callback in main
src/main.ts:13 [Function] processUsers
src/main.ts:14 [Function] map() callback in processUsers
src/main.ts:20 [Function] validateEmail
src/errors.ts:36 [Function] callError
src/errors.ts:17 [Function] missingReturn
src/errors.ts:27 [Function] propertyError
src/errors.ts:32 [Function] twoArgs
src/errors.ts:11 [Function] typeError
src/errors.ts:6 [Function] undefinedVariable
src/user.ts:119 [Function] validateUser"""
        
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
            "exclude_patterns": ["errors.ts"],
        })
        filtered_output = format_output(response["result"], "plain")
        assert filtered_output == """\
src/main.ts:6 [Function] createSampleUser
src/main.ts:55 [Function] main
src/main.ts:75 [Function] names.forEach() callback in main
src/main.ts:13 [Function] processUsers
src/main.ts:14 [Function] map() callback in processUsers
src/main.ts:20 [Function] validateEmail
src/user.ts:119 [Function] validateUser"""

    def test_grep_with_docs(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main.ts")],
            "workspace_root": str(workspace),
            "pattern": "^createSampleUser$",
            "kinds": ["function"],
            "include_docs": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:6 [Function] createSampleUser
    ```typescript
    function createSampleUser(): User
    ```
    Creates a sample user for testing.
"""

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main.ts"),
            "workspace_root": str(workspace),
            "line": 58,
            "column": 18,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "src/main.ts:6 function createSampleUser(): User {"

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main.ts"),
            "workspace_root": str(workspace),
            "line": 58,
            "column": 18,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:6-8

function createSampleUser(): User {
    return new User("John Doe", "john@example.com", 30);
}"""

    def test_definition_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main.ts"),
            "workspace_root": str(workspace),
            "line": 58,
            "column": 18,
            "context": 1,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:5-7
 */
function createSampleUser(): User {
    return new User("John Doe", "john@example.com", 30);
"""

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 13,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:4 export class User {
src/user.ts:30     save(user: User): void;
src/user.ts:31     load(email: string): User | undefined;
src/user.ts:33     list(): User[];
src/user.ts:40     private users: Map<string, User> = new Map();
src/user.ts:42     save(user: User): void {
src/user.ts:46     load(email: string): User | undefined {
src/user.ts:54     list(): User[] {
src/user.ts:63     private cache: Map<string, User> = new Map();
src/user.ts:71     save(user: User): void {
src/user.ts:76     load(email: string): User | undefined {
src/user.ts:84     list(): User[] {
src/user.ts:95     addUser(user: User): void {
src/user.ts:99     getUser(email: string): User | undefined {
src/user.ts:107     listUsers(): User[] {
src/user.ts:119 export function validateUser(user: User): string | null {
src/main.ts:1 import { User, UserRepository, MemoryStorage, validateUser } from './user';
src/main.ts:6 function createSampleUser(): User {
src/main.ts:7     return new User("John Doe", "john@example.com", 30);"""

    # =========================================================================
    # implementations tests
    # =========================================================================

    def test_implementations_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 29,
            "column": 17,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:39 export class MemoryStorage implements Storage {
src/user.ts:62 export class FileStorage implements Storage {"""

    def test_implementations_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 29,
            "column": 17,
            "context": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:38-40
 */
export class MemoryStorage implements Storage {
    private users: Map<string, User> = new Map();

src/user.ts:61-63
 */
export class FileStorage implements Storage {
    private cache: Map<string, User> = new Map();
"""

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        os.chdir(workspace)
        response = run_request("describe", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 13,
        })
        output = format_output(response["result"], "plain")
        assert output == """\

```typescript
class User
```
Represents a user in the system."""

    # =========================================================================
    # rename tests
    # =========================================================================

    def test_rename(self, workspace):
        os.chdir(workspace)
        
        # Save original content for restoration
        user_ts_path = workspace / "src" / "user.ts"
        main_ts_path = workspace / "src" / "main.ts"
        original_user_ts = user_ts_path.read_text()
        original_main_ts = main_ts_path.read_text()
        
        try:
            # Verify User class exists before rename
            assert "export class User {" in original_user_ts
            assert "import { User," in original_main_ts
            
            response = run_request("rename", {
                "path": str(user_ts_path),
                "workspace_root": str(workspace),
                "line": 4,
                "column": 13,
                "new_name": "Person",
            })
            output = format_output(response["result"], "plain")
            # TypeScript renames in both user.ts and main.ts (order may vary)
            lines = output.strip().split("\n")
            assert lines[0] == "Renamed in 2 file(s):"
            files_renamed = {line.strip() for line in lines[1:]}
            assert files_renamed == {"src/main.ts", "src/user.ts"}

            # Verify rename actually happened in the files
            renamed_user_ts = user_ts_path.read_text()
            renamed_main_ts = main_ts_path.read_text()
            assert "export class Person {" in renamed_user_ts
            assert "export class User {" not in renamed_user_ts
            assert "import { Person," in renamed_main_ts
            assert "import { User," not in renamed_main_ts
        finally:
            # Always restore original content
            user_ts_path.write_text(original_user_ts)
            main_ts_path.write_text(original_main_ts)

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "errors.ts"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "errors.ts" in output
        assert "error" in output.lower()

    def test_diagnostics_undefined_variable(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "errors.ts"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "undefinedVar" in output or "Cannot find name" in output

    def test_diagnostics_type_error(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "errors.ts"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        has_type_error = "number" in output.lower() and "string" in output.lower()
        assert has_type_error, f"Expected type error in output: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_updates_imports(self, workspace):
        os.chdir(workspace)
        
        # Save original state for restoration
        user_ts_path = workspace / "src" / "user.ts"
        main_ts_path = workspace / "src" / "main.ts"
        models_dir = workspace / "src" / "models"
        moved_user_ts_path = models_dir / "user.ts"
        
        original_user_ts = user_ts_path.read_text()
        original_main_ts = main_ts_path.read_text()
        
        try:
            # Create a subdirectory to move the file into
            models_dir.mkdir(exist_ok=True)
            
            # Check initial import in main.ts
            assert "from './user'" in original_main_ts
            
            # Move user.ts to models/user.ts
            response = run_request("move-file", {
                "old_path": str(user_ts_path),
                "new_path": str(moved_user_ts_path),
                "workspace_root": str(workspace),
            })
            output = format_output(response["result"], "plain")
            
            # Verify the file was moved
            assert not user_ts_path.exists()
            assert moved_user_ts_path.exists()
            
            # Check exact output - TypeScript updates imports
            assert output == """\
Moved file and updated imports in 2 file(s):
  src/main.ts
  src/models/user.ts"""
            
            # Check that imports were updated in main.ts
            updated_main = main_ts_path.read_text()
            assert "from './models/user'" in updated_main
        finally:
            # Always restore original state
            if moved_user_ts_path.exists():
                moved_user_ts_path.unlink()
            if models_dir.exists() and not any(models_dir.iterdir()):
                models_dir.rmdir()
            user_ts_path.write_text(original_user_ts)
            main_ts_path.write_text(original_main_ts)

    # =========================================================================
    # replace-function tests
    # =========================================================================

    def test_replace_function_basic(self, workspace):
        """Test basic function replacement with matching signature."""
        os.chdir(workspace)
        
        main_path = workspace / "src" / "main.ts"
        original = main_path.read_text()
        
        try:
            response = _call_replace_function_request({
                "workspace_root": str(workspace),
                "symbol": "createSampleUser",
                "new_contents": '''function createSampleUser(): User {
    return new User("Jane Doe", "jane@example.com", 25);
}''',
                "check_signature": True,
            })
            result = response["result"]
            assert result["replaced"] == True
            assert "main.ts" in result["path"]
            
            updated = main_path.read_text()
            assert 'Jane Doe' in updated
            assert 'jane@example.com' in updated
        finally:
            main_path.write_text(original)

    def test_replace_function_signature_mismatch(self, workspace):
        """Test that signature mismatch is detected."""
        os.chdir(workspace)
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "createSampleUser",
            "new_contents": '''function createSampleUser(extra: string): User {
    return new User("Jane Doe", "jane@example.com", 25);
}''',
            "check_signature": True,
        })
        result = response["result"]
        assert "error" in result
        assert "Signature mismatch" in result["error"]

    def test_replace_function_no_check_signature(self, workspace):
        """Test that check_signature=False allows signature changes."""
        os.chdir(workspace)
        
        main_path = workspace / "src" / "main.ts"
        original = main_path.read_text()
        
        try:
            response = _call_replace_function_request({
                "workspace_root": str(workspace),
                "symbol": "createSampleUser",
                "new_contents": '''function createSampleUser(name: string = "Default"): User {
    return new User(name, "default@example.com", 30);
}''',
                "check_signature": False,
            })
            result = response["result"]
            assert result["replaced"] == True
            
            updated = main_path.read_text()
            assert 'name: string = "Default"' in updated
        finally:
            main_path.write_text(original)

    def test_replace_function_non_function_error(self, workspace):
        """Test that replacing a non-function symbol gives an error."""
        os.chdir(workspace)
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "User",
            "new_contents": '''class User {
}''',
            "check_signature": True,
        })
        result = response["result"]
        assert "error" in result
        assert "not a Function or Method" in result["error"]

    def test_replace_function_bogus_content_reverts(self, workspace):
        """Test that bogus content that fails signature check reverts the file."""
        os.chdir(workspace)
        
        main_path = workspace / "src" / "main.ts"
        original = main_path.read_text()
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "createSampleUser",
            "new_contents": "this is not valid typescript @#$%^&*()",
            "check_signature": True,
        })
        result = response["result"]
        assert "error" in result
        
        # Verify file was reverted
        current = main_path.read_text()
        assert current == original
        
        # Verify no backup file left behind
        backup_path = main_path.with_suffix(".ts.lspcmd.bkup")
        assert not backup_path.exists()

    def test_replace_function_symbol_not_found(self, workspace):
        """Test error when symbol doesn't exist."""
        os.chdir(workspace)
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "nonexistentFunction",
            "new_contents": "function nonexistentFunction() {}",
            "check_signature": True,
        })
        result = response["result"]
        assert "error" in result
        assert "not found" in result["error"]

    # =========================================================================
    # resolve-symbol disambiguation tests
    # =========================================================================

    def test_resolve_symbol_unique_name(self, workspace):
        """Test resolving a unique symbol name."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "Counter",
        })
        result = response["result"]
        assert result["name"] == "Counter"
        assert result["kind"] == "Class"

    def test_resolve_symbol_ambiguous_shows_container_refs(self, workspace):
        """Test that ambiguous TypeScript symbols show Class.method format."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "save",
        })
        result = response["result"]
        assert result["error"] == "Symbol 'save' is ambiguous (3 matches)"
        assert result["total_matches"] == 3
        refs = [m["ref"] for m in result["matches"]]
        assert refs == ["FileStorage.save", "MemoryStorage.save", "Storage.save"]

    def test_resolve_symbol_class_method(self, workspace):
        """Test resolving Class.method format."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "Counter.increment",
        })
        result = response["result"]
        assert result["name"] == "increment"
        assert result["kind"] == "Method"

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "main.ts:createSampleUser",
        })
        result = response["result"]
        assert result["name"] == "createSampleUser"
        assert result["path"].endswith("main.ts")
