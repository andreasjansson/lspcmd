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
    requires_pyright,
    requires_rust_analyzer,
    requires_gopls,
    requires_typescript_lsp,
    requires_jdtls,
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
    """Integration tests for Python using pyright."""

    @pytest.fixture(autouse=True)
    def check_pyright(self):
        requires_pyright()

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
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": ".*",
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert "User" in names
        assert "MemoryStorage" in names
        assert "create_sample_user" in names

    def test_grep_pattern_filter(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": "^User",
            "case_sensitive": True,
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert names == ["User", "UserRepository"]

    def test_grep_kind_filter(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
        })
        symbols = response["result"]
        
        assert all(s["kind"] == "Class" for s in symbols)
        names = [s["name"] for s in symbols]
        assert "User" in names
        assert "MemoryStorage" in names
        assert "create_sample_user" not in names

    def test_grep_function_kind(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        symbols = response["result"]
        
        assert all(s["kind"] == "Function" for s in symbols)
        names = [s["name"] for s in symbols]
        assert "create_sample_user" in names
        assert "process_users" in names
        assert "main" in names
        assert "User" not in names

    def test_grep_case_sensitive(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": "user",
            "case_sensitive": False,
        })
        insensitive_symbols = response["result"]
        
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": "user",
            "case_sensitive": True,
        })
        sensitive_symbols = response["result"]
        
        # Case insensitive should find more (User, add_user, get_user, etc.)
        assert len(insensitive_symbols) > len(sensitive_symbols)
        
        # Case sensitive "user" should not match "User"
        sensitive_names = [s["name"] for s in sensitive_symbols]
        assert "User" not in sensitive_names
        assert "add_user" in sensitive_names

    def test_grep_combined_filters(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["class"],
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert set(names) == {"StorageProtocol", "MemoryStorage", "FileStorage"}

    def test_grep_multiple_files(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.py"), str(workspace / "utils.py")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        symbols = response["result"]
        
        # Should have functions from both files
        paths = set(s["path"] for s in symbols)
        assert "main.py" in paths
        assert "utils.py" in paths

    def test_grep_workspace_wide(self, workspace):
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": "validate",
            "kinds": ["function"],
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        # Should find validate functions across all files
        assert "validate_email" in names
        assert "validate_age" in names

    def test_grep_exclude_pattern(self, workspace):
        # First get all symbols
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
        })
        all_symbols = response["result"]
        
        # Now exclude utils.py
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["function"],
            "exclude_patterns": ["utils.py"],
        })
        filtered_symbols = response["result"]
        
        # Should have fewer symbols after excluding utils.py
        assert len(filtered_symbols) < len(all_symbols)
        
        # None should be from utils.py
        assert all(s["path"] != "utils.py" for s in filtered_symbols)

    def test_grep_with_docs(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.py")],
            "workspace_root": str(workspace),
            "pattern": "^User$",
            "kinds": ["class"],
            "include_docs": True,
        })
        symbols = response["result"]
        
        assert len(symbols) == 1
        assert symbols[0]["name"] == "User"
        assert "documentation" in symbols[0]
        assert symbols[0]["documentation"] is not None
        assert "user" in symbols[0]["documentation"].lower()

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 128,
            "column": 11,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")

        assert output == "main.py:111 def create_sample_user() -> User:"

    def test_definition_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 128,
            "column": 11,
            "context": 2,
            "body": False,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.py:109-113


def create_sample_user() -> User:
    \"\"\"Create a sample user for testing.\"\"\"
    return User(name="John Doe", email="john@example.com", age=30)
