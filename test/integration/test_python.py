import os
import shutil
import time

import click
import pytest

from lspcmd.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
    _call_replace_function_request,
    format_output,
    requires_basedpyright,
    run_request,
)


class TestPythonIntegration:
    """Integration tests for Python using basedpyright."""

    @pytest.fixture(autouse=True)
    def check_basedpyright(self):
        requires_basedpyright()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "python_project"
        dst = class_temp_dir / "python_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        # Warm up the server
        run_request("grep", {
            "paths": [str(project / "main.py")],
            "workspace_root": str(project),
            "pattern": ".*",
        })
        time.sleep(1.0)
        return project

    # =========================================================================
    # grep tests
    # =========================================================================

    def test_grep_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": ".*",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:14 [Class] StorageProtocol
main.py:17 [Method] save in StorageProtocol
main.py:17 [Variable] key in save
main.py:17 [Variable] value in save
main.py:21 [Method] load in StorageProtocol
main.py:21 [Variable] key in load
main.py:27 [Class] User
main.py:35 [Variable] name in User
main.py:36 [Variable] email in User
main.py:37 [Variable] age in User
main.py:39 [Method] is_adult in User
main.py:43 [Method] display_name in User
main.py:48 [Class] MemoryStorage
main.py:51 [Method] __init__ in MemoryStorage
main.py:54 [Method] save in MemoryStorage
main.py:54 [Variable] key in save
main.py:54 [Variable] value in save
main.py:57 [Method] load in MemoryStorage
main.py:57 [Variable] key in load
main.py:52 [Variable] _data in MemoryStorage
main.py:61 [Class] FileStorage
main.py:64 [Method] __init__ in FileStorage
main.py:64 [Variable] base_path in __init__
main.py:67 [Method] save in FileStorage
main.py:67 [Variable] key in save
main.py:67 [Variable] value in save
main.py:68 [Variable] path in save
main.py:69 [Variable] f in save
main.py:72 [Method] load in FileStorage
main.py:72 [Variable] key in load
main.py:73 [Variable] path in load
main.py:75 [Variable] f in load
main.py:65 [Variable] _base_path in FileStorage
main.py:80 [Class] UserRepository
main.py:86 [Method] __init__ in UserRepository
main.py:89 [Method] add_user in UserRepository
main.py:89 [Variable] user in add_user
main.py:93 [Method] get_user in UserRepository
main.py:93 [Variable] email in get_user
main.py:97 [Method] delete_user in UserRepository
main.py:97 [Variable] email in delete_user
main.py:104 [Method] list_users in UserRepository
main.py:108 [Method] count_users in UserRepository
main.py:87 [Variable] _users in UserRepository
main.py:113 [Function] create_sample_user
main.py:118 [Function] process_users
main.py:118 [Variable] repo in process_users
main.py:127 [Function] main
main.py:129 [Variable] repo in main
main.py:130 [Variable] user in main
main.py:138 [Variable] found in main"""

    def test_grep_pattern_filter(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": "^User",
            "case_sensitive": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:27 [Class] User
main.py:80 [Class] UserRepository"""

    def test_grep_kind_filter(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:14 [Class] StorageProtocol
main.py:27 [Class] User
main.py:48 [Class] MemoryStorage
main.py:61 [Class] FileStorage
main.py:80 [Class] UserRepository"""

    def test_grep_function_kind(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:113 [Function] create_sample_user
main.py:118 [Function] process_users
main.py:127 [Function] main"""

    def test_grep_case_sensitive(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": "user",
            "case_sensitive": False,
        })
        insensitive_output = format_output(response["result"], "plain")
        
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": "user",
            "case_sensitive": True,
        })
        sensitive_output = format_output(response["result"], "plain")
        
        assert insensitive_output == """\
main.py:27 [Class] User
main.py:80 [Class] UserRepository
main.py:89 [Method] add_user in UserRepository
main.py:89 [Variable] user in add_user
main.py:93 [Method] get_user in UserRepository
main.py:97 [Method] delete_user in UserRepository
main.py:104 [Method] list_users in UserRepository
main.py:108 [Method] count_users in UserRepository
main.py:87 [Variable] _users in UserRepository
main.py:113 [Function] create_sample_user
main.py:118 [Function] process_users
main.py:130 [Variable] user in main"""
        
        assert sensitive_output == """\
main.py:89 [Method] add_user in UserRepository
main.py:89 [Variable] user in add_user
main.py:93 [Method] get_user in UserRepository
main.py:97 [Method] delete_user in UserRepository
main.py:104 [Method] list_users in UserRepository
main.py:108 [Method] count_users in UserRepository
main.py:87 [Variable] _users in UserRepository
main.py:113 [Function] create_sample_user
main.py:118 [Function] process_users
main.py:130 [Variable] user in main"""

    def test_grep_combined_filters(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:14 [Class] StorageProtocol
main.py:48 [Class] MemoryStorage
main.py:61 [Class] FileStorage"""

    def test_grep_multiple_files(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.py"), str(workspace / "utils.py")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:113 [Function] create_sample_user
main.py:118 [Function] process_users
main.py:127 [Function] main
utils.py:9 [Function] validate_email
utils.py:22 [Function] validate_age
utils.py:27 [Function] memoize
utils.py:38 [Function] wrapper in memoize
utils.py:48 [Function] fibonacci
utils.py:125 [Function] format_name"""

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": "validate",
            "kinds": ["function"],
            "exclude_patterns": ["editable*"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
utils.py:9 [Function] validate_email
utils.py:22 [Function] validate_age"""

    def test_grep_exclude_pattern(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
            "exclude_patterns": ["editable*"],
        })
        all_output = format_output(response["result"], "plain")
        
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
            "exclude_patterns": ["utils.py", "editable*"],
        })
        filtered_output = format_output(response["result"], "plain")
        
        assert all_output == """\
utils.py:9 [Function] validate_email
utils.py:22 [Function] validate_age
utils.py:27 [Function] memoize
utils.py:38 [Function] wrapper in memoize
utils.py:48 [Function] fibonacci
utils.py:125 [Function] format_name
errors.py:4 [Function] undefined_variable
errors.py:9 [Function] type_error
errors.py:15 [Function] missing_return
main.py:113 [Function] create_sample_user
main.py:118 [Function] process_users
main.py:127 [Function] main"""
        
        assert filtered_output == """\
errors.py:4 [Function] undefined_variable
errors.py:9 [Function] type_error
errors.py:15 [Function] missing_return
main.py:113 [Function] create_sample_user
main.py:118 [Function] process_users
main.py:127 [Function] main"""

    def test_grep_with_docs(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": "^create_sample_user$",
            "kinds": ["function"],
            "include_docs": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:113 [Function] create_sample_user
    ```python
    (function) def create_sample_user() -> User
    ```
    ---
    Create a sample user for testing.
"""

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 130,
            "column": 11,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "main.py:113 def create_sample_user() -> User:"

    def test_definition_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 130,
            "column": 11,
            "context": 2,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:111-115


def create_sample_user() -> User:
    \"\"\"Create a sample user for testing.\"\"\"
    return User(name="John Doe", email="john@example.com", age=30)
"""

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 130,
            "column": 11,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:113-115

def create_sample_user() -> User:
    \"\"\"Create a sample user for testing.\"\"\"
    return User(name="John Doe", email="john@example.com", age=30)"""

    def test_definition_with_body_and_context(self, workspace):
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 130,
            "column": 11,
            "context": 2,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:111-117



def create_sample_user() -> User:
    \"\"\"Create a sample user for testing.\"\"\"
    return User(name="John Doe", email="john@example.com", age=30)

"""

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 27,
            "column": 6,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:27 class User:
main.py:87         self._users: dict[str, User] = {}
main.py:89     def add_user(self, user: User) -> None:
main.py:93     def get_user(self, email: str) -> Optional[User]:
main.py:104     def list_users(self) -> list[User]:
main.py:113 def create_sample_user() -> User:
main.py:115     return User(name="John Doe", email="john@example.com", age=30)"""

    def test_references_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 27,
            "column": 6,
            "context": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:26-28
@dataclass
class User:
    \"\"\"Represents a user in the system.

main.py:86-88
    def __init__(self) -> None:
        self._users: dict[str, User] = {}


main.py:88-90

    def add_user(self, user: User) -> None:
        \"\"\"Add a user to the repository.\"\"\"

main.py:92-94

    def get_user(self, email: str) -> Optional[User]:
        \"\"\"Retrieve a user by email address.\"\"\"

main.py:103-105

    def list_users(self) -> list[User]:
        \"\"\"List all users in the repository.\"\"\"

main.py:112-114

def create_sample_user() -> User:
    \"\"\"Create a sample user for testing.\"\"\"

main.py:114-116
    \"\"\"Create a sample user for testing.\"\"\"
    return User(name="John Doe", email="john@example.com", age=30)

"""

    # =========================================================================
    # describe (hover) tests
    # =========================================================================


    # =========================================================================
    # rename tests (uses isolated editable files)
    # =========================================================================

    def test_rename(self, workspace):
        os.chdir(workspace)
        
        editable_path = workspace / "editable.py"
        consumer_path = workspace / "editable_consumer.py"
        original_editable = editable_path.read_text()
        original_consumer = consumer_path.read_text()
        
        try:
            assert "class EditablePerson:" in original_editable
            assert "from editable import EditablePerson" in original_consumer
            
            response = run_request("rename", {
                "path": str(editable_path),
                "workspace_root": str(workspace),
                "line": 11,
                "column": 6,
                "new_name": "RenamedPerson",
            })
            output = format_output(response["result"], "plain")
            assert output == """\
Renamed in 2 file(s):
  editable.py
  editable_consumer.py"""

            renamed_editable = editable_path.read_text()
            renamed_consumer = consumer_path.read_text()
            assert "class RenamedPerson:" in renamed_editable
            assert "class EditablePerson:" not in renamed_editable
            assert "from editable import RenamedPerson" in renamed_consumer
            assert "from editable import EditablePerson" not in renamed_consumer
        finally:
            editable_path.write_text(original_editable)
            consumer_path.write_text(original_consumer)

    # =========================================================================
    # declaration tests
    # =========================================================================

    def test_declaration_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("declaration", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 27,
            "column": 6,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == "main.py:27 class User:"

    # =========================================================================
    # implementations tests
    # =========================================================================

    def test_implementations(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 14,
            "column": 6,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:14 class StorageProtocol(Protocol):
main.py:48 class MemoryStorage:
main.py:61 class FileStorage:
editable.py:30 class EditableStorage:"""

    # =========================================================================
    # subtypes/supertypes tests (not supported by pyright)
    # =========================================================================

    def test_subtypes_not_supported(self, workspace):
        os.chdir(workspace)
        response = run_request("subtypes", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 14,
            "column": 6,
            "context": 0,
        })
        assert "error" in response
        assert "prepareTypeHierarchy" in response["error"]

    def test_supertypes_not_supported(self, workspace):
        os.chdir(workspace)
        response = run_request("supertypes", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 48,
            "column": 6,
            "context": 0,
        })
        assert "error" in response
        assert "prepareTypeHierarchy" in response["error"]

    # =========================================================================
    # move-file tests (uses isolated editable files)
    # =========================================================================

    def test_move_file_updates_imports(self, workspace):
        os.chdir(workspace)
        
        editable_path = workspace / "editable.py"
        consumer_path = workspace / "editable_consumer.py"
        renamed_editable_path = workspace / "editable_renamed.py"
        
        original_editable = editable_path.read_text()
        original_consumer = consumer_path.read_text()
        
        try:
            assert editable_path.exists()
            assert "from editable import EditablePerson" in original_consumer
            
            response = run_request("move-file", {
                "old_path": str(editable_path),
                "new_path": str(renamed_editable_path),
                "workspace_root": str(workspace),
            })
            output = format_output(response["result"], "plain")
            
            assert not editable_path.exists()
            assert renamed_editable_path.exists()
            
            assert "Moved file and updated imports" in output
            assert "editable_consumer.py" in output
            assert "editable_renamed.py" in output
            
            updated_consumer = consumer_path.read_text()
            assert "from editable_renamed import EditablePerson" in updated_consumer
            assert "from editable import EditablePerson" not in updated_consumer
        finally:
            if renamed_editable_path.exists():
                renamed_editable_path.unlink()
            editable_path.write_text(original_editable)
            consumer_path.write_text(original_consumer)

    # =========================================================================
    # replace-function tests (uses isolated editable files)
    # =========================================================================

    def test_replace_function_basic(self, workspace):
        """Test basic function replacement with signature check."""
        os.chdir(workspace)
        
        editable_path = workspace / "editable.py"
        original = editable_path.read_text()
        
        try:
            response = _call_replace_function_request({
                "workspace_root": str(workspace),
                "symbol": "editable_create_sample",
                "new_contents": '''def editable_create_sample() -> EditablePerson:
    """Create an editable sample for testing."""
    return EditablePerson(name="Jane Doe", email="jane@example.com")''',
                "check_signature": True,
            })
            result = response["result"]
            assert result["replaced"] == True
            assert result["path"] == "editable.py"
            
            updated = editable_path.read_text()
            assert 'Jane Doe' in updated
            assert 'jane@example.com' in updated
        finally:
            editable_path.write_text(original)

    def test_replace_function_signature_mismatch(self, workspace):
        """Test that signature change is detected or rejected."""
        os.chdir(workspace)
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "editable_create_sample",
            "new_contents": '''def editable_create_sample(extra_param: str) -> EditablePerson:
    """Create an editable sample for testing."""
    return EditablePerson(name="Jane Doe", email="jane@example.com")''',
            "check_signature": True,
        })
        result = response["result"]
        assert "error" in result
        assert "Signature mismatch" in result["error"] or "Could not extract signature" in result["error"]

    def test_replace_function_no_check_signature(self, workspace):
        """Test that --no-check-signature allows signature changes."""
        os.chdir(workspace)
        
        editable_path = workspace / "editable.py"
        original = editable_path.read_text()
        
        try:
            response = _call_replace_function_request({
                "workspace_root": str(workspace),
                "symbol": "editable_create_sample",
                "new_contents": '''def editable_create_sample(name: str = "Default") -> EditablePerson:
    """Create an editable sample for testing."""
    return EditablePerson(name=name, email="default@example.com")''',
                "check_signature": False,
            })
            result = response["result"]
            assert result["replaced"] == True
            
            updated = editable_path.read_text()
            assert 'name: str = "Default"' in updated
        finally:
            editable_path.write_text(original)

    def test_replace_method_basic(self, workspace):
        """Test replacing a method within a class."""
        os.chdir(workspace)
        
        editable_path = workspace / "editable.py"
        original = editable_path.read_text()
        
        try:
            response = _call_replace_function_request({
                "workspace_root": str(workspace),
                "symbol": "EditableStorage.save",
                "new_contents": '''    def save(self, key: str, value: str) -> None:
        """Save with logging."""
        print(f"Saving {key}")
        self._data[key] = value''',
                "check_signature": False,
            })
            result = response["result"]
            assert result["replaced"] == True
            
            updated = editable_path.read_text()
            assert 'print(f"Saving {key}")' in updated
        finally:
            editable_path.write_text(original)

    def test_replace_function_non_function_error(self, workspace):
        """Test that replacing a non-function symbol gives an error."""
        os.chdir(workspace)
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "EditablePerson",
            "new_contents": '''class EditablePerson:
    pass''',
            "check_signature": True,
        })
        result = response["result"]
        assert "error" in result
        assert "not a Function or Method" in result["error"]

    def test_replace_function_bogus_content(self, workspace):
        """Test replacing with bogus content (with signature check disabled)."""
        os.chdir(workspace)
        
        editable_path = workspace / "editable.py"
        original = editable_path.read_text()
        
        try:
            response = _call_replace_function_request({
                "workspace_root": str(workspace),
                "symbol": "editable_create_sample",
                "new_contents": "def editable_create_sample(): pass  # minimal valid replacement",
                "check_signature": False,
            })
            result = response["result"]
            assert result["replaced"] == True
        finally:
            editable_path.write_text(original)

    def test_replace_function_symbol_not_found(self, workspace):
        """Test error when symbol doesn't exist."""
        os.chdir(workspace)
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "nonexistent_function",
            "new_contents": "def nonexistent_function(): pass",
            "check_signature": True,
        })
        result = response["result"]
        assert "error" in result
        assert "not found" in result["error"]

    def test_replace_function_empty_content(self, workspace):
        """Test that empty content fails gracefully."""
        os.chdir(workspace)
        
        main_path = workspace / "main.py"
        original = main_path.read_text()
        
        response = _call_replace_function_request({
            "workspace_root": str(workspace),
            "symbol": "create_sample_user",
            "new_contents": "",
            "check_signature": True,
        })
        result = response["result"]
        # Empty content should cause a signature mismatch or other error
        assert "error" in result
        
        # Verify file was reverted
        current = main_path.read_text()
        assert current == original

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
        assert result["line"] == 27
        assert result["kind"] == "Class"

    def test_resolve_symbol_ambiguous_shows_container_refs(self, workspace):
        """Test that ambiguous symbols show Container.name format in refs."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "save",
        })
        result = response["result"]
        assert result["error"] == "Symbol 'save' is ambiguous (4 matches)"
        assert result["total_matches"] == 4
        refs = sorted([m["ref"] for m in result["matches"]])
        assert refs == ["EditableStorage.save", "FileStorage.save", "MemoryStorage.save", "StorageProtocol.save"]

    def test_resolve_symbol_qualified_name(self, workspace):
        """Test resolving Container.name format."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "MemoryStorage.save",
        })
        result = response["result"]
        assert result["name"] == "save"
        assert result["line"] == 54
        assert result["kind"] == "Method"

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "main.py:User",
        })
        result = response["result"]
        assert result["name"] == "User"
        assert result["line"] == 27
        assert result["path"].endswith("main.py")

    # =========================================================================
    # show multi-line constant/variable tests
    # =========================================================================

    def test_show_multiline_dict_constant(self, workspace):
        """Test that show expands multi-line dict constants correctly."""
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "utils.py"),
            "workspace_root": str(workspace),
            "line": 130,
            "column": 0,
            "context": 0,
            "body": True,
            "direct_location": True,
            "range_start_line": 130,
            "range_end_line": 130,
            "kind": "Constant",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
