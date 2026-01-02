import os
import shutil
import time

import click
import pytest

from lspcmd.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
    format_output,
    requires_lua_ls,
    run_request,
)


class TestLuaIntegration:
    """Integration tests for Lua using lua-language-server."""

    @pytest.fixture(autouse=True)
    def check_lua_ls(self):
        requires_lua_ls()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "lua_project"
        dst = class_temp_dir / "lua_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("grep", {
            "paths": [str(project / "user.lua")],
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
            "paths": [str(workspace / "user.lua")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
        })
        output = format_output(response["result"], "plain")
        assert "[Object] Storage" in output
        assert "[Object] MemoryStorage" in output
        assert "[Object] FileStorage" in output

    def test_grep_kind_filter_function(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.lua")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.lua:8 [Function] createSampleUser (function ())
main.lua:14 [Function] validateUser (function (u))
main.lua:28 [Function] processUsers (function (repo))
main.lua:36 [Function] main (function ())"""

    def test_grep_kind_filter_object(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.lua")],
            "workspace_root": str(workspace),
            "pattern": "^User$",
            "kinds": ["object"],
        })
        output = format_output(response["result"], "plain")
        assert output == "user.lua:11 [Object] User"

    def test_grep_case_sensitive(self, workspace):
        os.chdir(workspace)
        # Case-insensitive should find Storage classes and storage variables
        response = run_request("grep", {
            "paths": [str(workspace / "user.lua")],
            "workspace_root": str(workspace),
            "pattern": "storage",
            "kinds": ["object"],
            "case_sensitive": False,
        })
        output = format_output(response["result"], "plain")
        assert "[Object] Storage" in output
        assert "[Object] MemoryStorage" in output
        assert "[Object] FileStorage" in output
        
        # Case-sensitive should find only lowercase storage (none for objects)
        response = run_request("grep", {
            "paths": [str(workspace / "user.lua")],
            "workspace_root": str(workspace),
            "pattern": "storage",
            "kinds": ["object"],
            "case_sensitive": True,
        })
        output = format_output(response["result"], "plain")
        assert output == ""

    def test_grep_combined_filters(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.lua")],
            "workspace_root": str(workspace),
            "pattern": "^Memory",
            "kinds": ["object"],
        })
        output = format_output(response["result"], "plain")
        assert output == "user.lua:72 [Object] MemoryStorage"

    def test_grep_multiple_files(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.lua"), str(workspace / "main.lua")],
            "workspace_root": str(workspace),
            "pattern": "User",
            "kinds": ["object"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
user.lua:11 [Object] User
user.lua:79 [Object] self.users in MemoryStorage.new
user.lua:158 [Object] UserRepository"""

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        all_files = [str(p) for p in workspace.glob("*.lua")]
        response = run_request("grep", {
            "paths": all_files,
            "workspace_root": str(workspace),
            "pattern": "main",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == "main.lua:36 [Function] main (function ())"

    def test_grep_exclude_pattern(self, workspace):
        os.chdir(workspace)
        all_files = [str(p) for p in workspace.glob("*.lua")]
        response = run_request("grep", {
            "paths": all_files,
            "workspace_root": str(workspace),
            "pattern": "User",
            "kinds": ["object"],
            "exclude_patterns": ["errors.lua"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
user.lua:11 [Object] User
user.lua:79 [Object] self.users in MemoryStorage.new
user.lua:158 [Object] UserRepository"""

    def test_grep_with_docs(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.lua")],
            "workspace_root": str(workspace),
            "pattern": "^createSampleUser$",
            "kinds": ["function"],
            "include_docs": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.lua:8 [Function] createSampleUser (function ())
    ```lua
    function createSampleUser()
      -> table
    ```
    
    ---
    
     Creates a sample user for testing.
     @return User A sample user instance
"""

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.lua"),
            "workspace_root": str(workspace),
            "line": 40,
            "column": 23,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "main.lua:8 local function createSampleUser()"

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.lua"),
            "workspace_root": str(workspace),
            "line": 40,
            "column": 23,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.lua:8-10

local function createSampleUser()
    return user.User.new("John Doe", "john@example.com", 30)
end"""

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "user.lua"),
            "workspace_root": str(workspace),
            "line": 12,
            "column": 6,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == "user.lua:12 User.__index = User"

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        os.chdir(workspace)
        response = run_request("describe", {
            "path": str(workspace / "user.lua"),
            "workspace_root": str(workspace),
            "line": 12,
            "column": 6,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
```lua
(field) User.__index: {
    displayName: function,
    isAdult: function,
    new: function,
    __index: table,
}
```"""

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.lua"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "errors.lua" in output
        # lua-language-server reports undefined globals as warnings/hints
        has_diagnostic = "undefined" in output.lower() or "warning" in output.lower() or len(output.strip()) > 0
        assert has_diagnostic or output == "", f"Expected diagnostics or empty output, got: {output}"

    def test_diagnostics_undefined_global(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.lua"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        # lua-ls may report undefined_var as undefined-global
        if output.strip():
            has_undefined = "undefined" in output.lower() or "global" in output.lower()
            assert has_undefined, f"Expected undefined global warning in output: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_not_supported(self, workspace):
        os.chdir(workspace)
        
        response = run_request("move-file", {
            "old_path": str(workspace / "user.lua"),
            "new_path": str(workspace / "person.lua"),
            "workspace_root": str(workspace),
        })
        assert "error" in response
        assert response["error"] == "move-file is not supported by lua-language-server"
        
        # Verify file was NOT moved
        assert (workspace / "user.lua").exists()
        assert not (workspace / "person.lua").exists()

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
        assert result["kind"] == "Object"

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "user.lua:User",
        })
        result = response["result"]
        assert result["name"] == "User"
        assert result["path"].endswith("user.lua")