"""

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 128,
            "column": 11,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.py:111-113

def create_sample_user() -> User:
    \"\"\"Create a sample user for testing.\"\"\"
    return User(name="John Doe", email="john@example.com", age=30)"""

    def test_definition_with_body_and_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 128,
            "column": 11,
            "context": 2,
            "body": True,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.py:109-115



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
            "line": 25,
            "column": 6,
            "context": 0,
        })
        result = response["result"]
        
        assert len(result) == 7
        paths = [r["path"] for r in result]
        assert all(p == "main.py" for p in paths)

    def test_references_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 6,
            "context": 1,
        })
        result = response["result"]
        assert len(result) == 7
        assert all("context_lines" in r for r in result)
        assert result[0]["context_start"] == 24

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        response = run_request("describe", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 6,
        })
        result = response["result"]
        
        assert result["contents"] is not None
        assert "User" in result["contents"]

    # =========================================================================
    # rename tests
    # =========================================================================

    def test_rename(self, workspace):
        response = run_request("rename", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 6,
            "new_name": "Person",
        })
        result = response["result"]
        
        assert result["renamed"] == True
        assert "main.py" in result["files_modified"]

        # Revert the rename
        run_request("rename", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 6,
            "new_name": "User",
        })

    # =========================================================================
    # declaration tests
    # =========================================================================

    def test_declaration_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("declaration", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 6,
            "context": 0,
        })
        result = response["result"]
        assert len(result) >= 1
        assert "main.py" in result[0]["path"]

    # =========================================================================
    # implementations tests (not supported by pyright)
    # =========================================================================

    def test_implementations_not_supported(self, workspace):
        import click
        os.chdir(workspace)
        with pytest.raises(click.ClickException) as exc_info:
            run_request("implementations", {
                "path": str(workspace / "main.py"),
                "workspace_root": str(workspace),
                "line": 12,
                "column": 6,
                "context": 0,
            })
        assert "textDocument/implementation" in str(exc_info.value)

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
                "line": 12,
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
                "line": 46,
                "column": 6,
                "context": 0,
            })
        assert "prepareTypeHierarchy" in str(exc_info.value)


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

    def test_grep_single_file(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": ".*",
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert "User" in names
        assert "Storage" in names
        assert "NewUser" in names

    def test_grep_pattern_filter(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": "^New",
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert all(n.startswith("New") for n in names)
        assert "NewUser" in names
        assert "NewMemoryStorage" in names

    def test_grep_kind_filter_struct(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["struct"],
        })
        symbols = response["result"]
        
        assert all(s["kind"] == "Struct" for s in symbols)
        names = [s["name"] for s in symbols]
        assert "User" in names
        assert "MemoryStorage" in names

    def test_grep_kind_filter_interface(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["interface"],
        })
        symbols = response["result"]
        
        assert all(s["kind"] == "Interface" for s in symbols)
        names = [s["name"] for s in symbols]
        assert "Storage" in names
        assert "Validator" in names

    def test_grep_multiple_kinds(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["struct", "interface"],
        })
        symbols = response["result"]
        
        kinds = set(s["kind"] for s in symbols)
        assert kinds == {"Struct", "Interface"}

    def test_grep_with_docs(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "main.go")],
            "workspace_root": str(workspace),
            "pattern": "^User$",
            "kinds": ["struct"],
            "include_docs": True,
        })
        symbols = response["result"]
        
        assert len(symbols) == 1
        assert symbols[0]["name"] == "User"
        assert "documentation" in symbols[0]
        # Go hover docs include type info
        assert symbols[0]["documentation"] is not None

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
        result = response["result"]
        
        assert len(result) == 22

    def test_references_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "context": 1,
        })
        result = response["result"]
        assert len(result) == 22
        assert all("context_lines" in r for r in result)

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
        result = response["result"]
        
        assert len(result) == 2
        names = [r["path"] for r in result]
        assert all("main.go" in n for n in names)

    def test_implementations_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 31,
            "column": 5,
            "context": 1,
        })
        result = response["result"]
        assert len(result) == 2
        assert all("context_lines" in r for r in result)

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        response = run_request("describe", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
        })
        result = response["result"]
        
        assert result["contents"] is not None
        assert "User" in result["contents"]

    # =========================================================================
    # rename tests
    # =========================================================================

    def test_rename(self, workspace):
        response = run_request("rename", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "new_name": "Person",
        })
        result = response["result"]
        
        assert result["renamed"] == True

        # Revert the rename
        run_request("rename", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "new_name": "User",
        })

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
        for f in ["main.rs", "user.rs", "storage.rs"]:
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

    def test_grep_single_file(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.rs")],
            "workspace_root": str(workspace),
            "pattern": ".*",
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert "User" in names
        assert "UserRepository" in names

    def test_grep_pattern_filter(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "storage.rs")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert "Storage" in names
        assert "MemoryStorage" in names
        assert "FileStorage" in names

    def test_grep_kind_filter(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.rs")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["struct"],
        })
        symbols = response["result"]
        
        assert all(s["kind"] == "Struct" for s in symbols)
        names = [s["name"] for s in symbols]
        assert "User" in names
        assert "UserRepository" in names

    def test_grep_interface_kind(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "storage.rs")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["interface"],
        })
        symbols = response["result"]
        
        # Rust traits show as Interface
        assert len(symbols) == 1
        assert symbols[0]["name"] == "Storage"

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry("definition", {
            "path": str(workspace / "src" / "main.rs"),
            "workspace_root": str(workspace),
            "line": 23,
            "column": 16,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")

        assert output == "src/main.rs:8 fn create_sample_user() -> User {"

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry("definition", {
            "path": str(workspace / "src" / "main.rs"),
            "workspace_root": str(workspace),
            "line": 23,
            "column": 16,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
src/main.rs:7-10

/// Creates a sample user for testing.
fn create_sample_user() -> User {
    User::new("John Doe".to_string(), "john@example.com".to_string(), 30)
}"""

    def test_definition_with_body_and_context(self, workspace):
        os.chdir(workspace)
        response = self._run_request_with_retry("definition", {
            "path": str(workspace / "src" / "main.rs"),
            "workspace_root": str(workspace),
            "line": 23,
            "column": 16,
            "context": 1,
            "body": True,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
src/main.rs:6-11


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
            "line": 8,
            "column": 3,
            "context": 0,
        })
        result = response["result"]
        
        assert len(result) == 2


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

    def test_grep_single_file(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": ".*",
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert "User" in names
        assert "Storage" in names
        assert "MemoryStorage" in names

    def test_grep_pattern_filter(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": "Storage",
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert "Storage" in names
        assert "MemoryStorage" in names
        assert "FileStorage" in names

    def test_grep_kind_filter_class(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
        })
        symbols = response["result"]
        
        assert all(s["kind"] == "Class" for s in symbols)
        names = [s["name"] for s in symbols]
        assert "User" in names
        assert "MemoryStorage" in names
        assert "FileStorage" in names
        assert "UserRepository" in names

    def test_grep_kind_filter_interface(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["interface"],
        })
        symbols = response["result"]
        
        assert all(s["kind"] == "Interface" for s in symbols)
        assert len(symbols) == 1
        assert symbols[0]["name"] == "Storage"

    def test_grep_with_docs(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "user.ts")],
            "workspace_root": str(workspace),
            "pattern": "^User$",
            "kinds": ["class"],
            "include_docs": True,
        })
        symbols = response["result"]
        
        assert len(symbols) == 1
        assert symbols[0]["name"] == "User"
        assert "documentation" in symbols[0]
        assert symbols[0]["documentation"] is not None

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
        result = response["result"]
        
        assert len(result) == 19  # Many references across files

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
        result = response["result"]
        
        assert len(result) == 2

    def test_implementations_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 29,
            "column": 17,
            "context": 1,
        })
        result = response["result"]
        assert len(result) == 2
        assert all("context_lines" in r for r in result)

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        response = run_request("describe", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 13,
        })
        result = response["result"]
        
        assert result["contents"] is not None
        assert "User" in result["contents"]

    # =========================================================================
    # rename tests
    # =========================================================================

    def test_rename(self, workspace):
        response = run_request("rename", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 13,
            "new_name": "Person",
        })
        result = response["result"]
        
        assert result["renamed"] == True
        assert len(result["files_modified"]) == 2


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

    def test_grep_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": ".*",
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert "User" in names
        assert "getName()" in names

    def test_grep_pattern_filter(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": "^get",
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert "getName()" in names
        assert "getEmail()" in names
        assert "getAge()" in names

    def test_grep_kind_filter_class(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
        })
        symbols = response["result"]
        
        assert all(s["kind"] == "Class" for s in symbols)
        assert len(symbols) == 1
        assert symbols[0]["name"] == "User"

    def test_grep_kind_filter_method(self, workspace):
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["method"],
        })
        symbols = response["result"]
        
        assert all(s["kind"] == "Method" for s in symbols)
        names = [s["name"] for s in symbols]
        assert "getName()" in names
        assert "isAdult()" in names

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

        assert "createSampleUser" in output

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
        result = response["result"]
        
        assert "createSampleUser" in result["content"]
        assert result["start_line"] < result["end_line"]

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
        result = response["result"]
        
        assert len(result) >= 1
        assert "context_lines" in result[0]

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
        result = response["result"]
        
        assert len(result) == 20

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
        result = response["result"]
        
        assert len(result) == 3

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        response = run_request("describe", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java"),
            "workspace_root": str(workspace),
            "line": 6,
            "column": 13,
        })
        result = response["result"]
        
        assert result["contents"] is not None
        assert "User" in result["contents"]


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
        requires_pyright()

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
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert "PythonUser" in names
        assert "PythonService" in names

    def test_go_grep(self, workspace):
        requires_gopls()

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
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        assert "GoUser" in names
        assert "GoService" in names

    def test_both_languages_workspace_wide(self, workspace):
        requires_pyright()
        requires_gopls()

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
        })
        symbols = response["result"]
        names = [s["name"] for s in symbols]
        
        # Should find services from both Python and Go
        assert "PythonService" in names
        assert "GoService" in names