utils.py:130-138

COUNTRY_CODES = {
    "US": "United States",
    "CA": "Canada",
    "GB": "United Kingdom",
    "DE": "Germany",
    "FR": "France",
    "JP": "Japan",
    "AU": "Australia",
}"""

    def test_show_multiline_list_constant(self, workspace):
        """Test that show expands multi-line list constants correctly."""
        os.chdir(workspace)
        response = run_request("show", {
            "path": str(workspace / "utils.py"),
            "workspace_root": str(workspace),
            "line": 140,
            "column": 0,
            "context": 0,
            "body": True,
            "direct_location": True,
            "range_start_line": 140,
            "range_end_line": 140,
            "kind": "Constant",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
utils.py:140-145

DEFAULT_CONFIG = [
    "debug=false",
    "timeout=30",
    "max_retries=3",
    "log_level=INFO",
]"""

    # =========================================================================
    # calls tests
    # =========================================================================

    def test_calls_outgoing(self, workspace):
        """Test outgoing calls from create_sample_user (only calls User)."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "outgoing",
            "from_path": str(workspace / "main.py"),
            "from_line": 113,
            "from_column": 4,
            "from_symbol": "create_sample_user",
            "max_depth": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:113 [Function] create_sample_user

Outgoing calls:
  └── main.py:27 [Class] User"""

    def test_calls_incoming(self, workspace):
        """Test incoming calls to create_sample_user function."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "incoming",
            "to_path": str(workspace / "main.py"),
            "to_line": 113,
            "to_column": 4,
            "to_symbol": "create_sample_user",
            "max_depth": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.py:113 [Function] create_sample_user

Incoming calls:
  └── main.py:127 [Function] main"""

    def test_calls_path_found(self, workspace):
        """Test finding call path between two functions."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "path",
            "from_path": str(workspace / "main.py"),
            "from_line": 127,
            "from_column": 4,
            "from_symbol": "main",
            "to_path": str(workspace / "main.py"),
            "to_line": 113,
            "to_column": 4,
            "to_symbol": "create_sample_user",
            "max_depth": 3,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
Call path:
main.py:127 [Function] main
  → main.py:113 [Function] create_sample_user"""

    def test_calls_path_not_found(self, workspace):
        """Test call path when no path exists."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "path",
            "from_path": str(workspace / "main.py"),
            "from_line": 113,
            "from_column": 4,
            "from_symbol": "create_sample_user",
            "to_path": str(workspace / "main.py"),
            "to_line": 127,
            "to_column": 4,
            "to_symbol": "main",
            "max_depth": 3,
        })
        output = format_output(response["result"], "plain")
        assert output == "No call path found from 'create_sample_user' to 'main' within depth 3"

    def test_calls_outgoing_include_non_workspace(self, workspace):
        """Test outgoing calls with --include-non-workspace shows stdlib calls."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "outgoing",
            "from_path": str(workspace / "utils.py"),
            "from_line": 9,
            "from_column": 4,
            "from_symbol": "validate_email",
            "max_depth": 1,
            "include_non_workspace": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
utils.py:9 [Function] validate_email

Outgoing calls:
  ├── [Class] bool
  ├── [Function] match
  └── [Function] match"""

    def test_calls_outgoing_excludes_stdlib_by_default(self, workspace):
        """Test outgoing calls without --include-non-workspace excludes stdlib."""
        os.chdir(workspace)
        response = run_request("calls", {
            "workspace_root": str(workspace),
            "mode": "outgoing",
            "from_path": str(workspace / "utils.py"),
            "from_line": 9,
            "from_column": 4,
            "from_symbol": "validate_email",
            "max_depth": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
utils.py:9 [Function] validate_email

Outgoing calls:"""
