import os
import shutil
import time

import click
import pytest

from lspcmd.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
    format_output,
    requires_intelephense,
    run_request,
)


class TestPhpIntegration:
    """Integration tests for PHP using intelephense."""

    @pytest.fixture(autouse=True)
    def check_intelephense(self):
        requires_intelephense()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "php_project"
        dst = class_temp_dir / "php_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("grep", {
            "paths": [str(project / "src" / "User.php")],
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
            "paths": [str(workspace / "src" / "Storage.php")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["interface"],
        })
        output = format_output(response["result"], "plain")
        assert "Storage" in output

    def test_grep_kind_filter_class(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "MemoryStorage.php")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert "[Class] MemoryStorage" in output

    def test_grep_kind_filter_interface(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "Storage.php")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["interface"],
        })
        output = format_output(response["result"], "plain")
        assert "[Interface] Storage" in output

    def test_grep_kind_filter_method(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "User.php")],
            "workspace_root": str(workspace),
            "pattern": "^get",
            "kinds": ["method"],
        })
        output = format_output(response["result"], "plain")
        assert "getName" in output
        assert "getEmail" in output
        assert "getAge" in output

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "Main.php"),
            "workspace_root": str(workspace),
            "line": 63,
            "column": 22,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert "createSampleUser" in output

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "Main.php"),
            "workspace_root": str(workspace),
            "line": 63,
            "column": 22,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert "createSampleUser" in output
        assert "John Doe" in output

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "src" / "User.php"),
            "workspace_root": str(workspace),
            "line": 10,
            "column": 6,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert "User" in output

    # =========================================================================
    # implementations tests
    # =========================================================================

    def test_implementations_not_supported(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "src" / "Storage.php"),
            "workspace_root": str(workspace),
            "line": 10,
            "column": 10,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert "does not support implementations" in output
        assert "may require a license" in output

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        os.chdir(workspace)
        response = run_request("describe", {
            "path": str(workspace / "src" / "User.php"),
            "workspace_root": str(workspace),
            "line": 10,
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
            "path": str(workspace / "src" / "Errors.php"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "Errors.php" in output
        assert "error" in output.lower()

    def test_diagnostics_undefined_variable(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "Errors.php"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "undefinedVar" in output or "undefined" in output.lower()

    def test_diagnostics_type_error(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "Errors.php"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        has_type_error = "int" in output.lower() or "type" in output.lower() or "return" in output.lower()
        assert has_type_error, f"Expected type error in output: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_not_supported(self, workspace):
        import click
        os.chdir(workspace)
        
        base_path = workspace / "src"
        
        response = run_request("move-file", {
            "old_path": str(base_path / "User.php"),
            "new_path": str(base_path / "Person.php"),
            "workspace_root": str(workspace),
        })
        assert "error" in response
        assert response["error"] == "move-file is not supported by intelephense"
        
        # Verify file was NOT moved
        assert (base_path / "User.php").exists()
        assert not (base_path / "Person.php").exists()

    # =========================================================================
    # resolve-symbol disambiguation tests
    # =========================================================================

    def test_resolve_symbol_unique_name(self, workspace):
        """Test resolving a unique symbol name."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "UserRepository",
        })
        result = response["result"]
        assert result["name"] == "UserRepository"
        assert result["kind"] == "Class"

    def test_resolve_symbol_ambiguous_shows_container_refs(self, workspace):
        """Test that ambiguous PHP symbols show Class.method format."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "save",
        })
        result = response["result"]
        assert result["error"] == "Symbol 'save' is ambiguous (3 matches)"
        assert result["total_matches"] == 3
        refs = sorted([m["ref"] for m in result["matches"]])
        assert refs == ["FileStorage.save", "MemoryStorage.save", "Storage.save"]

    def test_resolve_symbol_class_method(self, workspace):
        """Test resolving Class.method format."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "MemoryStorage.save",
        })
        result = response["result"]
        assert result["name"] == "save"
        assert result["kind"] == "Method"

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "User.php:User",
        })
        result = response["result"]
        assert result["name"] == "User"
        assert result["path"].endswith("User.php")
