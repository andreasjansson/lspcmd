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
        assert lowercase_output == ""

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
        response = run_request("show", {
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
        response = run_request("show", {
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
        response = run_request("show", {
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

    def test_definition_with_body_and_context(self, workspace):
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "src" / "main.ts"),
            "workspace_root": str(workspace),
            "line": 58,
            "column": 18,
            "context": 1,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:5-9

 */
function createSampleUser(): User {
    return new User("John Doe", "john@example.com", 30);
}
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

    def test_references_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 13,
            "context": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:3-5
 */
export class User {
    constructor(

src/user.ts:29-31
export interface Storage {
    save(user: User): void;
    load(email: string): User | undefined;

src/user.ts:30-32
    save(user: User): void;
    load(email: string): User | undefined;
    delete(email: string): boolean;

src/user.ts:32-34
    delete(email: string): boolean;
    list(): User[];
}

src/user.ts:39-41
export class MemoryStorage implements Storage {
    private users: Map<string, User> = new Map();


src/user.ts:41-43

    save(user: User): void {
        this.users.set(user.email, user);

src/user.ts:45-47

    load(email: string): User | undefined {
        return this.users.get(email);

src/user.ts:53-55

    list(): User[] {
        return Array.from(this.users.values());

src/user.ts:62-64
export class FileStorage implements Storage {
    private cache: Map<string, User> = new Map();


src/user.ts:70-72

    save(user: User): void {
        // Stub: just cache in memory

src/user.ts:75-77

    load(email: string): User | undefined {
        return this.cache.get(email);

src/user.ts:83-85

    list(): User[] {
        return Array.from(this.cache.values());

src/user.ts:94-96

    addUser(user: User): void {
        this.storage.save(user);

src/user.ts:98-100

    getUser(email: string): User | undefined {
        return this.storage.load(email);

src/user.ts:106-108

    listUsers(): User[] {
        return this.storage.list();

src/user.ts:118-120
 */
export function validateUser(user: User): string | null {
    if (!user.name) {

src/main.ts:1-2
import { User, UserRepository, MemoryStorage, validateUser } from './user';


src/main.ts:5-7
 */
function createSampleUser(): User {
    return new User("John Doe", "john@example.com", 30);

src/main.ts:6-8
function createSampleUser(): User {
    return new User("John Doe", "john@example.com", 30);
}
"""

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
    # rename tests (uses isolated editable files)
    # =========================================================================

    def test_rename(self, workspace):
        os.chdir(workspace)
        
        editable_path = workspace / "src" / "editable.ts"
        consumer_path = workspace / "src" / "editable_consumer.ts"
        original_editable = editable_path.read_text()
        original_consumer = consumer_path.read_text()
        
        try:
            assert "export class EditablePerson {" in original_editable
            assert "import { EditablePerson," in original_consumer
            
            response = run_request("rename", {
                "path": str(editable_path),
                "workspace_root": str(workspace),
                "line": 11,
                "column": 13,
                "new_name": "RenamedPerson",
            })
            output = format_output(response["result"], "plain")
            lines = output.strip().split("\n")
            assert lines[0] == "Renamed in 2 file(s):"
            files_renamed = {line.strip() for line in lines[1:]}
            assert files_renamed == {"src/editable.ts", "src/editable_consumer.ts"}

            renamed_editable = editable_path.read_text()
            renamed_consumer = consumer_path.read_text()
            assert "export class RenamedPerson {" in renamed_editable
            assert "export class EditablePerson {" not in renamed_editable
            assert "import { RenamedPerson," in renamed_consumer
            assert "import { EditablePerson," not in renamed_consumer
        finally:
            editable_path.write_text(original_editable)
            consumer_path.write_text(original_consumer)

    # =========================================================================
    # move-file tests (uses isolated editable files)
    # =========================================================================

    def test_move_file_updates_imports(self, workspace):
        os.chdir(workspace)
        
        editable_path = workspace / "src" / "editable.ts"
        consumer_path = workspace / "src" / "editable_consumer.ts"
        models_dir = workspace / "src" / "models"
        moved_editable_path = models_dir / "editable.ts"
        
        original_editable = editable_path.read_text()
        original_consumer = consumer_path.read_text()
        
        try:
            models_dir.mkdir(exist_ok=True)
            
            assert "from './editable'" in original_consumer
            
            response = run_request("move-file", {
                "old_path": str(editable_path),
                "new_path": str(moved_editable_path),
                "workspace_root": str(workspace),
            })
            output = format_output(response["result"], "plain")
            
            assert not editable_path.exists()
            assert moved_editable_path.exists()
            
            assert output == """\
Moved file and updated imports in 2 file(s):
  src/editable_consumer.ts
  src/models/editable.ts"""
            
            updated_consumer = consumer_path.read_text()
            assert "from './models/editable'" in updated_consumer
        finally:
            if moved_editable_path.exists():
                moved_editable_path.unlink()
            if models_dir.exists() and not any(models_dir.iterdir()):
                models_dir.rmdir()
            editable_path.write_text(original_editable)
            consumer_path.write_text(original_consumer)

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

    # =========================================================================
    # show multi-line constant tests
    # =========================================================================

    def test_show_multiline_object_constant(self, workspace):
        """Test that show displays multi-line object constants correctly."""
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 135,
            "column": 13,
            "context": 0,
            "body": True,
            "direct_location": True,
            "range_start_line": 135,
            "range_end_line": 143,
            "kind": "Constant",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:135-143

export const COUNTRY_CODES: Record<string, string> = {
    "US": "United States",
    "CA": "Canada",
    "GB": "United Kingdom",
    "DE": "Germany",
    "FR": "France",
    "JP": "Japan",
    "AU": "Australia",
};"""

    def test_show_multiline_array_constant(self, workspace):
        """Test that show displays multi-line array constants correctly."""
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 148,
            "column": 13,
            "context": 0,
            "body": True,
            "direct_location": True,
            "range_start_line": 148,
            "range_end_line": 153,
            "kind": "Constant",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:148-153

export const DEFAULT_CONFIG: string[] = [
    "debug=false",
    "timeout=30",
    "max_retries=3",
    "log_level=INFO",
];"""

    # =========================================================================
    # calls tests
    # =========================================================================

    def test_calls_outgoing(self, workspace):
        """Test outgoing calls from createSampleUser (only calls User)."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "outgoing",
            "from_path": str(workspace / "src" / "main.ts"),
            "from_line": 6,
            "from_column": 9,
            "from_symbol": "createSampleUser",
            "max_depth": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:6 [Function] createSampleUser

Outgoing calls:
  └── src/user.ts:4 [Class] User"""

    def test_calls_incoming(self, workspace):
        """Test incoming calls to createSampleUser function."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "incoming",
            "to_path": str(workspace / "src" / "main.ts"),
            "to_line": 6,
            "to_column": 9,
            "to_symbol": "createSampleUser",
            "max_depth": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:6 [Function] createSampleUser

Incoming calls:
  └── src/main.ts:55 [Function] main"""

    def test_calls_outgoing_include_non_workspace(self, workspace):
        """Test outgoing calls with --include-non-workspace shows stdlib calls."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "outgoing",
            "from_path": str(workspace / "src" / "main.ts"),
            "from_line": 13,
            "from_column": 9,
            "from_symbol": "processUsers",
            "max_depth": 1,
            "include_non_workspace": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:13 [Function] processUsers

Outgoing calls:
  ├── [Method] map
  ├── src/user.ts:107 [Method] listUsers (UserRepository)
  └── src/user.ts:21 [Method] displayName (User)"""

    def test_calls_outgoing_excludes_stdlib_by_default(self, workspace):
        """Test outgoing calls without --include-non-workspace excludes stdlib."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "outgoing",
            "from_path": str(workspace / "src" / "main.ts"),
            "from_line": 13,
            "from_column": 9,
            "from_symbol": "processUsers",
            "max_depth": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:13 [Function] processUsers

Outgoing calls:
  ├── src/user.ts:107 [Method] listUsers (UserRepository)
  └── src/user.ts:21 [Method] displayName (User)"""
