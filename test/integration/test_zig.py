import os
import shutil
import time

import click
import pytest

from lspcmd.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
    format_output,
    requires_zls,
    run_request,
)


class TestZigIntegration:
    """Integration tests for Zig using zls."""

    @pytest.fixture(autouse=True)
    def check_zls(self):
        requires_zls()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "zig_project"
        dst = class_temp_dir / "zig_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("grep", {
            "paths": [str(project / "src" / "user.zig")],
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
            "paths": [str(workspace / "src" / "user.zig")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.zig:31 [Constant] Storage
src/user.zig:51 [Constant] MemoryStorage
src/user.zig:85 [Constant] FileStorage
src/user.zig:114 [Field] storage (UserRepository) in UserRepository"""

    def test_grep_kind_filter_constant(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.zig")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["constant"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.zig:1 [Constant] std
src/user.zig:4 [Constant] User
src/user.zig:31 [Constant] Storage
src/user.zig:51 [Constant] MemoryStorage
src/user.zig:85 [Constant] FileStorage
src/user.zig:113 [Constant] UserRepository
src/user.zig:146 [Constant] DEFAULT_PORTS
src/user.zig:155 [Constant] COUNTRY_CODES"""

    def test_grep_kind_filter_function(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main.zig")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.zig:4 [Function] main (fn main() !void)
src/main.zig:22 [Function] createSampleUser (fn createSampleUser() user.User)
src/main.zig:27 [Function] validateUser (fn validateUser(u: user.User) !void)"""

    def test_grep_case_sensitive(self, workspace):
        os.chdir(workspace)
        # Case-insensitive should find Storage classes
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.zig")],
            "workspace_root": str(workspace),
            "pattern": "storage",
            "kinds": ["constant"],
            "case_sensitive": False,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.zig:31 [Constant] Storage
src/user.zig:51 [Constant] MemoryStorage
src/user.zig:85 [Constant] FileStorage"""
        
        # Case-sensitive should find nothing
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.zig")],
            "workspace_root": str(workspace),
            "pattern": "storage",
            "kinds": ["constant"],
            "case_sensitive": True,
        })
        output = format_output(response["result"], "plain")
        assert output == ""

    def test_grep_combined_filters(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.zig")],
            "workspace_root": str(workspace),
            "pattern": "^Memory",
            "kinds": ["constant"],
        })
        output = format_output(response["result"], "plain")
        assert output == "src/user.zig:51 [Constant] MemoryStorage"

    def test_grep_multiple_files(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.zig"), str(workspace / "src" / "main.zig")],
            "workspace_root": str(workspace),
            "pattern": "User",
            "kinds": ["constant"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.zig:4 [Constant] User
src/user.zig:113 [Constant] UserRepository
src/main.zig:2 [Constant] user"""

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        all_files = [str(p) for p in (workspace / "src").glob("*.zig")]
        response = run_request("grep", {
            "paths": all_files,
            "workspace_root": str(workspace),
            "pattern": "main",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == "src/main.zig:4 [Function] main (fn main() !void)"

    def test_grep_exclude_pattern(self, workspace):
        os.chdir(workspace)
        all_files = [str(p) for p in (workspace / "src").glob("*.zig")]
        response = run_request("grep", {
            "paths": all_files,
            "workspace_root": str(workspace),
            "pattern": "User",
            "kinds": ["constant"],
            "exclude_patterns": ["errors.zig"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.zig:4 [Constant] User
src/user.zig:113 [Constant] UserRepository
src/main.zig:2 [Constant] user"""

    def test_grep_with_docs(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main.zig")],
            "workspace_root": str(workspace),
            "pattern": "^createSampleUser$",
            "kinds": ["function"],
            "include_docs": True,
        })
        output = format_output(response["result"], "plain")
        # zls returns hover docs with markdown including code blocks
        assert "src/main.zig:22 [Function] createSampleUser (fn createSampleUser() user.User)" in output
        assert "Creates a sample user for testing." in output

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "src" / "main.zig"),
            "workspace_root": str(workspace),
            "line": 12,
            "column": 24,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "src/main.zig:22 pub fn createSampleUser() user.User {"

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "src" / "main.zig"),
            "workspace_root": str(workspace),
            "line": 12,
            "column": 24,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.zig:22-24

pub fn createSampleUser() user.User {
    return user.User.init("John Doe", "john@example.com", 30);
}"""

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "src" / "user.zig"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 11,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        # zls returns many references to User type
        assert "src/user.zig:4" in output
        assert "src/user.zig:10" in output

    # =========================================================================

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_not_supported(self, workspace):
        os.chdir(workspace)
        
        response = run_request("move-file", {
            "old_path": str(workspace / "src" / "user.zig"),
            "new_path": str(workspace / "src" / "person.zig"),
            "workspace_root": str(workspace),
        })
        assert "error" in response
        assert response["error"] == "move-file is not supported by zls"
        
        # Verify file was NOT moved
        assert (workspace / "src" / "user.zig").exists()
        assert not (workspace / "src" / "person.zig").exists()

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
        assert result["kind"] == "Constant"

    def test_resolve_symbol_struct_method(self, workspace):
        """Test resolving Struct.method format."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "User.isAdult",
        })
        result = response["result"]
        assert result["name"] == "isAdult"
        assert result["kind"] == "Function"

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "main.zig:main",
        })
        result = response["result"]
        assert result["name"] == "main"
        assert result["path"].endswith("main.zig")

    # =========================================================================
    # show multi-line constant tests
    # =========================================================================

    def test_show_multiline_array_constant(self, workspace):
        """Test that show displays multi-line array constants correctly."""
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "src" / "user.zig"),
            "workspace_root": str(workspace),
            "line": 146,
            "column": 10,
            "context": 0,
            "body": True,
            "direct_location": True,
            "range_start_line": 146,
            "range_end_line": 152,
            "kind": "Constant",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.zig:146-152

pub const DEFAULT_PORTS = [_]u16{
    80,
    443,
    8080,
    8443,
    3000,
};"""

    # =========================================================================
    # calls tests (zls does not support call hierarchy)
    # =========================================================================

    def test_calls_not_supported(self, workspace):
        """Test that calls returns proper error for zls (returns null for prepare)."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "outgoing",
            "from_path": str(workspace / "src" / "main.zig"),
            "from_line": 4,
            "from_column": 7,
            "from_symbol": "main",
            "max_depth": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == "Error: No callable symbol found at src/main.zig:4:7 for 'main'. The symbol may not be a function/method, or the position may be incorrect."
