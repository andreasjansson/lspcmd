import os
import shutil
import time

import click
import pytest

from lspcmd.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
    _call_replace_function_request,
    format_output,
    requires_gopls,
    run_request,
)


class TestGoIntegration:
    """Integration tests for Go using gopls."""

    @pytest.fixture(autouse=True)
    def check_gopls(self):
        requires_gopls()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "go_project"
        dst = class_temp_dir / "go_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("grep", {
            "paths": [str(project / "main.go")],
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
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": "^New",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:16 [Function] NewUser (func(name, email string, age int) *User)
main.go:44 [Function] NewMemoryStorage (func() *MemoryStorage)
main.go:90 [Function] NewFileStorage (func(basePath string) *FileStorage)
main.go:124 [Function] NewUserRepository (func(storage Storage) *UserRepository)"""

    def test_grep_kind_filter_struct(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["struct"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:9 [Struct] User (struct{...})
main.go:39 [Struct] MemoryStorage (struct{...})
main.go:85 [Struct] FileStorage (struct{...})
main.go:119 [Struct] UserRepository (struct{...})"""

    def test_grep_kind_filter_interface(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["interface"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:31 [Interface] Storage (interface{...})
main.go:154 [Interface] Validator (interface{...})"""

    def test_grep_case_sensitive(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": "user",
            "case_sensitive": False,
        })
        insensitive_output = format_output(response["result"], "plain")
        
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": "user",
            "case_sensitive": True,
        })
        sensitive_output = format_output(response["result"], "plain")
        
        assert "User" in insensitive_output
        assert "NewUser" in insensitive_output
        assert "User" not in sensitive_output
        assert "user" in sensitive_output.lower()

    def test_grep_combined_filters(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["struct"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:39 [Struct] MemoryStorage (struct{...})
main.go:85 [Struct] FileStorage (struct{...})"""

    def test_grep_multiple_files(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.go"), str(workspace / "utils.go")],
            "workspace_root": str(workspace),
            "pattern": "^New",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert "main.go" in output
        assert "utils.go" in output
        assert "NewUser" in output
        assert "NewCounter" in output

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": "Validate",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert "ValidateEmail" in output
        assert "ValidateAge" in output
        assert "ValidateUser" in output

    def test_grep_exclude_pattern(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        all_output = format_output(response["result"], "plain")
        
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
            "exclude_patterns": ["utils.go"],
        })
        filtered_output = format_output(response["result"], "plain")
        
        assert "utils.go" in all_output
        assert "utils.go" not in filtered_output
        assert "main.go" in filtered_output

    def test_grep_with_docs(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": "^NewUser$",
            "kinds": ["function"],
            "include_docs": True,
        })
        output = format_output(response["result"], "plain")
        assert "NewUser" in output
        assert "creates a new User instance" in output.lower() or "func NewUser" in output

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 174,
            "column": 9,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "main.go:124 func NewUserRepository(storage Storage) *UserRepository {"

    def test_definition_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 174,
            "column": 9,
            "context": 1,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:123-125
// NewUserRepository creates a new repository with the given storage.
func NewUserRepository(storage Storage) *UserRepository {
\treturn &UserRepository{storage: storage}
"""

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 174,
            "column": 9,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:124-126

func NewUserRepository(storage Storage) *UserRepository {
\treturn &UserRepository{storage: storage}
}"""

    def test_definition_with_body_and_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 174,
            "column": 9,
            "context": 1,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:123-127

// NewUserRepository creates a new repository with the given storage.
func NewUserRepository(storage Storage) *UserRepository {
\treturn &UserRepository{storage: storage}
}
"""

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:9 type User struct {
main.go:16 func NewUser(name, email string, age int) *User {
main.go:17 \treturn &User{Name: name, Email: email, Age: age}
main.go:21 func (u *User) IsAdult() bool {
main.go:26 func (u *User) DisplayName() string {
main.go:32 \tSave(user *User) error
main.go:33 \tLoad(email string) (*User, error)
main.go:35 \tList() ([]*User, error)
main.go:40 \tusers map[string]*User
main.go:45 \treturn &MemoryStorage{users: make(map[string]*User)}
main.go:49 func (m *MemoryStorage) Save(user *User) error {
main.go:58 func (m *MemoryStorage) Load(email string) (*User, error) {
main.go:76 func (m *MemoryStorage) List() ([]*User, error) {
main.go:77 \tresult := make([]*User, 0, len(m.users))
main.go:95 func (f *FileStorage) Save(user *User) error {
main.go:101 func (f *FileStorage) Load(email string) (*User, error) {
main.go:113 func (f *FileStorage) List() ([]*User, error) {
main.go:129 func (r *UserRepository) AddUser(user *User) error {
main.go:134 func (r *UserRepository) GetUser(email string) (*User, error) {
main.go:144 func (r *UserRepository) ListUsers() ([]*User, error) {
main.go:149 func createSampleUser() *User {
main.go:159 func ValidateUser(user *User) error {"""

    def test_references_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 124,
            "column": 5,
            "context": 1,
        })
        output = format_output(response["result"], "plain")
        assert "NewUserRepository" in output
        assert "// NewUserRepository creates a new repository" in output

    # =========================================================================
    # implementations tests
    # =========================================================================

    def test_implementations_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 31,
            "column": 5,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:39 type MemoryStorage struct {
main.go:85 type FileStorage struct {"""

    def test_implementations_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 31,
            "column": 5,
            "context": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:38-40
// MemoryStorage stores users in memory.
type MemoryStorage struct {
\tusers map[string]*User

main.go:84-86
// FileStorage stores users in files (stub implementation).
type FileStorage struct {
\tbasePath string
"""

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        os.chdir(workspace)
        response = run_request("describe", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
```go
type User struct { // size=40 (0x28), class=48 (0x30)
\tName  string
\tEmail string
\tAge   int
}
```

---

User represents a user in the system.


```go
func (u *User) DisplayName() string
func (u *User) IsAdult() bool
```"""

    # =========================================================================
    # rename tests
    # =========================================================================

    def test_rename(self, workspace):
        os.chdir(workspace)
        
        # Verify User struct exists before rename
        original_content = (workspace / "main.go").read_text()
        assert "type User struct" in original_content
        
        response = run_request("rename", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "new_name": "Person",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
Renamed in 1 file(s):
  main.go"""

        # Verify rename actually happened in the file
        renamed_content = (workspace / "main.go").read_text()
        assert "type Person struct" in renamed_content
        assert "type User struct" not in renamed_content

        # Revert the rename
        run_request("rename", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "new_name": "User",
        })
        
        # Verify revert worked
        reverted_content = (workspace / "main.go").read_text()
        assert "type User struct" in reverted_content
        assert "type Person struct" not in reverted_content

    # =========================================================================
    # declaration tests (gopls doesn't support this)
    # =========================================================================

    def test_declaration_not_supported(self, workspace):
        os.chdir(workspace)
        response = run_request("declaration", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 175,
            "column": 2,
            "context": 0,
        })
        assert "error" in response
        assert "textDocument/declaration" in response["error"]

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.go"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "errors.go" in output
        assert "error" in output.lower()

    def test_diagnostics_undefined_variable(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.go"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "undefinedVar" in output or "undefined" in output.lower()

    def test_diagnostics_type_error(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.go"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        lines = output.split("\n")
        has_type_error = any("int" in line and "string" in line for line in lines) or \
                        any("cannot" in line.lower() and "type" in line.lower() for line in lines) or \
                        any("convert" in line.lower() for line in lines)
        assert has_type_error, f"Expected type error in output: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_not_supported(self, workspace):
        os.chdir(workspace)
        
        response = run_request("move-file", {
            "old_path": str(workspace / "utils.go"),
            "new_path": str(workspace / "helpers.go"),
            "workspace_root": str(workspace),
        })
        assert "error" in response
        assert response["error"] == "move-file is not supported by gopls"
        
        # Verify file was NOT moved
        assert (workspace / "utils.go").exists()
        assert not (workspace / "helpers.go").exists()

    # =========================================================================
    # replace-function tests
    # =========================================================================

    def test_replace_function_basic(self, workspace):
        """Test basic function replacement with matching signature."""
        os.chdir(workspace)
        
        main_path = workspace / "main.go"
        original = main_path.read_text()
        
        try:
            response = _call_replace_function_request({
                "workspace_root": str(workspace),
                "symbol": "NewUser",
                "new_contents": '''func NewUser(name, email string, age int) *User {
	// Updated implementation
	return &User{Name: name, Email: email, Age: age}
}''',
                "check_signature": True,
            })
            result = response["result"]
            assert result["replaced"] == True
            assert result["path"] == "main.go"
            
            updated = main_path.read_text()
            assert '// Updated implementation' in updated
        finally:
            main_path.write_text(original)

    def test_replace_function_signature_mismatch(self, workspace):
        """Test that signature mismatch is detected."""
        os.chdir(workspace)
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "NewUser",
            "new_contents": '''func NewUser(name string) *User {
	return &User{Name: name, Email: "", Age: 0}
}''',
            "check_signature": True,
        })
        result = response["result"]
        assert "error" in result
        assert "Signature mismatch" in result["error"]

    def test_replace_function_no_check_signature(self, workspace):
        """Test that check_signature=False allows signature changes."""
        os.chdir(workspace)
        
        main_path = workspace / "main.go"
        original = main_path.read_text()
        
        try:
            response = _call_replace_function_request({
                "workspace_root": str(workspace),
                "symbol": "NewUser",
                "new_contents": '''func NewUser(name string) *User {
	return &User{Name: name, Email: "default@example.com", Age: 0}
}''',
                "check_signature": False,
            })
            result = response["result"]
            assert result["replaced"] == True
            
            updated = main_path.read_text()
            assert 'func NewUser(name string)' in updated
        finally:
            main_path.write_text(original)

    def test_replace_function_non_function_error(self, workspace):
        """Test that replacing a non-function symbol gives an error."""
        os.chdir(workspace)
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "User",
            "new_contents": '''type User struct {
	Name string
}''',
            "check_signature": True,
        })
        result = response["result"]
        assert "error" in result
        assert "not a Function or Method" in result["error"]

    def test_replace_function_bogus_content_reverts(self, workspace):
        """Test that bogus content that fails signature check reverts the file."""
        os.chdir(workspace)
        
        main_path = workspace / "main.go"
        original = main_path.read_text()
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "NewUser",
            "new_contents": "this is not valid go code @#$%^&*()",
            "check_signature": True,
        })
        result = response["result"]
        assert "error" in result
        
        # Verify file was reverted
        current = main_path.read_text()
        assert current == original
        
        # Verify no backup file left behind
        backup_path = main_path.with_suffix(".go.lspcmd.bkup")
        assert not backup_path.exists()

    def test_replace_function_symbol_not_found(self, workspace):
        """Test error when symbol doesn't exist."""
        os.chdir(workspace)
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "NonexistentFunc",
            "new_contents": "func NonexistentFunc() {}",
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
            "symbol_path": "User",
        })
        result = response["result"]
        assert result["name"] == "User"
        assert result["kind"] == "Struct"

    def test_resolve_symbol_ambiguous_shows_container_refs(self, workspace):
        """Test that ambiguous Go methods show Type.method format."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "Save",
        })
        result = response["result"]
        assert result["error"] == "Symbol 'Save' is ambiguous (3 matches)"
        assert result["total_matches"] == 3
        refs = [m["ref"] for m in result["matches"]]
        assert refs == ["Storage.Save", "MemoryStorage.Save", "FileStorage.Save"]

    def test_resolve_symbol_go_method_qualified(self, workspace):
        """Test that 'MemoryStorage.Save' finds '(*MemoryStorage).Save'."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "MemoryStorage.Save",
        })
        result = response["result"]
        assert result["name"] == "(*MemoryStorage).Save"
        assert result["line"] == 49
        assert result["path"].endswith("main.go")

    def test_resolve_symbol_value_receiver_method(self, workspace):
        """Test resolving methods with value receivers."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "User.IsAdult",
        })
        result = response["result"]
        assert "IsAdult" in result["name"]
        assert result["kind"] == "Method"

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "main.go:NewUser",
        })
        result = response["result"]
        assert result["name"] == "NewUser"
        assert result["path"].endswith("main.go")
