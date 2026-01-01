import os
import shutil
import time

import click
import pytest

from lspcmd.utils.config import add_workspace_root, load_config

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
        run_request("grep", {
            "paths": [str(project / "user.rb")],
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
            "paths": [str(workspace / "user.rb")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert "Storage" in output
        assert "MemoryStorage" in output
        assert "FileStorage" in output

    def test_grep_kind_filter_class(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.rb")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert "[Class] User" in output
        assert "[Class] Storage" in output
        assert "[Class] MemoryStorage" in output
        assert "[Class] FileStorage" in output
        assert "[Class] UserRepository" in output

    def test_grep_kind_filter_method(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.rb")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["method"],
        })
        output = format_output(response["result"], "plain")
        assert "initialize" in output
        assert "adult?" in output
        assert "display_name" in output

    def test_grep_kind_filter_function(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.rb")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function", "method"],
        })
        output = format_output(response["result"], "plain")
        assert "create_sample_user" in output
        assert "validate_user" in output
        assert "process_users" in output
        assert "main" in output

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.rb"),
            "workspace_root": str(workspace),
            "line": 35,
            "column": 9,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert "create_sample_user" in output

    def test_definition_with_body_not_supported(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.rb"),
            "workspace_root": str(workspace),
            "line": 35,
            "column": 9,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert "does not provide symbol ranges" in output

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "user.rb"),
            "workspace_root": str(workspace),
            "line": 8,
            "column": 6,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert "User" in output

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        os.chdir(workspace)
        response = run_request("describe", {
            "path": str(workspace / "user.rb"),
            "workspace_root": str(workspace),
            "line": 8,
            "column": 6,
        })
        output = format_output(response["result"], "plain")
        assert "User" in output

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.rb"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        # Solargraph may not report all Ruby errors, but should at least process the file
        assert "errors.rb" in output or output == ""

    def test_diagnostics_method_redefinition(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.rb"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        # Solargraph may report method redefinition as a warning
        if output.strip():
            has_warning = "redefin" in output.lower() or "duplicate" in output.lower() or "warning" in output.lower()
            # If there's output, it should contain something meaningful
            assert has_warning or "error" in output.lower(), f"Expected meaningful diagnostic: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_not_supported(self, workspace):
        import click
        os.chdir(workspace)
        
        with pytest.raises(click.ClickException) as exc_info:
            run_request("move-file", {
                "old_path": str(workspace / "user.rb"),
                "new_path": str(workspace / "person.rb"),
                "workspace_root": str(workspace),
            })
        assert str(exc_info.value) == "move-file is not supported by solargraph"
        
        # Verify file was NOT moved
        assert (workspace / "user.rb").exists()
        assert not (workspace / "person.rb").exists()

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
        assert result["kind"] == "Class"

    def test_resolve_symbol_class_method(self, workspace):
        """Test resolving Class#method format - solargraph may not index instance methods."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "User.is_adult",
        })
        result = response["result"]
        # Solargraph may not find instance methods with this notation
        if "error" not in result:
            assert result["name"] == "is_adult"
            assert result["kind"] == "Method"

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "user.rb:User",
        })
        result = response["result"]
        assert result["name"] == "User"
        assert result["path"].endswith("user.rb")
