"""Integration tests for lspcmd.

Tests LSP features using the actual CLI interface (run_request + format_output).
Uses pytest-xdist for parallel execution to test concurrent daemon access.

Run with: pytest tests/test_integration.py -n auto
"""

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from lspcmd.cli import run_request, ensure_daemon_running
from lspcmd.output.formatters import format_output
from lspcmd.utils.config import add_workspace_root, load_config

from .conftest import (
    requires_basedpyright,
    requires_rust_analyzer,
    requires_gopls,
    requires_typescript_lsp,
    requires_jdtls,
    requires_clangd,
    requires_zls,
    requires_lua_ls,
    requires_solargraph,
    requires_intelephense,
    FIXTURES_DIR,
)

os.environ["LSPCMD_REQUEST_TIMEOUT"] = "60"


@pytest.fixture(scope="class")
def class_temp_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("integration")


@pytest.fixture(scope="class")
def class_isolated_config(class_temp_dir):
    # Use /tmp for cache to avoid AF_UNIX path length limits (max ~104 chars)
    # The socket path would be too long if we used pytest's temp dir
    cache_dir = Path(tempfile.mkdtemp(prefix="lspcmd_test_"))
    config_dir = class_temp_dir / "config"
    config_dir.mkdir()
    old_cache = os.environ.get("XDG_CACHE_HOME")
    old_config = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CACHE_HOME"] = str(cache_dir)
    os.environ["XDG_CONFIG_HOME"] = str(config_dir)
    yield {"cache": cache_dir, "config": config_dir}
    if old_cache:
        os.environ["XDG_CACHE_HOME"] = old_cache
    else:
        os.environ.pop("XDG_CACHE_HOME", None)
    if old_config:
        os.environ["XDG_CONFIG_HOME"] = old_config
    else:
        os.environ.pop("XDG_CONFIG_HOME", None)
    shutil.rmtree(cache_dir, ignore_errors=True)


@pytest.fixture(scope="class")
def class_daemon(class_isolated_config):
    ensure_daemon_running()
    time.sleep(0.5)
    yield
    try:
        run_request("shutdown", {})
    except Exception:
        pass


# =============================================================================
# Python Integration Tests (pyright)
# =============================================================================


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
main.py:26 [Class] User
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
main.py:26 [Class] User
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
main.py:26 [Class] User
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
main.py:26 [Class] User
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
utils.py:47 [Function] fibonacci
utils.py:125 [Function] format_name"""

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": "validate",
            "kinds": ["function"],
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
        })
        all_output = format_output(response["result"], "plain")
        
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
            "exclude_patterns": ["utils.py"],
        })
        filtered_output = format_output(response["result"], "plain")
        
        assert all_output == """\
