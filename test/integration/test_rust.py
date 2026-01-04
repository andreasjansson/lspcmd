import os
import shutil
import time

import click
import pytest

from leta.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
    format_output,
    requires_rust_analyzer,
    run_request,
)


class TestRustIntegration:
    """Integration tests for Rust using rust-analyzer."""

    @pytest.fixture(autouse=True)
    def check_rust_analyzer(self):
        requires_rust_analyzer()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "rust_project"
        dst = class_temp_dir / "rust_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        # rust-analyzer needs more time to fully index
        for f in ["main.rs", "user.rs", "storage.rs", "errors.rs"]:
            run_request(
                "grep",
                {
                    "paths": [str(project / "src" / f)],
                    "workspace_root": str(project),
                    "pattern": ".*",
                },
            )
        time.sleep(4.0)
        return project

    def _run_request_with_retry(self, method, params, max_retries=3):
        """Run a request with retries for transient rust-analyzer errors."""
        import click

        for attempt in range(max_retries):
            try:
                return run_request(method, params)
            except click.ClickException as e:
                if "content modified" in str(e) and attempt < max_retries - 1:
                    time.sleep(1.0)
                    continue
                raise

    # =========================================================================
    # grep tests
    # =========================================================================

    def test_grep_pattern_filter(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "src" / "storage.rs")],
                "workspace_root": str(workspace),
                "pattern": "Storage",
                "kinds": ["struct", "interface"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/storage.rs:5 [Interface] Storage
src/storage.rs:20 [Struct] MemoryStorage
src/storage.rs:58 [Struct] FileStorage"""
        )

    def test_grep_kind_filter(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "src" / "user.rs")],
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["struct"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/user.rs:5 [Struct] User
src/user.rs:44 [Struct] UserRepository"""
        )

    def test_grep_case_sensitive(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "grep",
            {
                "paths": [str(workspace / "src" / "user.rs")],
                "workspace_root": str(workspace),
                "pattern": "^User$",
                "case_sensitive": False,
            },
        )
        output = format_output(result, "plain")
        assert output == "src/user.rs:5 [Struct] User"

        response = self._run_request_with_retry(
            "grep",
            {
                "paths": [str(workspace / "src" / "user.rs")],
                "workspace_root": str(workspace),
                "pattern": "^user$",
                "case_sensitive": True,
            },
        )
        lowercase_output = format_output(result, "plain")
        assert lowercase_output == ""

    def test_grep_combined_filters(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "grep",
            {
                "paths": [str(workspace / "src" / "storage.rs")],
                "workspace_root": str(workspace),
                "pattern": "Storage",
                "kinds": ["struct"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/storage.rs:20 [Struct] MemoryStorage
src/storage.rs:58 [Struct] FileStorage"""
        )

    def test_grep_multiple_files(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "grep",
            {
                "paths": [
                    str(workspace / "src" / "user.rs"),
                    str(workspace / "src" / "storage.rs"),
                ],
                "workspace_root": str(workspace),
                "pattern": "^new$",
                "kinds": ["function"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/user.rs:13 [Function] new (fn(name: String, email: String, age: u32) -> Self) in impl User
src/user.rs:50 [Function] new (fn(storage: S) -> Self) in impl UserRepository<S>
src/storage.rs:26 [Function] new (fn() -> Self) in impl MemoryStorage
src/storage.rs:65 [Function] new (fn(base_path: String) -> Self) in impl FileStorage"""
        )

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "grep",
            {
                "workspace_root": str(workspace),
                "pattern": "validate",
                "case_sensitive": False,
                "kinds": ["function"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == "src/user.rs:81 [Function] validate_user (fn(user: &User) -> Result<(), String>)"
        )

    def test_grep_exclude_pattern(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "grep",
            {
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["function"],
            },
        )
        all_output = format_output(result, "plain")
        assert (
            all_output
            == """\
src/user.rs:13 [Function] new (fn(name: String, email: String, age: u32) -> Self) in impl User
src/user.rs:50 [Function] new (fn(storage: S) -> Self) in impl UserRepository<S>
src/user.rs:81 [Function] validate_user (fn(user: &User) -> Result<(), String>)
src/errors.rs:4 [Function] undefined_variable (fn() -> i32)
src/errors.rs:9 [Function] type_error (fn() -> i32)
src/errors.rs:14 [Function] binding_error (fn())
src/main.rs:10 [Function] create_sample_user (fn() -> User)
src/main.rs:15 [Function] process_users (fn(repo: &UserRepository<MemoryStorage>) -> Vec<String>)
src/main.rs:22 [Function] main (fn())
src/storage.rs:26 [Function] new (fn() -> Self) in impl MemoryStorage
src/storage.rs:34 [Function] default (fn() -> Self) in impl Default for MemoryStorage
src/storage.rs:65 [Function] new (fn(base_path: String) -> Self) in impl FileStorage"""
        )

        response = self._run_request_with_retry(
            "grep",
            {
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["function"],
                "exclude_patterns": ["errors.rs"],
            },
        )
        filtered_output = format_output(result, "plain")
        assert (
            filtered_output
            == """\
src/user.rs:13 [Function] new (fn(name: String, email: String, age: u32) -> Self) in impl User
src/user.rs:50 [Function] new (fn(storage: S) -> Self) in impl UserRepository<S>
src/user.rs:81 [Function] validate_user (fn(user: &User) -> Result<(), String>)
src/main.rs:10 [Function] create_sample_user (fn() -> User)
src/main.rs:15 [Function] process_users (fn(repo: &UserRepository<MemoryStorage>) -> Vec<String>)
src/main.rs:22 [Function] main (fn())
src/storage.rs:26 [Function] new (fn() -> Self) in impl MemoryStorage
src/storage.rs:34 [Function] default (fn() -> Self) in impl Default for MemoryStorage
src/storage.rs:65 [Function] new (fn(base_path: String) -> Self) in impl FileStorage"""
        )

    def test_grep_with_docs(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "grep",
            {
                "paths": [str(workspace / "src" / "main.rs")],
                "workspace_root": str(workspace),
                "pattern": "^create_sample_user$",
                "kinds": ["function"],
                "include_docs": True,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/main.rs:10 [Function] create_sample_user (fn() -> User)
    ```rust
    sample_project
    ```
    
    ```rust
    fn create_sample_user() -> User
    ```
    
    ---
    
    Creates a sample user for testing.
"""
        )

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "show",
            {
                "path": str(workspace / "src" / "main.rs"),
                "workspace_root": str(workspace),
                "line": 25,
                "column": 16,
                "context": 0,
                "body": False,
            },
        )
        output = format_output(result, "plain")
        assert output == "src/main.rs:10 fn create_sample_user() -> User {"

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "show",
            {
                "path": str(workspace / "src" / "main.rs"),
                "workspace_root": str(workspace),
                "line": 25,
                "column": 16,
                "context": 0,
                "body": True,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/main.rs:9-12

/// Creates a sample user for testing.
fn create_sample_user() -> User {
    User::new("John Doe".to_string(), "john@example.com".to_string(), 30)
}"""
        )

    def test_definition_with_body_and_context(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "show",
            {
                "path": str(workspace / "src" / "main.rs"),
                "workspace_root": str(workspace),
                "line": 25,
                "column": 16,
                "context": 1,
                "body": True,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/main.rs:8-13


/// Creates a sample user for testing.
fn create_sample_user() -> User {
    User::new("John Doe".to_string(), "john@example.com".to_string(), 30)
}
"""
        )

    def test_definition_with_context(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "show",
            {
                "path": str(workspace / "src" / "main.rs"),
                "workspace_root": str(workspace),
                "line": 25,
                "column": 16,
                "context": 1,
                "body": False,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/main.rs:9-11
/// Creates a sample user for testing.
fn create_sample_user() -> User {
    User::new("John Doe".to_string(), "john@example.com".to_string(), 30)
"""
        )

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "references",
            {
                "path": str(workspace / "src" / "main.rs"),
                "workspace_root": str(workspace),
                "line": 10,
                "column": 3,
                "context": 0,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/main.rs:25     let user = create_sample_user();
src/main.rs:10 fn create_sample_user() -> User {"""
        )

    def test_references_with_context(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "references",
            {
                "path": str(workspace / "src" / "main.rs"),
                "workspace_root": str(workspace),
                "line": 10,
                "column": 3,
                "context": 1,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/main.rs:24-26
    let mut repo = UserRepository::new(storage);
    let user = create_sample_user();


src/main.rs:9-11
/// Creates a sample user for testing.
fn create_sample_user() -> User {
    User::new("John Doe".to_string(), "john@example.com".to_string(), 30)
"""
        )

    # =========================================================================
    # rename tests
    # =========================================================================

    def test_rename(self, workspace):
        os.chdir(workspace)

        user_rs = workspace / "src" / "user.rs"
        main_rs = workspace / "src" / "main.rs"
        storage_rs = workspace / "src" / "storage.rs"

        original_user = user_rs.read_text()
        original_main = main_rs.read_text()
        original_storage = storage_rs.read_text()

        try:
            response = self._run_request_with_retry(
                "rename",
                {
                    "path": str(user_rs),
                    "workspace_root": str(workspace),
                    "line": 5,
                    "column": 11,
                    "new_name": "Person",
                },
            )
            output = format_output(result, "plain")
            assert (
                output
                == """\
Renamed in 3 file(s):
  src/main.rs
  src/user.rs
  src/storage.rs"""
            )

            # Verify rename happened
            content = user_rs.read_text()
            assert "pub struct Person {" in content
            assert "pub struct User {" not in content
        finally:
            user_rs.write_text(original_user)
            main_rs.write_text(original_main)
            storage_rs.write_text(original_storage)

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_updates_mod_declarations(self, workspace):
        os.chdir(workspace)

        # Verify user.rs exists and check initial mod declaration
        assert (workspace / "src" / "user.rs").exists()
        original_main = (workspace / "src" / "main.rs").read_text()
        assert "mod user;" in original_main

        # Rename user.rs to person.rs
        response = self._run_request_with_retry(
            "move-file",
            {
                "old_path": str(workspace / "src" / "user.rs"),
                "new_path": str(workspace / "src" / "person.rs"),
                "workspace_root": str(workspace),
            },
        )
        output = format_output(result, "plain")

        # Verify the file was moved
        assert not (workspace / "src" / "user.rs").exists()
        assert (workspace / "src" / "person.rs").exists()

        # Check exact output - rust-analyzer updates mod declarations
        # storage.rs also uses user module so it gets updated too
        assert (
            output
            == """\
Moved file and updated imports in 3 file(s):
  src/main.rs
  src/storage.rs
  src/person.rs"""
        )

        # Check that mod declaration was updated in main.rs
        updated_main = (workspace / "src" / "main.rs").read_text()
        assert "mod person;" in updated_main
        assert "mod user;" not in updated_main

    # =========================================================================
    # resolve-symbol disambiguation tests
    # =========================================================================

    def test_resolve_symbol_unique_name(self, workspace):
        """Test resolving a unique symbol name."""
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "resolve-symbol",
            {
                "workspace_root": str(workspace),
                "symbol_path": "UserRepository",
            },
        )
        assert result.name == "UserRepository"
        assert result.kind == "Struct"

    def test_resolve_symbol_ambiguous_shows_container_refs(self, workspace):
        """Test that ambiguous Rust symbols show Type.method format."""
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "resolve-symbol",
            {
                "workspace_root": str(workspace),
                "symbol_path": "new",
            },
        )
        assert result.error == "Symbol 'new' is ambiguous (4 matches)"
        assert result.total_matches == 4
        refs = [m.ref for m in result.matches]
        assert refs == [
            "User.new",
            "UserRepository.new",
            "MemoryStorage.new",
            "FileStorage.new",
        ]

    def test_resolve_symbol_impl_method(self, workspace):
        """Test resolving impl method with Type.method format."""
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "resolve-symbol",
            {
                "workspace_root": str(workspace),
                "symbol_path": "MemoryStorage.new",
            },
        )
        assert result.name == "new"
        assert result.kind == "Function"
        assert result.path.endswith("storage.rs")

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "resolve-symbol",
            {
                "workspace_root": str(workspace),
                "symbol_path": "storage.rs:Storage",
            },
        )
        assert result.name == "Storage"
        assert result.path.endswith("storage.rs")

    # =========================================================================
    # show multi-line constant tests
    # =========================================================================

    def test_show_multiline_array_constant(self, workspace):
        """Test that show displays multi-line array constants correctly."""
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "show",
            {
                "path": str(workspace / "src" / "user.rs"),
                "workspace_root": str(workspace),
                "line": 92,
                "column": 10,
                "context": 0,
                "body": True,
                "direct_location": True,
                "range_start_line": 91,
                "range_end_line": 98,
                "kind": "Constant",
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/user.rs:91-98

/// Default ports for various services.
pub const DEFAULT_PORTS: [u16; 5] = [
    80,
    443,
    8080,
    8443,
    3000,
];"""
        )

    # =========================================================================
    # calls tests
    # =========================================================================

    def test_calls_incoming(self, workspace):
        """Test incoming calls to create_sample_user function."""
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "calls",
            {
                "workspace_root": str(workspace),
                "mode": "incoming",
                "to_path": str(workspace / "src" / "main.rs"),
                "to_line": 10,
                "to_column": 3,
                "to_symbol": "create_sample_user",
                "max_depth": 1,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/main.rs:10 [Function] create_sample_user (fn create_sample_user() -> User)

Incoming calls:
  └── src/main.rs:22 [Function] main (fn main())"""
        )

    def test_calls_outgoing_include_non_workspace(self, workspace):
        """Test outgoing calls with --include-non-workspace shows stdlib calls."""
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "calls",
            {
                "workspace_root": str(workspace),
                "mode": "outgoing",
                "from_path": str(workspace / "src" / "main.rs"),
                "from_line": 10,
                "from_column": 3,
                "from_symbol": "create_sample_user",
                "max_depth": 1,
                "include_non_workspace": True,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/main.rs:10 [Function] create_sample_user (fn create_sample_user() -> User)

Outgoing calls:
  ├── src/user.rs:13 [Function] new (pub fn new(name: String, email: String, age: u32) -> Self)
  └── [Function] to_string (fn to_string(&self) -> String)"""
        )

    def test_calls_outgoing_excludes_stdlib_by_default(self, workspace):
        """Test outgoing calls without --include-non-workspace excludes stdlib."""
        os.chdir(workspace)
        response = self._run_request_with_retry(
            "calls",
            {
                "workspace_root": str(workspace),
                "mode": "outgoing",
                "from_path": str(workspace / "src" / "main.rs"),
                "from_line": 10,
                "from_column": 3,
                "from_symbol": "create_sample_user",
                "max_depth": 1,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
src/main.rs:10 [Function] create_sample_user (fn create_sample_user() -> User)

Outgoing calls:
  └── src/user.rs:13 [Function] new (pub fn new(name: String, email: String, age: u32) -> Self)"""
        )
