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
        assert output == """\
src/User.php:53 [Method] getName in User
src/User.php:63 [Method] getEmail in User
src/User.php:73 [Method] getAge in User"""

    def test_grep_case_sensitive(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "User.php")],
            "workspace_root": str(workspace),
            "pattern": "^User$",
            "case_sensitive": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "src/User.php:10 [Class] User"
        
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "User.php")],
            "workspace_root": str(workspace),
            "pattern": "^user$",
            "case_sensitive": True,
        })
        lowercase_output = format_output(response["result"], "plain")
        assert lowercase_output == ""

    def test_grep_combined_filters(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/MemoryStorage.php:10 [Class] MemoryStorage
src/FileStorage.php:10 [Class] FileStorage"""

    def test_grep_multiple_files(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "Main.php"), str(workspace / "src" / "User.php")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["method"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/Main.php:17 [Method] createSampleUser (static) in Main
src/Main.php:28 [Method] validateUser (static) in Main
src/Main.php:47 [Method] processUsers (static) in Main
src/Main.php:58 [Method] run (static) in Main
src/User.php:53 [Method] getName in User
src/User.php:63 [Method] getEmail in User
src/User.php:73 [Method] getAge in User
src/User.php:83 [Method] isAdult in User
src/User.php:93 [Method] displayName in User"""

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": "validate",
            "case_sensitive": False,
            "kinds": ["method"],
        })
        output = format_output(response["result"], "plain")
        assert output == "src/Main.php:28 [Method] validateUser (static) in Main"

    def test_grep_exclude_pattern(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
            "exclude_patterns": ["Errors.php"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/Main.php:10 [Class] Main
src/User.php:10 [Class] User
src/MemoryStorage.php:10 [Class] MemoryStorage
src/FileStorage.php:10 [Class] FileStorage
src/UserRepository.php:10 [Class] UserRepository"""

    def test_grep_with_docs(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "Main.php")],
            "workspace_root": str(workspace),
            "pattern": "createSampleUser",
            "kinds": ["method"],
            "include_docs": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/Main.php:17 [Method] createSampleUser (static) in Main
    __LspcmdFixture\\\\Main::createSampleUser__
    
    Creates a sample user for testing.
    
    ```php
    <?php
    public static function createSampleUser(): User { }
    ```
    
    _@return_ `User` A sample user instance
"""

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

    # =========================================================================
    # show multi-line constant tests
    # =========================================================================

    def test_show_multiline_array_constant(self, workspace):
        """Test that show displays multi-line array constants correctly."""
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "User.php"),
            "workspace_root": str(workspace),
            "line": 15,
            "column": 17,
            "context": 0,
            "body": True,
            "direct_location": True,
            "range_start_line": 15,
            "range_end_line": 23,
            "kind": "Constant",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/User.php:15-23

    public const COUNTRY_CODES = [
        'US' => 'United States',
        'CA' => 'Canada',
        'GB' => 'United Kingdom',
        'DE' => 'Germany',
        'FR' => 'France',
        'JP' => 'Japan',
        'AU' => 'Australia',
    ];"""

    # =========================================================================
    # calls tests (intelephense does not support call hierarchy)
    # =========================================================================

    def test_calls_not_supported(self, workspace):
        """Test that calls returns proper error for intelephense."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "outgoing",
            "from_path": str(workspace / "src" / "Main.php"),
            "from_line": 58,
            "from_column": 23,
            "from_symbol": "run",
            "max_depth": 1,
        })
        assert "error" in response
        assert "prepareCallHierarchy" in response["error"]
        assert "intelephense" in response["error"]