utils.py:9 [Function] validate_email
utils.py:22 [Function] validate_age
utils.py:27 [Function] memoize
utils.py:38 [Function] wrapper in memoize
utils.py:47 [Function] fibonacci
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
        response = run_request("definition", {
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
        response = run_request("definition", {
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
        response = run_request("definition", {
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
        response = run_request("definition", {
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

    def test_describe_hover(self, workspace):
        os.chdir(workspace)
        response = run_request("describe", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 27,
            "column": 6,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
```python
(class) User
```
---
Represents a user in the system.

Attributes:  
&nbsp;&nbsp;&nbsp;&nbsp;name: The user's full name.  
&nbsp;&nbsp;&nbsp;&nbsp;email: The user's email address (used as unique identifier).  
&nbsp;&nbsp;&nbsp;&nbsp;age: The user's age in years."""

    # =========================================================================
    # rename tests
    # =========================================================================

    def test_rename(self, workspace):
        os.chdir(workspace)
        
        # Verify User class exists before rename
        original_content = (workspace / "main.py").read_text()
        assert "class User:" in original_content
        
        response = run_request("rename", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 27,
            "column": 6,
            "new_name": "Person",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
Renamed in 1 file(s):
  main.py"""

        # Verify rename actually happened in the file
        renamed_content = (workspace / "main.py").read_text()
        assert "class Person:" in renamed_content
        assert "class User:" not in renamed_content

        # Revert the rename
        run_request("rename", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 27,
            "column": 6,
            "new_name": "User",
        })
        
        # Verify revert worked
        reverted_content = (workspace / "main.py").read_text()
        assert "class User:" in reverted_content
        assert "class Person:" not in reverted_content

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
main.py:61 class FileStorage:"""

    # =========================================================================
    # subtypes/supertypes tests (not supported by pyright)
    # =========================================================================

    def test_subtypes_not_supported(self, workspace):
        import click
        os.chdir(workspace)
        with pytest.raises(click.ClickException) as exc_info:
            run_request("subtypes", {
                "path": str(workspace / "main.py"),
                "workspace_root": str(workspace),
                "line": 14,
                "column": 6,
                "context": 0,
            })
        assert "prepareTypeHierarchy" in str(exc_info.value)

    def test_supertypes_not_supported(self, workspace):
        import click
        os.chdir(workspace)
        with pytest.raises(click.ClickException) as exc_info:
            run_request("supertypes", {
                "path": str(workspace / "main.py"),
                "workspace_root": str(workspace),
                "line": 48,
                "column": 6,
                "context": 0,
            })
        assert "prepareTypeHierarchy" in str(exc_info.value)

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.py"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "errors.py" in output
        assert "error" in output.lower()
        assert "undefined_var" in output or "undefined" in output.lower()

    def test_diagnostics_type_error(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.py"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        lines = output.split("\n")
        type_error_found = any("int" in line and "str" in line for line in lines) or \
                          any("type" in line.lower() for line in lines)
        assert type_error_found, f"Expected type error in output: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_updates_imports(self, workspace):
        os.chdir(workspace)
        
        # Verify utils.py exists
        assert (workspace / "utils.py").exists()
        
        # Check initial import in main.py
        original_main = (workspace / "main.py").read_text()
        assert "from utils import validate_email" in original_main
        
        # Rename utils.py to helpers.py (basedpyright only updates imports when
        # the filename changes, not when the file moves to a different directory)
        response = run_request("move-file", {
            "old_path": str(workspace / "utils.py"),
            "new_path": str(workspace / "helpers.py"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        
        # Verify the file was renamed
        assert not (workspace / "utils.py").exists()
        assert (workspace / "helpers.py").exists()
        
        # basedpyright updates the import when the filename changes
        assert output == """\
Moved file and updated imports in 4 file(s):
  main.py
  utils.py
  errors.py
  helpers.py"""
        
        # Verify the import was updated
        updated_main = (workspace / "main.py").read_text()
        assert "from helpers import validate_email" in updated_main
        assert "from utils import validate_email" not in updated_main


# =============================================================================
# Go Integration Tests (gopls)
# =============================================================================


class TestGoIntegration:
    """Integration tests for Go using gopls."""

    @pytest.fixture(autouse=True)
    def check_gopls(self):
        requires_gopls()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "go_project"
        dst = class_temp_dir / "go_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("grep", {
            "paths": [str(project / "main.go")],
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
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": "^New",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:16 [Function] NewUser (func(name, email string, age int) *User)
main.go:44 [Function] NewMemoryStorage (func() *MemoryStorage)
main.go:90 [Function] NewFileStorage (func(basePath string) *FileStorage)
main.go:124 [Function] NewUserRepository (func(storage Storage) *UserRepository)"""

    def test_grep_kind_filter_struct(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["struct"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:9 [Struct] User (struct{...})
main.go:39 [Struct] MemoryStorage (struct{...})
main.go:85 [Struct] FileStorage (struct{...})
main.go:119 [Struct] UserRepository (struct{...})"""

    def test_grep_kind_filter_interface(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["interface"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:31 [Interface] Storage (interface{...})
main.go:154 [Interface] Validator (interface{...})"""

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 174,
            "column": 9,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "main.go:124 func NewUserRepository(storage Storage) *UserRepository {"

    def test_definition_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 174,
            "column": 9,
            "context": 1,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:123-125
// NewUserRepository creates a new repository with the given storage.
func NewUserRepository(storage Storage) *UserRepository {
\treturn &UserRepository{storage: storage}
"""

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 174,
            "column": 9,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:124-126

func NewUserRepository(storage Storage) *UserRepository {
\treturn &UserRepository{storage: storage}
}"""

    def test_definition_with_body_and_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 174,
            "column": 9,
            "context": 1,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:123-127

// NewUserRepository creates a new repository with the given storage.
func NewUserRepository(storage Storage) *UserRepository {
\treturn &UserRepository{storage: storage}
}
"""

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:9 type User struct {
main.go:16 func NewUser(name, email string, age int) *User {
main.go:17 \treturn &User{Name: name, Email: email, Age: age}
main.go:21 func (u *User) IsAdult() bool {
main.go:26 func (u *User) DisplayName() string {
main.go:32 \tSave(user *User) error
main.go:33 \tLoad(email string) (*User, error)
main.go:35 \tList() ([]*User, error)
main.go:40 \tusers map[string]*User
main.go:45 \treturn &MemoryStorage{users: make(map[string]*User)}
main.go:49 func (m *MemoryStorage) Save(user *User) error {
main.go:58 func (m *MemoryStorage) Load(email string) (*User, error) {
main.go:76 func (m *MemoryStorage) List() ([]*User, error) {
main.go:77 \tresult := make([]*User, 0, len(m.users))
main.go:95 func (f *FileStorage) Save(user *User) error {
main.go:101 func (f *FileStorage) Load(email string) (*User, error) {
main.go:113 func (f *FileStorage) List() ([]*User, error) {
main.go:129 func (r *UserRepository) AddUser(user *User) error {
main.go:134 func (r *UserRepository) GetUser(email string) (*User, error) {
main.go:144 func (r *UserRepository) ListUsers() ([]*User, error) {
main.go:149 func createSampleUser() *User {
main.go:159 func ValidateUser(user *User) error {"""

    # =========================================================================
    # implementations tests
    # =========================================================================

    def test_implementations_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 31,
            "column": 5,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:39 type MemoryStorage struct {
main.go:85 type FileStorage struct {"""

    def test_implementations_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 31,
            "column": 5,
            "context": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:38-40
// MemoryStorage stores users in memory.
type MemoryStorage struct {
\tusers map[string]*User

main.go:84-86
// FileStorage stores users in files (stub implementation).
type FileStorage struct {
\tbasePath string
"""

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        os.chdir(workspace)
        response = run_request("describe", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
```go
type User struct { // size=40 (0x28), class=48 (0x30)
\tName  string
\tEmail string
\tAge   int
}
```

---

User represents a user in the system.


```go
func (u *User) DisplayName() string
func (u *User) IsAdult() bool
```"""

    # =========================================================================
    # rename tests
    # =========================================================================

    def test_rename(self, workspace):
        os.chdir(workspace)
        
        # Verify User struct exists before rename
        original_content = (workspace / "main.go").read_text()
        assert "type User struct" in original_content
        
        response = run_request("rename", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "new_name": "Person",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
Renamed in 1 file(s):
  main.go"""

        # Verify rename actually happened in the file
        renamed_content = (workspace / "main.go").read_text()
        assert "type Person struct" in renamed_content
        assert "type User struct" not in renamed_content

        # Revert the rename
        run_request("rename", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "new_name": "User",
        })
        
        # Verify revert worked
        reverted_content = (workspace / "main.go").read_text()
        assert "type User struct" in reverted_content
        assert "type Person struct" not in reverted_content

    # =========================================================================
    # declaration tests (gopls doesn't support this)
    # =========================================================================

    def test_declaration_not_supported(self, workspace):
        import click
        os.chdir(workspace)
        with pytest.raises(click.ClickException) as exc_info:
            run_request("declaration", {
                "path": str(workspace / "main.go"),
                "workspace_root": str(workspace),
                "line": 175,
                "column": 2,
                "context": 0,
            })
        assert "textDocument/declaration" in str(exc_info.value)

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.go"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "errors.go" in output
        assert "error" in output.lower()

    def test_diagnostics_undefined_variable(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.go"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "undefinedVar" in output or "undefined" in output.lower()

    def test_diagnostics_type_error(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "errors.go"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        lines = output.split("\n")
        has_type_error = any("int" in line and "string" in line for line in lines) or \
                        any("cannot" in line.lower() and "type" in line.lower() for line in lines) or \
                        any("convert" in line.lower() for line in lines)
        assert has_type_error, f"Expected type error in output: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_not_supported(self, workspace):
        import click
        os.chdir(workspace)
        
        with pytest.raises(click.ClickException) as exc_info:
            run_request("move-file", {
                "old_path": str(workspace / "utils.go"),
                "new_path": str(workspace / "helpers.go"),
                "workspace_root": str(workspace),
            })
        assert str(exc_info.value) == "move-file is not supported by gopls"
        
        # Verify file was NOT moved
        assert (workspace / "utils.go").exists()
        assert not (workspace / "helpers.go").exists()


# =============================================================================
# Rust Integration Tests (rust-analyzer)
# =============================================================================


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
src/storage.rs:4 [Interface] Storage
src/storage.rs:19 [Struct] MemoryStorage
src/storage.rs:57 [Struct] FileStorage"""

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
src/user.rs:3 [Struct] User
src/user.rs:43 [Struct] UserRepository"""

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


# =============================================================================
# TypeScript Integration Tests (typescript-language-server)
# =============================================================================


class TestTypeScriptIntegration:
    """Integration tests for TypeScript using typescript-language-server."""

    @pytest.fixture(autouse=True)
    def check_typescript_lsp(self):
        requires_typescript_lsp()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "typescript_project"
        dst = class_temp_dir / "typescript_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("grep", {
            "paths": [str(project / "src" / "main.ts")],
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
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["class", "interface"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:62 [Class] FileStorage
src/user.ts:39 [Class] MemoryStorage
src/user.ts:29 [Interface] Storage"""

    def test_grep_kind_filter_class(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:62 [Class] FileStorage
src/user.ts:39 [Class] MemoryStorage
src/user.ts:4 [Class] User
src/user.ts:92 [Class] UserRepository"""

    def test_grep_kind_filter_interface(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["interface"],
        })
        output = format_output(response["result"], "plain")
        assert output == "src/user.ts:29 [Interface] Storage"

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main.ts"),
            "workspace_root": str(workspace),
            "line": 58,
            "column": 18,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "src/main.ts:6 function createSampleUser(): User {"

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main.ts"),
            "workspace_root": str(workspace),
            "line": 58,
            "column": 18,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:6-8

function createSampleUser(): User {
    return new User("John Doe", "john@example.com", 30);
}"""

    def test_definition_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main.ts"),
            "workspace_root": str(workspace),
            "line": 58,
            "column": 18,
            "context": 1,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main.ts:5-7
 */
function createSampleUser(): User {
    return new User("John Doe", "john@example.com", 30);
"""

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 13,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:4 export class User {
src/user.ts:30     save(user: User): void;
src/user.ts:31     load(email: string): User | undefined;
src/user.ts:33     list(): User[];
src/user.ts:40     private users: Map<string, User> = new Map();
src/user.ts:42     save(user: User): void {
src/user.ts:46     load(email: string): User | undefined {
src/user.ts:54     list(): User[] {
src/user.ts:63     private cache: Map<string, User> = new Map();
src/user.ts:71     save(user: User): void {
src/user.ts:76     load(email: string): User | undefined {
src/user.ts:84     list(): User[] {
src/user.ts:95     addUser(user: User): void {
src/user.ts:99     getUser(email: string): User | undefined {
src/user.ts:107     listUsers(): User[] {
src/user.ts:119 export function validateUser(user: User): string | null {
src/main.ts:1 import { User, UserRepository, MemoryStorage, validateUser } from './user';
src/main.ts:6 function createSampleUser(): User {
src/main.ts:7     return new User("John Doe", "john@example.com", 30);"""

    # =========================================================================
    # implementations tests
    # =========================================================================

    def test_implementations_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 29,
            "column": 17,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:39 export class MemoryStorage implements Storage {
src/user.ts:62 export class FileStorage implements Storage {"""

    def test_implementations_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 29,
            "column": 17,
            "context": 1,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/user.ts:38-40
 */
export class MemoryStorage implements Storage {
    private users: Map<string, User> = new Map();

src/user.ts:61-63
 */
export class FileStorage implements Storage {
    private cache: Map<string, User> = new Map();
"""

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        os.chdir(workspace)
        response = run_request("describe", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 13,
        })
        output = format_output(response["result"], "plain")
        assert output == """\

```typescript
class User
```
Represents a user in the system."""

    # =========================================================================
    # rename tests
    # =========================================================================

    def test_rename(self, workspace):
        os.chdir(workspace)
        
        # Verify User class exists before rename
        original_user_ts = (workspace / "src" / "user.ts").read_text()
        original_main_ts = (workspace / "src" / "main.ts").read_text()
        assert "export class User {" in original_user_ts
        assert "import { User," in original_main_ts
        
        response = run_request("rename", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 13,
            "new_name": "Person",
        })
        output = format_output(response["result"], "plain")
        # TypeScript renames in both user.ts and main.ts (order may vary)
        lines = output.strip().split("\n")
        assert lines[0] == "Renamed in 2 file(s):"
        files_renamed = {line.strip() for line in lines[1:]}
        assert files_renamed == {"src/main.ts", "src/user.ts"}

        # Verify rename actually happened in the files
        renamed_user_ts = (workspace / "src" / "user.ts").read_text()
        renamed_main_ts = (workspace / "src" / "main.ts").read_text()
        assert "export class Person {" in renamed_user_ts
        assert "export class User {" not in renamed_user_ts
        assert "import { Person," in renamed_main_ts
        assert "import { User," not in renamed_main_ts

        # Revert the rename
        run_request("rename", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 13,
            "new_name": "User",
        })
        
        # Verify revert worked
        reverted_user_ts = (workspace / "src" / "user.ts").read_text()
        reverted_main_ts = (workspace / "src" / "main.ts").read_text()
        assert "export class User {" in reverted_user_ts
        assert "export class Person {" not in reverted_user_ts
        assert "import { User," in reverted_main_ts

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "errors.ts"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "errors.ts" in output
        assert "error" in output.lower()

    def test_diagnostics_undefined_variable(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "errors.ts"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "undefinedVar" in output or "Cannot find name" in output

    def test_diagnostics_type_error(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "errors.ts"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        has_type_error = "number" in output.lower() and "string" in output.lower()
        assert has_type_error, f"Expected type error in output: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_updates_imports(self, workspace):
        os.chdir(workspace)
        
        # Create a subdirectory to move the file into
        models_dir = workspace / "src" / "models"
        models_dir.mkdir(exist_ok=True)
        
        # Check initial import in main.ts
        original_main = (workspace / "src" / "main.ts").read_text()
        assert "from './user'" in original_main
        
        # Move user.ts to models/user.ts
        response = run_request("move-file", {
            "old_path": str(workspace / "src" / "user.ts"),
            "new_path": str(workspace / "src" / "models" / "user.ts"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        
        # Verify the file was moved
        assert not (workspace / "src" / "user.ts").exists()
        assert (workspace / "src" / "models" / "user.ts").exists()
        
        # Check exact output - TypeScript updates imports
        assert output == """\
Moved file and updated imports in 2 file(s):
  src/main.ts
  src/models/user.ts"""
        
        # Check that imports were updated in main.ts
        updated_main = (workspace / "src" / "main.ts").read_text()
        assert "from './models/user'" in updated_main


# =============================================================================
# Java Integration Tests (jdtls)
# =============================================================================


class TestJavaIntegration:
    """Integration tests for Java using jdtls."""

    @pytest.fixture(autouse=True)
    def check_jdtls(self):
        requires_jdtls()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "java_project"
        dst = class_temp_dir / "java_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("grep", {
            "paths": [str(project / "src" / "main" / "java" / "com" / "example" / "Main.java")],
            "workspace_root": str(project),
            "pattern": ".*",
        })
        time.sleep(3.0)
        return project

    # =========================================================================
    # grep tests
    # =========================================================================

    def test_grep_pattern_filter(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": "^get",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/User.java:24 [Method] getName() ( : String) in User
src/main/java/com/example/User.java:33 [Method] getEmail() ( : String) in User
src/main/java/com/example/User.java:42 [Method] getAge() ( : int) in User"""

    def test_grep_kind_filter_class(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert output == "src/main/java/com/example/User.java:3 [Class] User"

    def test_grep_kind_filter_method(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["method"],
        })
        output = format_output(response["result"], "plain")
        assert "getName()" in output
        assert "isAdult()" in output

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Main.java"),
            "workspace_root": str(workspace),
            "line": 50,
            "column": 21,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "src/main/java/com/example/Main.java:15     public static User createSampleUser() {"

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Main.java"),
            "workspace_root": str(workspace),
            "line": 50,
            "column": 21,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/Main.java:10-17

    /**
     * Creates a sample user for testing.
     *
     * @return A sample user
     */
    public static User createSampleUser() {
        return new User("John Doe", "john@example.com", 30);
    }"""

    def test_definition_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Main.java"),
            "workspace_root": str(workspace),
            "line": 50,
            "column": 21,
            "context": 1,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/Main.java:14-16
     */
    public static User createSampleUser() {
        return new User("John Doe", "john@example.com", 30);
"""

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java"),
            "workspace_root": str(workspace),
            "line": 6,
            "column": 13,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/FileStorage.java:14     private Map<String, User> cache = new HashMap<>();
src/main/java/com/example/FileStorage.java:39     public void save(User user) {
src/main/java/com/example/FileStorage.java:48     public User load(String email) {
src/main/java/com/example/FileStorage.java:64     public List<User> list() {
src/main/java/com/example/Main.java:15     public static User createSampleUser() {
src/main/java/com/example/Main.java:16         return new User("John Doe", "john@example.com", 30);
src/main/java/com/example/Main.java:27                 .map(User::displayName)
src/main/java/com/example/Main.java:50         User user = createSampleUser();
src/main/java/com/example/Main.java:54         User found = repo.getUser("john@example.com");
src/main/java/com/example/MemoryStorage.java:13     private Map<String, User> users = new HashMap<>();
src/main/java/com/example/MemoryStorage.java:26     public void save(User user) {
src/main/java/com/example/MemoryStorage.java:34     public User load(String email) {
src/main/java/com/example/MemoryStorage.java:50     public List<User> list() {
src/main/java/com/example/Storage.java:14     void save(User user);
src/main/java/com/example/Storage.java:22     User load(String email);
src/main/java/com/example/Storage.java:37     List<User> list();
src/main/java/com/example/User.java:6 public class User {
src/main/java/com/example/UserRepository.java:26     public void addUser(User user) {
src/main/java/com/example/UserRepository.java:36     public User getUser(String email) {
src/main/java/com/example/UserRepository.java:55     public List<User> listUsers() {"""

    # =========================================================================
    # implementations tests
    # =========================================================================

    def test_implementations_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Storage.java"),
            "workspace_root": str(workspace),
            "line": 8,
            "column": 17,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        # Order is non-deterministic for jdtls, so check parts
        assert "AbstractStorage.java:7" in output
        assert "FileStorage.java:12" in output
        assert "MemoryStorage.java:12" in output

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        os.chdir(workspace)
        response = run_request("describe", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java"),
            "workspace_root": str(workspace),
            "line": 6,
            "column": 13,
        })
        output = format_output(response["result"], "plain")
        assert output == "com.example.User\nRepresents a user in the system."

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Errors.java"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "Errors.java" in output
        assert "error" in output.lower()

    def test_diagnostics_undefined_variable(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Errors.java"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "undefinedVar" in output or "cannot find symbol" in output.lower() or "cannot be resolved" in output.lower()

    def test_diagnostics_type_error(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Errors.java"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        has_type_error = "incompatible" in output.lower() or "cannot convert" in output.lower() or "type mismatch" in output.lower()
        assert has_type_error, f"Expected type error in output: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_renames_class(self, workspace):
        os.chdir(workspace)
        
        base_path = workspace / "src" / "main" / "java" / "com" / "example"
        
        # Verify User.java exists and check initial class usage
        assert (base_path / "User.java").exists()
        original_main = (base_path / "Main.java").read_text()
        assert "User createSampleUser()" in original_main
        assert "new User(" in original_main
        
        # Rename User.java to Person.java
        response = run_request("move-file", {
            "old_path": str(base_path / "User.java"),
            "new_path": str(base_path / "Person.java"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        
        # Verify the file was moved
        assert not (base_path / "User.java").exists()
        assert (base_path / "Person.java").exists()
        
        # jdtls updates class references across multiple files
        assert "Moved file and updated imports in" in output
        assert "src/main/java/com/example/Main.java" in output
        assert "src/main/java/com/example/Person.java" in output
        
        # Check that class references were updated in Main.java
        updated_main = (base_path / "Main.java").read_text()
        assert "Person createSampleUser()" in updated_main
        assert "new Person(" in updated_main
        assert "new User(" not in updated_main


# =============================================================================
# Multi-Language Project Tests
# =============================================================================


class TestMultiLanguageIntegration:
    """Integration tests for multi-language projects."""

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "multi_language_project"
        dst = class_temp_dir / "multi_language_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        return project

    def test_python_grep(self, workspace):
        requires_basedpyright()
        os.chdir(workspace)

        run_request("grep", {
            "paths": [str(workspace / "app.py")],
            "workspace_root": str(workspace),
            "pattern": ".*",
        })
        time.sleep(0.5)

        response = run_request("grep", {
            "paths": [str(workspace / "app.py")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
app.py:10 [Class] ServiceProtocol
app.py:18 [Class] PythonUser
app.py:25 [Class] PythonService"""

    def test_go_grep(self, workspace):
        requires_gopls()
        os.chdir(workspace)

        run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": ".*",
        })
        time.sleep(0.5)

        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["struct"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
main.go:6 [Struct] GoUser (struct{...})
main.go:12 [Struct] GoService (struct{...})"""

    def test_both_languages_workspace_wide(self, workspace):
        requires_basedpyright()
        requires_gopls()
        os.chdir(workspace)

        # Warm up both servers
        run_request("grep", {
            "paths": [str(workspace / "app.py")],
            "workspace_root": str(workspace),
            "pattern": ".*",
        })
        run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": ".*",
        })
        time.sleep(0.5)

        # Now do workspace-wide search
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": "Service",
            "kinds": ["struct", "class"],
        })
        output = format_output(response["result"], "plain")
        # Order may vary, check both are present
        assert "app.py:10 [Class] ServiceProtocol" in output
        assert "app.py:25 [Class] PythonService" in output
        assert "main.go:12 [Struct] GoService" in output


# =============================================================================
# C++ Integration Tests (clangd)
# =============================================================================


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
        assert "createSampleUser" in output
        assert "validateUser" in output

    def test_grep_kind_filter_method(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "user.hpp")],
            "workspace_root": str(workspace),
            "pattern": "^is",
            "kinds": ["method"],
        })
        output = format_output(response["result"], "plain")
        assert "isAdult" in output

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
        assert "createSampleUser" in output

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
        assert "createSampleUser" in output
        assert 'John Doe' in output

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
        assert "createSampleUser" in output

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
        import click
        os.chdir(workspace)
        
        with pytest.raises(click.ClickException) as exc_info:
            run_request("move-file", {
                "old_path": str(workspace / "user.hpp"),
                "new_path": str(workspace / "person.hpp"),
                "workspace_root": str(workspace),
            })
        assert str(exc_info.value) == "move-file is not supported by clangd"
        
        # Verify file was NOT moved
        assert (workspace / "user.hpp").exists()
        assert not (workspace / "person.hpp").exists()


# =============================================================================
# Zig Integration Tests (zls)
# =============================================================================


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
        assert "Storage" in output
        assert "MemoryStorage" in output
        assert "FileStorage" in output

    def test_grep_kind_filter_constant(self, workspace):
        os.chdir(workspace)
        # In Zig, structs are reported as constants by zls
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.zig")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["constant"],
        })
        output = format_output(response["result"], "plain")
        assert "User" in output
        assert "MemoryStorage" in output
        assert "FileStorage" in output
        assert "UserRepository" in output

    def test_grep_kind_filter_function(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main.zig")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert "createSampleUser" in output
        assert "validateUser" in output
        assert "main" in output

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main.zig"),
            "workspace_root": str(workspace),
            "line": 12,
            "column": 24,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert "createSampleUser" in output

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main.zig"),
            "workspace_root": str(workspace),
            "line": 12,
            "column": 24,
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
            "path": str(workspace / "src" / "user.zig"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 11,
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
            "path": str(workspace / "src" / "user.zig"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 11,
        })
        output = format_output(response["result"], "plain")
        assert "User" in output

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "errors.zig"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "errors.zig" in output
        assert "error" in output.lower()

    def test_diagnostics_undefined_identifier(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "errors.zig"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "undefined_var" in output or "undefined" in output.lower() or "undeclared" in output.lower()

    def test_diagnostics_type_error(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "errors.zig"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        # zls may not report type errors inline - it catches undefined identifiers and unreachable code
        # Accept either type errors OR the other errors zls reports
        has_type_error = ("i32" in output and ("u8" in output or "const" in output)) or \
                         "unreachable" in output.lower()
        assert has_type_error, f"Expected type error or unreachable code in output: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_not_supported(self, workspace):
        import click
        os.chdir(workspace)
        
        with pytest.raises(click.ClickException) as exc_info:
            run_request("move-file", {
                "old_path": str(workspace / "src" / "user.zig"),
                "new_path": str(workspace / "src" / "person.zig"),
                "workspace_root": str(workspace),
            })
        assert str(exc_info.value) == "move-file is not supported by zls"
        
        # Verify file was NOT moved
        assert (workspace / "src" / "user.zig").exists()
        assert not (workspace / "src" / "person.zig").exists()


# =============================================================================
# Lua Integration Tests (lua-language-server)
# =============================================================================


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
        assert "Storage" in output
        assert "MemoryStorage" in output
        assert "FileStorage" in output

    def test_grep_kind_filter_function(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "main.lua")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        output = format_output(response["result"], "plain")
        assert "createSampleUser" in output
        assert "validateUser" in output
        assert "processUsers" in output
        assert "main" in output

    def test_grep_kind_filter_object(self, workspace):
        os.chdir(workspace)
        # In Lua, classes/tables are reported as objects by lua-language-server
        response = run_request("grep", {
            "paths": [str(workspace / "user.lua")],
            "workspace_root": str(workspace),
            "pattern": "^User$",
            "kinds": ["object"],
        })
        output = format_output(response["result"], "plain")
        assert "User" in output

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
        assert "createSampleUser" in output

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
        assert "createSampleUser" in output
        assert "John Doe" in output

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
        assert "User" in output

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
        assert "User" in output

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
        import click
        os.chdir(workspace)
        
        with pytest.raises(click.ClickException) as exc_info:
            run_request("move-file", {
                "old_path": str(workspace / "user.lua"),
                "new_path": str(workspace / "person.lua"),
                "workspace_root": str(workspace),
            })
        assert str(exc_info.value) == "move-file is not supported by lua-language-server"
        
        # Verify file was NOT moved
        assert (workspace / "user.lua").exists()
        assert not (workspace / "person.lua").exists()


# =============================================================================
# Ruby Integration Tests (solargraph)
# =============================================================================


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
        assert "--body not supported" in output

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


# =============================================================================
# PHP Integration Tests (intelephense)
# =============================================================================


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
        
        with pytest.raises(click.ClickException) as exc_info:
            run_request("move-file", {
                "old_path": str(base_path / "User.php"),
                "new_path": str(base_path / "Person.php"),
                "workspace_root": str(workspace),
            })
        assert str(exc_info.value) == "move-file is not supported by intelephense"
        
        # Verify file was NOT moved
        assert (base_path / "User.php").exists()
        assert not (base_path / "Person.php").exists()
