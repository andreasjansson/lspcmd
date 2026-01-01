import os
import shutil
import time

import click
import pytest

from lspcmd.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
    format_output,
    requires_clangd,
    run_request,
)


class TestCppIntegration:
    """Integration tests for C++ using clangd."""

    @pytest.fixture(autouse=True)
    def check_clangd(self):
        requires_clangd()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "cpp_project"
        dst = class_temp_dir / "cpp_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("grep", {
            "paths": [str(project / "user.hpp")],
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
            "paths": [str(workspace / "user.hpp")],
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
            "paths": [str(workspace / "user.hpp")],
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

    def test_grep_kind_filter_function(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.hpp")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
user.hpp:135 [Function] createSampleUser (User ()) in example
user.hpp:140 [Function] validateUser (void (const User &)) in example"""

    def test_grep_kind_filter_method(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.hpp")],
            "workspace_root": str(workspace),
            "pattern": "^is",
            "kinds": ["method"],
        })
        output = format_output(response["result"], "plain")
        assert output == "user.hpp:23 [Method] isAdult (bool () const) in User"

    def test_grep_case_sensitive(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.hpp")],
            "workspace_root": str(workspace),
            "pattern": "^User$",
            "case_sensitive": False,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
user.hpp:13 [Class] User (class) in example
user.hpp:15 [Constructor] User ((std::string, std::string, int)) in User"""
        
        response = run_request("grep", {
            "paths": [str(workspace / "user.hpp")],
            "workspace_root": str(workspace),
            "pattern": "^user$",
            "case_sensitive": True,
        })
        lowercase_output = format_output(response["result"], "plain")
        assert lowercase_output == "No results"

    def test_grep_combined_filters(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.hpp")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
user.hpp:37 [Class] Storage (class) in example
user.hpp:48 [Class] MemoryStorage (class) in example
user.hpp:80 [Class] FileStorage (class) in example"""

    def test_grep_multiple_files(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.hpp"), str(workspace / "main.cpp")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
user.hpp:135 [Function] createSampleUser (User ()) in example
user.hpp:140 [Function] validateUser (void (const User &)) in example
main.cpp:7 [Function] main (int ())"""

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": "validate",
            "case_sensitive": False,
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == "user.hpp:140 [Function] validateUser (void (const User &)) in example"

    def test_grep_exclude_pattern(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        all_output = format_output(response["result"], "plain")
        assert all_output == """\
user.hpp:135 [Function] createSampleUser (User ()) in example
user.hpp:140 [Function] validateUser (void (const User &)) in example
errors.cpp:6 [Function] undefinedVariable (int ())
errors.cpp:11 [Function] typeError (int ())
errors.cpp:17 [Function] missingReturn (int ())
errors.cpp:23 [Function] twoArgs (void (int, int))
errors.cpp:25 [Function] argumentError (void ())
errors.cpp:30 [Function] typeConversion (void ())
main.cpp:7 [Function] main (int ())"""
        
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
            "exclude_patterns": ["errors.cpp"],
        })
        filtered_output = format_output(response["result"], "plain")
        assert filtered_output == """\
user.hpp:135 [Function] createSampleUser (User ()) in example
user.hpp:140 [Function] validateUser (void (const User &)) in example
main.cpp:7 [Function] main (int ())"""

    def test_grep_with_docs(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.hpp")],
            "workspace_root": str(workspace),
            "pattern": "createSampleUser",
            "kinds": ["function"],
            "include_docs": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
user.hpp:135 [Function] createSampleUser (User ()) in example
    ### function `createSampleUser`  
    
    ---
    → `User`  
    Creates a sample user for testing.  
    
    ---
    ```cpp
    // In namespace example
    inline User createSampleUser()
    ```
"""

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.cpp"),
            "workspace_root": str(workspace),
            "line": 11,
            "column": 16,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "user.hpp:135 inline User createSampleUser() {"

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.cpp"),
            "workspace_root": str(workspace),
            "line": 11,
            "column": 16,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
user.hpp:135-137

inline User createSampleUser() {
    return User("John Doe", "john@example.com", 30);
}"""

    def test_definition_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.cpp"),
            "workspace_root": str(workspace),
            "line": 11,
            "column": 16,
            "context": 1,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
user.hpp:134-136
/// Creates a sample user for testing.
inline User createSampleUser() {
    return User("John Doe", "john@example.com", 30);
"""

    def test_definition_with_body_and_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.cpp"),
            "workspace_root": str(workspace),
            "line": 11,
            "column": 25,
            "context": 1,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
user.hpp:134-138

/// Creates a sample user for testing.
inline User createSampleUser() {
    return User("John Doe", "john@example.com", 30);
}
"""

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        # NOTE: This test uses set comparison instead of exact string match because
        # clangd returns references in non-deterministic order depending on indexing timing.
        # This is a deliberate exception to the rule that all tests match exact outputs.
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "user.hpp"),
            "workspace_root": str(workspace),
            "line": 13,
            "column": 6,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        expected_lines = {
            "main.cpp:11     User user = createSampleUser();",
            "user.hpp:13 class User {",
            "user.hpp:15     User(std::string name, std::string email, int age)",
            "user.hpp:41     virtual void save(const User& user) = 0;",
            "user.hpp:44     virtual std::vector<User> list() = 0;",
            "user.hpp:50     void save(const User& user) override {",
            "user.hpp:66     std::vector<User> list() override {",
            "user.hpp:67         std::vector<User> result;",
            "user.hpp:76     std::unordered_map<std::string, User> users_;",
            "user.hpp:85     void save(const User& user) override {",
            "user.hpp:99     std::vector<User> list() override {",
            "user.hpp:114     void addUser(const User& user) {",
            "user.hpp:126     std::vector<User> listUsers() {",
            "user.hpp:135 inline User createSampleUser() {",
            'user.hpp:136     return User("John Doe", "john@example.com", 30);',
            "user.hpp:140 inline void validateUser(const User& user) {",
        }
        actual_lines = set(output.strip().split("\n"))
        assert actual_lines == expected_lines

    # =========================================================================
    # implementations tests
    # =========================================================================

    def test_implementations_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "user.hpp"),
            "workspace_root": str(workspace),
            "line": 37,
            "column": 6,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert "MemoryStorage" in output
        assert "FileStorage" in output

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        os.chdir(workspace)
        response = run_request("describe", {
            "path": str(workspace / "user.hpp"),
            "workspace_root": str(workspace),
            "line": 13,
            "column": 6,
        })
        output = format_output(response["result"], "plain")
        assert "User" in output

    # =========================================================================
    # rename tests
    # =========================================================================

    def test_rename(self, workspace):
        os.chdir(workspace)
        
        # Verify User class exists before rename
        original_content = (workspace / "user.hpp").read_text()
        assert "class User {" in original_content
        
        response = run_request("rename", {
            "path": str(workspace / "user.hpp"),
            "workspace_root": str(workspace),
            "line": 13,
            "column": 6,
            "new_name": "Person",
        })
        output = format_output(response["result"], "plain")
        # clangd renames in multiple files (user.hpp and main.cpp), order may vary
        lines = output.strip().split("\n")
        assert lines[0].startswith("Renamed in")
        assert "file(s):" in lines[0]

        # Verify rename actually happened
        renamed_content = (workspace / "user.hpp").read_text()
        assert "class Person {" in renamed_content
        assert "class User {" not in renamed_content

        # Revert the rename
        run_request("rename", {
            "path": str(workspace / "user.hpp"),
            "workspace_root": str(workspace),
            "line": 13,
            "column": 6,
            "new_name": "User",
        })
        
        # Verify revert worked
        reverted_content = (workspace / "user.hpp").read_text()
        assert "class User {" in reverted_content
        assert "class Person {" not in reverted_content

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.cpp"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "errors.cpp" in output
        assert "error" in output.lower()

    def test_diagnostics_undefined_variable(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.cpp"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "undefinedVar" in output or "undeclared" in output.lower() or "not declared" in output.lower()

    def test_diagnostics_type_error(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.cpp"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        has_type_error = "cannot initialize" in output.lower() or "incompatible" in output.lower() or "invalid" in output.lower()
        assert has_type_error, f"Expected type error in output: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_not_supported(self, workspace):
        os.chdir(workspace)
        
        response = run_request("move-file", {
            "old_path": str(workspace / "user.hpp"),
            "new_path": str(workspace / "person.hpp"),
            "workspace_root": str(workspace),
        })
        assert "error" in response
        assert response["error"] == "move-file is not supported by clangd"
        
        # Verify file was NOT moved
        assert (workspace / "user.hpp").exists()
        assert not (workspace / "person.hpp").exists()

    # =========================================================================
    # resolve-symbol disambiguation tests
    # =========================================================================

    def test_resolve_symbol_unique_name(self, workspace):
        """Test resolving a unique symbol name."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "example.UserRepository",
        })
        result = response["result"]
        assert result["name"] == "UserRepository"
        assert result["kind"] == "Class"

    def test_resolve_symbol_ambiguous_shows_container_refs(self, workspace):
        """Test that ambiguous C++ symbols show Class.method format."""
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
            "symbol_path": "User.isAdult",
        })
        result = response["result"]
        assert result["name"] == "isAdult"
        assert result["kind"] == "Method"

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "main.cpp:main",
        })
        result = response["result"]
        assert result["name"] == "main"
        assert result["path"].endswith("main.cpp")
