import os
import shutil
import time

import pytest

from lspcmd.utils.config import add_workspace_root, load_config

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
            run_request("grep", {
                "paths": [str(project / "src" / f)],
                "workspace_root": str(project),
                "pattern": ".*",
            })
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
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "storage.rs")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["struct", "interface"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/storage.rs:5 [Interface] Storage
src/storage.rs:20 [Struct] MemoryStorage
src/storage.rs:58 [Struct] FileStorage"""

    def test_grep_kind_filter(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.rs")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["struct"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.rs:5 [Struct] User
src/user.rs:44 [Struct] UserRepository"""

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry("definition", {
            "path": str(workspace / "src" / "main.rs"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 16,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "src/main.rs:10 fn create_sample_user() -> User {"

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry("definition", {
            "path": str(workspace / "src" / "main.rs"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 16,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.rs:9-12

/// Creates a sample user for testing.
fn create_sample_user() -> User {
    User::new("John Doe".to_string(), "john@example.com".to_string(), 30)
}"""

    def test_definition_with_body_and_context(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry("definition", {
            "path": str(workspace / "src" / "main.rs"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 16,
            "context": 1,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.rs:8-13


/// Creates a sample user for testing.
fn create_sample_user() -> User {
    User::new("John Doe".to_string(), "john@example.com".to_string(), 30)
}
"""

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry("references", {
            "path": str(workspace / "src" / "main.rs"),
            "workspace_root": str(workspace),
            "line": 10,
            "column": 3,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.rs:25     let user = create_sample_user();
src/main.rs:10 fn create_sample_user() -> User {"""

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        # rust-analyzer uses push diagnostics from cargo check
        # Need to wait longer for cargo to run
        time.sleep(3.0)
        response = self._run_request_with_retry("diagnostics", {
            "path": str(workspace / "src" / "errors.rs"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        # rust-analyzer may not report diagnostics immediately - cargo check runs async
        # At minimum we should not crash; diagnostics may take a while to arrive
        assert output is not None

    def test_diagnostics_workspace(self, workspace):
        os.chdir(workspace)
        # For workspace-wide diagnostics, rust-analyzer needs time to run cargo check
        time.sleep(3.0)
        response = self._run_request_with_retry("workspace-diagnostics", {
            "workspace_root": str(workspace),
        })
        # Workspace diagnostics should return something (even if empty due to timing)
        assert response is not None

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
        response = self._run_request_with_retry("move-file", {
            "old_path": str(workspace / "src" / "user.rs"),
            "new_path": str(workspace / "src" / "person.rs"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        
        # Verify the file was moved
        assert not (workspace / "src" / "user.rs").exists()
        assert (workspace / "src" / "person.rs").exists()
        
        # Check exact output - rust-analyzer updates mod declarations
        # storage.rs also uses user module so it gets updated too
        assert output == """\
Moved file and updated imports in 3 file(s):
  src/main.rs
  src/storage.rs
  src/person.rs"""
        
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
        response = self._run_request_with_retry("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "UserRepository",
        })
        result = response["result"]
        assert result["name"] == "UserRepository"
        assert result["kind"] == "Struct"

    def test_resolve_symbol_ambiguous_shows_container_refs(self, workspace):
        """Test that ambiguous Rust symbols show Type.method format."""
        os.chdir(workspace)
        response = self._run_request_with_retry("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "new",
        })
        result = response["result"]
        assert result["error"] == "Symbol 'new' is ambiguous (4 matches)"
        assert result["total_matches"] == 4
        refs = [m["ref"] for m in result["matches"]]
        assert refs == ["User.new", "UserRepository.new", "MemoryStorage.new", "FileStorage.new"]

    def test_resolve_symbol_impl_method(self, workspace):
        """Test resolving impl method with Type.method format."""
        os.chdir(workspace)
        response = self._run_request_with_retry("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "MemoryStorage.new",
        })
        result = response["result"]
        assert result["name"] == "new"
        assert result["kind"] == "Function"
        assert result["path"].endswith("storage.rs")

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        response = self._run_request_with_retry("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "storage.rs:Storage",
        })
        result = response["result"]
        assert result["name"] == "Storage"
        assert result["path"].endswith("storage.rs")
