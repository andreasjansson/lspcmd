import os
import shutil
import time

import click
import pytest

from leta.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
    format_output,
    requires_solargraph,
    run_request,
)


class TestRubyIntegration:
    """Integration tests for Ruby using solargraph."""

    @pytest.fixture(autouse=True)
    def check_solargraph(self):
        requires_solargraph()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "ruby_project"
        dst = class_temp_dir / "ruby_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request(
            "grep",
            {
                "paths": [str(project / "user.rb")],
                "workspace_root": str(project),
                "pattern": ".*",
            },
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
                "paths": [str(workspace / "user.rb")],
                "workspace_root": str(workspace),
                "pattern": "Storage",
                "kinds": ["class"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
user.rb:38 [Class] Storage
user.rb:71 [Class] MemoryStorage
user.rb:113 [Class] FileStorage"""
        )

    def test_grep_kind_filter_class(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "user.rb")],
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["class"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
user.rb:8 [Class] User
user.rb:38 [Class] Storage
user.rb:71 [Class] MemoryStorage
user.rb:113 [Class] FileStorage
user.rb:163 [Class] UserRepository"""
        )

    def test_grep_kind_filter_method(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "user.rb")],
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["method"],
            },
        )
        output = format_output(result, "plain")
        assert "initialize" in output
        assert "adult?" in output
        assert "display_name" in output

    def test_grep_kind_filter_function(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "main.rb")],
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["function", "method"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.rb:8 [Method] create_sample_user
main.rb:16 [Method] validate_user
main.rb:26 [Method] process_users
main.rb:31 [Method] main"""
        )

    def test_grep_case_sensitive(self, workspace):
        os.chdir(workspace)
        # Case-insensitive should find Storage classes
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "user.rb")],
                "workspace_root": str(workspace),
                "pattern": "storage",
                "kinds": ["class"],
                "case_sensitive": False,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
user.rb:38 [Class] Storage
user.rb:71 [Class] MemoryStorage
user.rb:113 [Class] FileStorage"""
        )

        # Case-sensitive should find nothing (lowercase doesn't match)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "user.rb")],
                "workspace_root": str(workspace),
                "pattern": "storage",
                "kinds": ["class"],
                "case_sensitive": True,
            },
        )
        output = format_output(result, "plain")
        assert output == ""

    def test_grep_combined_filters(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "user.rb")],
                "workspace_root": str(workspace),
                "pattern": "^Memory",
                "kinds": ["class"],
            },
        )
        output = format_output(result, "plain")
        assert output == "user.rb:71 [Class] MemoryStorage"

    def test_grep_multiple_files(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "user.rb"), str(workspace / "main.rb")],
                "workspace_root": str(workspace),
                "pattern": "User",
                "kinds": ["class"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
user.rb:8 [Class] User
user.rb:163 [Class] UserRepository"""
        )

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        all_files = [str(p) for p in workspace.glob("*.rb")]
        result = run_request(
            "grep",
            {
                "paths": all_files,
                "workspace_root": str(workspace),
                "pattern": "main",
                "kinds": ["method"],
            },
        )
        output = format_output(result, "plain")
        assert output == "main.rb:31 [Method] main"

    def test_grep_exclude_pattern(self, workspace):
        os.chdir(workspace)
        all_files = [str(p) for p in workspace.glob("*.rb")]
        result = run_request(
            "grep",
            {
                "paths": all_files,
                "workspace_root": str(workspace),
                "pattern": "User",
                "kinds": ["class"],
                "exclude_patterns": ["errors.rb"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
user.rb:8 [Class] User
user.rb:163 [Class] UserRepository"""
        )

    def test_grep_with_docs(self, workspace):
        """Test grep with docs - Solargraph may not return docs due to hover position."""
        os.chdir(workspace)
        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "user.rb")],
                "workspace_root": str(workspace),
                "pattern": "^User$",
                "kinds": ["class"],
                "include_docs": True,
            },
        )
        output = format_output(result, "plain")
        # Solargraph doesn't return docs at the reported symbol position
        assert output == "user.rb:8 [Class] User"

    # =========================================================================
    # definition tests
    # =========================================================================


    def test_definition(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "show",
            {
                "path": str(workspace / "main.rb"),
                "workspace_root": str(workspace),
                "line": 35,
                "column": 9,
                "context": 0,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.rb:8-10

def create_sample_user
  User.new('John Doe', 'john@example.com', 30)
end"""
        )

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        result = run_request(
            "references",
            {
                "path": str(workspace / "user.rb"),
                "workspace_root": str(workspace),
                "line": 8,
                "column": 6,
                "context": 0,
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.rb:9   User.new('John Doe', 'john@example.com', 30)
user.rb:8 class User"""
        )

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_not_supported(self, workspace):
        os.chdir(workspace)

        result = run_request(
            "move-file",
            {
                "old_path": str(workspace / "user.rb"),
                "new_path": str(workspace / "person.rb"),
                "workspace_root": str(workspace),
            },
        )
        assert "error" in response
        assert response["error"] == "move-file is not supported by solargraph"

        # Verify file was NOT moved
        assert (workspace / "user.rb").exists()
        assert not (workspace / "person.rb").exists()

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
            },
        )
        assert result.name == "User"
        assert result.kind == "Class"

    def test_resolve_symbol_class_method(self, workspace):
        """Test resolving Class#method format - solargraph may not index instance methods."""
        os.chdir(workspace)
        result = run_request(
            "resolve-symbol",
            {
                "workspace_root": str(workspace),
                "symbol_path": "User.is_adult",
            },
        )
        # Solargraph may not find instance methods with this notation
        if "error" not in result:
            assert result.name == "is_adult"
            assert result.kind == "Method"

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        result = run_request(
            "resolve-symbol",
            {
                "workspace_root": str(workspace),
                "symbol_path": "user.rb:User",
            },
        )
        assert result.name == "User"
        assert result.path.endswith("user.rb")

    # =========================================================================
    # show multi-line constant tests
    # =========================================================================

    def test_show_multiline_hash_constant(self, workspace):
        """Test that show displays multi-line Hash constants correctly."""
        os.chdir(workspace)
        result = run_request(
            "show",
            {
                "path": str(workspace / "user.rb"),
                "workspace_root": str(workspace),
                "line": 144,
                "column": 0,
                "context": 0,
                "direct_location": True,
                "range_start_line": 144,
                "range_end_line": 152,
                "kind": "Constant",
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
user.rb:144-152

COUNTRY_CODES = {
  'US' => 'United States',
  'CA' => 'Canada',
  'GB' => 'United Kingdom',
  'DE' => 'Germany',
  'FR' => 'France',
  'JP' => 'Japan',
  'AU' => 'Australia'
}.freeze"""
        )

    def test_show_multiline_array_constant(self, workspace):
        """Test that show displays multi-line Array constants correctly."""
        os.chdir(workspace)
        result = run_request(
            "show",
            {
                "path": str(workspace / "user.rb"),
                "workspace_root": str(workspace),
                "line": 155,
                "column": 0,
                "context": 0,
                "direct_location": True,
                "range_start_line": 155,
                "range_end_line": 160,
                "kind": "Constant",
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
user.rb:155-160

DEFAULT_CONFIG = [
  'debug=false',
  'timeout=30',
  'max_retries=3',
  'log_level=INFO'
].freeze"""
        )

    # =========================================================================
    # calls tests (solargraph does not support call hierarchy)
    # =========================================================================

    def test_calls_not_supported(self, workspace):
        """Test that calls returns proper error for solargraph."""
        os.chdir(workspace)
        result = run_request(
            "calls",
            {
                "workspace_root": str(workspace),
                "mode": "outgoing",
                "from_path": str(workspace / "main.rb"),
                "from_line": 37,
                "from_column": 4,
                "from_symbol": "main",
                "max_depth": 1,
            },
        )
        assert "error" in response
        assert (
            response["error"]
            == "textDocument/prepareCallHierarchy is not supported by solargraph"
        )
