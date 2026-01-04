import os
import shutil
import time

import click
import pytest

from leta.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
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
        run_request(
            "grep",
            {
                "paths": [str(project / "main.go")],
                "workspace_root": str(project),
                "pattern": ".*",
            }
        )
        time.sleep(1.0)
        return project

    # =========================================================================
    # grep tests
    # =========================================================================

    def test_grep_pattern_filter(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go")],
                "workspace_root": str(workspace),
                "pattern": "^New",
                "kinds": ["function"],
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:16 [Function] NewUser (func(name, email string, age int) *User)
main.go:44 [Function] NewMemoryStorage (func() *MemoryStorage)
main.go:90 [Function] NewFileStorage (func(basePath string) *FileStorage)
main.go:124 [Function] NewUserRepository (func(storage Storage) *UserRepository)"""
        )

    def test_grep_kind_filter_struct(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go")],
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["struct"],
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:9 [Struct] User (struct{...})
main.go:39 [Struct] MemoryStorage (struct{...})
main.go:85 [Struct] FileStorage (struct{...})
main.go:119 [Struct] UserRepository (struct{...})"""
        )

    def test_grep_kind_filter_interface(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go")],
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["interface"],
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:31 [Interface] Storage (interface{...})
main.go:154 [Interface] Validator (interface{...})"""
        )

    def test_grep_case_sensitive(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go")],
                "workspace_root": str(workspace),
                "pattern": "^User$",
                "case_sensitive": False,
            }
        )
        insensitive_output = format_output(result, "plain")
        assert insensitive_output == "main.go:9 [Struct] User (struct{...})"

        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go")],
                "workspace_root": str(workspace),
                "pattern": "^User$",
                "case_sensitive": True,
            }
        )
        sensitive_output = format_output(result, "plain")
        assert sensitive_output == "main.go:9 [Struct] User (struct{...})"

        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go")],
                "workspace_root": str(workspace),
                "pattern": "^user$",
                "case_sensitive": True,
            }
        )
        lowercase_output = format_output(result, "plain")
        assert lowercase_output == ""

    def test_grep_combined_filters(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go")],
                "workspace_root": str(workspace),
                "pattern": "Storage",
                "kinds": ["struct"],
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:39 [Struct] MemoryStorage (struct{...})
main.go:85 [Struct] FileStorage (struct{...})"""
        )

    def test_grep_multiple_files(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go"), str(workspace / "utils.go")],
                "workspace_root": str(workspace),
                "pattern": "^New",
                "kinds": ["function"],
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:16 [Function] NewUser (func(name, email string, age int) *User)
main.go:44 [Function] NewMemoryStorage (func() *MemoryStorage)
main.go:90 [Function] NewFileStorage (func(basePath string) *FileStorage)
main.go:124 [Function] NewUserRepository (func(storage Storage) *UserRepository)
utils.go:31 [Function] NewCounter (func(initial int) *Counter)
utils.go:64 [Function] NewResult (func(value T) *Result[T])
utils.go:69 [Function] NewError (func(err error) *Result[T])"""
        )

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "workspace_root": str(workspace),
                "pattern": "Validate",
                "kinds": ["function"],
                "exclude_patterns": ["editable*"],
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
utils.go:9 [Function] ValidateEmail (func(email string) bool)
utils.go:16 [Function] ValidateAge (func(age int) bool)
main.go:159 [Function] ValidateUser (func(user *User) error)"""
        )

    def test_grep_exclude_pattern(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["function"],
                "exclude_patterns": ["editable*"],
            }
        )
        all_output = format_output(result, "plain")
        assert (
            all_output
            == """\
utils.go:9 [Function] ValidateEmail (func(email string) bool)
utils.go:16 [Function] ValidateAge (func(age int) bool)
utils.go:21 [Function] FormatName (func(first, last string) string)
utils.go:31 [Function] NewCounter (func(initial int) *Counter)
utils.go:64 [Function] NewResult (func(value T) *Result[T])
utils.go:69 [Function] NewError (func(err error) *Result[T])
main.go:16 [Function] NewUser (func(name, email string, age int) *User)
main.go:44 [Function] NewMemoryStorage (func() *MemoryStorage)
main.go:90 [Function] NewFileStorage (func(basePath string) *FileStorage)
main.go:124 [Function] NewUserRepository (func(storage Storage) *UserRepository)
main.go:149 [Function] createSampleUser (func() *User)
main.go:159 [Function] ValidateUser (func(user *User) error)
main.go:172 [Function] main (func())
errors.go:4 [Function] ErrorFunc (func())
errors.go:17 [Function] TypeErrorFunc (func() int)"""
        )

        result = run_request(
            "grep",
            {
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["function"],
                "exclude_patterns": ["utils.go", "editable*"],
            }
        )
        filtered_output = format_output(result, "plain")
        assert (
            filtered_output
            == """\
main.go:16 [Function] NewUser (func(name, email string, age int) *User)
main.go:44 [Function] NewMemoryStorage (func() *MemoryStorage)
main.go:90 [Function] NewFileStorage (func(basePath string) *FileStorage)
main.go:124 [Function] NewUserRepository (func(storage Storage) *UserRepository)
main.go:149 [Function] createSampleUser (func() *User)
main.go:159 [Function] ValidateUser (func(user *User) error)
main.go:172 [Function] main (func())
errors.go:4 [Function] ErrorFunc (func())
errors.go:17 [Function] TypeErrorFunc (func() int)"""
        )

    def test_grep_with_docs(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go")],
                "workspace_root": str(workspace),
                "pattern": "^NewUser$",
                "kinds": ["function"],
                "include_docs": True,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:16 [Function] NewUser (func(name, email string, age int) *User)
    ```go
    func NewUser(name string, email string, age int) *User
    ```
    
    ---
    
    NewUser creates a new User instance.
"""
        )

    # =========================================================================
    # definition tests
    # =========================================================================



    def test_definition(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "show",
            {
                "path": str(workspace / "main.go"),
                "workspace_root": str(workspace),
                "line": 174,
                "column": 9,
                "context": 0,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:124-126

func NewUserRepository(storage Storage) *UserRepository {
\treturn &UserRepository{storage: storage}
}"""
        )

    def test_definition_with_context(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "show",
            {
                "path": str(workspace / "main.go"),
                "workspace_root": str(workspace),
                "line": 174,
                "column": 9,
                "context": 1,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:123-127

// NewUserRepository creates a new repository with the given storage.
func NewUserRepository(storage Storage) *UserRepository {
\treturn &UserRepository{storage: storage}
}
"""
        )

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "references",
            {
                "path": str(workspace / "main.go"),
                "workspace_root": str(workspace),
                "line": 9,
                "column": 5,
                "context": 0,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
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
        )

    def test_references_with_context(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "references",
            {
                "path": str(workspace / "main.go"),
                "workspace_root": str(workspace),
                "line": 124,
                "column": 5,
                "context": 1,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:123-125
// NewUserRepository creates a new repository with the given storage.
func NewUserRepository(storage Storage) *UserRepository {
\treturn &UserRepository{storage: storage}

main.go:173-175
\tstorage := NewMemoryStorage()
\trepo := NewUserRepository(storage)
\tuser := createSampleUser()
"""
        )

    # =========================================================================
    # implementations tests
    # =========================================================================

    def test_implementations_basic(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "implementations",
            {
                "path": str(workspace / "main.go"),
                "workspace_root": str(workspace),
                "line": 31,
                "column": 5,
                "context": 0,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:39 type MemoryStorage struct {
main.go:85 type FileStorage struct {"""
        )

    def test_implementations_with_context(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "implementations",
            {
                "path": str(workspace / "main.go"),
                "workspace_root": str(workspace),
                "line": 31,
                "column": 5,
                "context": 1,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:38-40
// MemoryStorage stores users in memory.
type MemoryStorage struct {
\tusers map[string]*User

main.go:84-86
// FileStorage stores users in files (stub implementation).
type FileStorage struct {
\tbasePath string
"""
        )

    # =========================================================================

    # =========================================================================
    # rename tests (uses isolated editable files)
    # =========================================================================

    def test_rename(self, workspace):
        os.chdir(workspace)

        editable_path = workspace / "editable.go"
        original_editable = editable_path.read_text()

        try:
            assert "type EditablePerson struct" in original_editable

            result = run_request(
                "rename",
                {
                    "path": str(editable_path),
                    "workspace_root": str(workspace),
                    "line": 9,
                    "column": 6,
                    "new_name": "RenamedPerson",
                }
            )
            output = format_output(result, "plain")
            assert (
                output
                == """\
Renamed in 1 file(s):
  editable.go"""
            )

            renamed_editable = editable_path.read_text()
            assert "type RenamedPerson struct" in renamed_editable
            assert "type EditablePerson struct" not in renamed_editable
        finally:
            editable_path.write_text(original_editable)

    # =========================================================================
    # declaration tests (gopls doesn't support this)
    # =========================================================================

    def test_declaration_not_supported(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "declaration",
            {
                "path": str(workspace / "main.go"),
                "workspace_root": str(workspace),
                "line": 175,
                "column": 2,
                "context": 0,
            },
            expect_error=True,
        )
        assert result.error == "textDocument/declaration is not supported by gopls"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_not_supported(self, workspace):
        os.chdir(workspace)

        result = run_request(
            "move-file",
            {
                "old_path": str(workspace / "utils.go"),
                "new_path": str(workspace / "helpers.go"),
                "workspace_root": str(workspace),
            }
        ,
            expect_error=True,
        )
        assert hasattr(result, "error")
        assert result.error == "move-file is not supported by gopls"

        # Verify file was NOT moved
        assert (workspace / "utils.go").exists()
        assert not (workspace / "helpers.go").exists()

    # =========================================================================
    # resolve-symbol disambiguation tests
    # =========================================================================

    def test_resolve_symbol_unique_name(self, workspace):
        """Test resolving a unique symbol name."""
        os.chdir(workspace)
        result = run_request(
            "resolve-symbol",
            {
                "workspace_root": str(workspace),
                "symbol_path": "User",
            }
        )
        assert result.name == "User"
        assert result.kind == "Struct"

    def test_resolve_symbol_ambiguous_shows_container_refs(self, workspace):
        """Test that ambiguous Go methods show Type.method format."""
        os.chdir(workspace)
        result = run_request(
            "resolve-symbol",
            {
                "workspace_root": str(workspace),
                "symbol_path": "Save",
            }
        ,
            expect_error=True,
        )
        assert result.error == "Symbol 'Save' is ambiguous (4 matches)"
        assert result.total_matches == 4
        refs = sorted([m.ref for m in result.matches])
        assert refs == [
            "EditableStorage.Save",
            "FileStorage.Save",
            "MemoryStorage.Save",
            "Storage.Save",
        ]

    def test_resolve_symbol_go_method_qualified(self, workspace):
        """Test that 'MemoryStorage.Save' finds '(*MemoryStorage).Save'."""
        os.chdir(workspace)
        result = run_request(
            "resolve-symbol",
            {
                "workspace_root": str(workspace),
                "symbol_path": "MemoryStorage.Save",
            }
        )
        assert result.name == "(*MemoryStorage).Save"
        assert result.line == 49
        assert result.path.endswith("main.go")

    def test_resolve_symbol_value_receiver_method(self, workspace):
        """Test resolving methods with value receivers."""
        os.chdir(workspace)
        result = run_request(
            "resolve-symbol",
            {
                "workspace_root": str(workspace),
                "symbol_path": "User.IsAdult",
            }
        )
        assert "IsAdult" in result.name
        assert result.kind == "Method"

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        result = run_request(
            "resolve-symbol",
            {
                "workspace_root": str(workspace),
                "symbol_path": "main.go:NewUser",
            }
        )
        assert result.name == "NewUser"
        assert result.path.endswith("main.go")

    # =========================================================================
    # show multi-line variable tests
    # =========================================================================

    def test_show_multiline_map_variable(self, workspace):
        """Test that show displays multi-line map variables correctly."""
        os.chdir(workspace)
        result = run_request(
            "show",
            {
                "path": str(workspace / "utils.go"),
                "workspace_root": str(workspace),
                "line": 100,
                "column": 4,
                "context": 0,
                "direct_location": True,
                "range_start_line": 100,
                "range_end_line": 108,
                "kind": "Variable",
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
utils.go:100-108

var CountryCodes = map[string]string{
\t"US": "United States",
\t"CA": "Canada",
\t"GB": "United Kingdom",
\t"DE": "Germany",
\t"FR": "France",
\t"JP": "Japan",
\t"AU": "Australia",
}"""
        )

    def test_show_multiline_slice_variable(self, workspace):
        """Test that show displays multi-line slice variables correctly."""
        os.chdir(workspace)
        result = run_request(
            "show",
            {
                "path": str(workspace / "utils.go"),
                "workspace_root": str(workspace),
                "line": 111,
                "column": 4,
                "context": 0,
                "direct_location": True,
                "range_start_line": 111,
                "range_end_line": 117,
                "kind": "Variable",
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
utils.go:111-117

var DefaultPorts = []int{
\t80,
\t443,
\t8080,
\t8443,
\t3000,
}"""
        )

    # =========================================================================
    # calls tests
    # =========================================================================

    def test_calls_outgoing(self, workspace):
        """Test outgoing calls from createSampleUser (only calls NewUser)."""
        os.chdir(workspace)
        result = run_request(
            "calls",
            {
                "workspace_root": str(workspace),
                "mode": "outgoing",
                "from_path": str(workspace / "main.go"),
                "from_line": 149,
                "from_column": 5,
                "from_symbol": "createSampleUser",
                "max_depth": 1,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:149 [Function] createSampleUser (sample_project • main.go)

Outgoing calls:
  └── main.go:16 [Function] NewUser (sample_project • main.go)"""
        )

    def test_calls_incoming(self, workspace):
        """Test incoming calls to createSampleUser function."""
        os.chdir(workspace)
        result = run_request(
            "calls",
            {
                "workspace_root": str(workspace),
                "mode": "incoming",
                "to_path": str(workspace / "main.go"),
                "to_line": 149,
                "to_column": 5,
                "to_symbol": "createSampleUser",
                "max_depth": 1,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:149 [Function] createSampleUser (sample_project • main.go)

Incoming calls:
  └── main.go:172 [Function] main (sample_project • main.go)"""
        )

    def test_calls_path_found(self, workspace):
        """Test finding call path between two functions."""
        os.chdir(workspace)
        result = run_request(
            "calls",
            {
                "workspace_root": str(workspace),
                "mode": "path",
                "from_path": str(workspace / "main.go"),
                "from_line": 172,
                "from_column": 5,
                "from_symbol": "main",
                "to_path": str(workspace / "main.go"),
                "to_line": 149,
                "to_column": 5,
                "to_symbol": "createSampleUser",
                "max_depth": 3,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
Call path:
main.go:172 [Function] main (sample_project • main.go)
  → main.go:149 [Function] createSampleUser (sample_project • main.go)"""
        )

    def test_calls_outgoing_include_non_workspace(self, workspace):
        """Test outgoing calls with --include-non-workspace shows stdlib calls."""
        os.chdir(workspace)
        result = run_request(
            "calls",
            {
                "workspace_root": str(workspace),
                "mode": "outgoing",
                "from_path": str(workspace / "main.go"),
                "from_line": 26,
                "from_column": 16,
                "from_symbol": "DisplayName",
                "max_depth": 1,
                "include_non_workspace": True,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:26 [Function] DisplayName (sample_project • main.go)

Outgoing calls:
  └── [Function] Sprintf (fmt • print.go)"""
        )

    def test_calls_outgoing_excludes_stdlib_by_default(self, workspace):
        """Test outgoing calls without --include-non-workspace excludes stdlib."""
        os.chdir(workspace)
        result = run_request(
            "calls",
            {
                "workspace_root": str(workspace),
                "mode": "outgoing",
                "from_path": str(workspace / "main.go"),
                "from_line": 26,
                "from_column": 16,
                "from_symbol": "DisplayName",
                "max_depth": 1,
            }
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:26 [Function] DisplayName (sample_project • main.go)

Outgoing calls:"""
        )
