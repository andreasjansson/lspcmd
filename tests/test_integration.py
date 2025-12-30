"""Comprehensive integration tests for lspcmd.

Tests all LSP features across Python, Go, Rust, TypeScript, Java, and multi-language projects.
"""

import asyncio
import os
import shutil
from pathlib import Path

import pytest

from lspcmd.daemon.session import Session
from lspcmd.daemon.server import DaemonServer
from lspcmd.lsp.protocol import LSPResponseError, LSPMethodNotSupported
from lspcmd.utils.uri import path_to_uri
from lspcmd.utils.config import add_workspace_root

from .conftest import (
    requires_pyright,
    requires_rust_analyzer,
    requires_gopls,
    requires_typescript_lsp,
    requires_jdtls,
    FIXTURES_DIR,
)

os.environ["LSPCMD_REQUEST_TIMEOUT"] = "60"


def find_line_col(content: str, pattern: str, not_pattern: str | None = None) -> tuple[int, int]:
    """Find line and column of a pattern in content."""
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if pattern in line:
            if not_pattern and not_pattern in line:
                continue
            return i, line.index(pattern.split()[0] if " " in pattern else pattern)
    raise ValueError(f"Pattern '{pattern}' not found")


# =============================================================================
# Python Integration Tests (pyright)
# =============================================================================


class TestPythonIntegration:
    """Integration tests for Python using pyright."""

    @pytest.fixture(autouse=True)
    def check_pyright(self):
        requires_pyright()

    @pytest.fixture(scope="class")
    def class_temp_dir(self, tmp_path_factory):
        return tmp_path_factory.mktemp("python")

    @pytest.fixture(scope="class")
    def class_project(self, class_temp_dir):
        src = FIXTURES_DIR / "python_project"
        dst = class_temp_dir / "python_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def class_isolated_config(self, class_temp_dir):
        cache_dir = class_temp_dir / "cache"
        config_dir = class_temp_dir / "config"
        cache_dir.mkdir()
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

    @pytest.fixture(scope="class")
    def class_session(self, class_isolated_config):
        return Session()

    @pytest.fixture(scope="class")
    async def workspace(self, class_project, class_session):
        main_py = class_project / "main.py"
        ws = await class_session.get_or_create_workspace(main_py, class_project)
        await ws.ensure_document_open(main_py)
        await ws.client.wait_for_service_ready()
        yield ws, class_project
        await class_session.close_all()

    @pytest.mark.asyncio
    async def test_initialize_server(self, workspace):
        ws, project = workspace
        assert ws.client is not None
        assert ws.client._initialized

    @pytest.mark.asyncio
    async def test_grep_document_symbols(self, workspace):
        ws, project = workspace
        main_py = project / "main.py"

        result = await ws.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(main_py)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "User" in names
        assert "UserRepository" in names
        assert "StorageProtocol" in names

    @pytest.mark.asyncio
    async def test_find_definition(self, workspace):
        ws, project = workspace
        main_py = project / "main.py"
        content = main_py.read_text()
        line, col = find_line_col(content, "user = create_sample_user()")
        col = content.splitlines()[line].index("create_sample_user")

        result = await ws.client.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_find_references(self, workspace):
        ws, project = workspace
        main_py = project / "main.py"
        content = main_py.read_text()
        line, col = find_line_col(content, "class User:")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": line, "character": col},
                "context": {"includeDeclaration": True},
            },
        )

        assert result is not None
        assert len(result) >= 2

    @pytest.mark.asyncio
    async def test_describe_hover(self, workspace):
        ws, project = workspace
        main_py = project / "main.py"
        content = main_py.read_text()
        line, col = find_line_col(content, "class User:")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert "contents" in result

    @pytest.mark.asyncio
    async def test_diagnostics(self, workspace):
        ws, project = workspace
        main_py = project / "main.py"
        stored = ws.client.get_stored_diagnostics(path_to_uri(main_py))
        assert stored is not None or stored == []

    @pytest.mark.asyncio
    async def test_rename(self, workspace):
        ws, project = workspace
        main_py = project / "main.py"
        content = main_py.read_text()
        line, col = find_line_col(content, "class User:")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": line, "character": col},
                "newName": "Person",
            },
        )

        assert result is not None
        assert "changes" in result or "documentChanges" in result

    @pytest.mark.asyncio
    async def test_list_code_actions(self, workspace):
        ws, project = workspace
        main_py = project / "main.py"

        result = await ws.client.send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                "context": {"diagnostics": []},
            },
        )

        assert result is None or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_format(self, workspace):
        ws, project = workspace
        main_py = project / "main.py"

        try:
            result = await ws.client.send_request(
                "textDocument/formatting",
                {
                    "textDocument": {"uri": path_to_uri(main_py)},
                    "options": {"tabSize": 4, "insertSpaces": True},
                },
            )
            assert result is None or isinstance(result, list)
        except LSPResponseError:
            pass  # Pyright may not support formatting

    @pytest.mark.asyncio
    async def test_organize_imports(self, workspace):
        ws, project = workspace
        main_py = project / "main.py"

        result = await ws.client.send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                "context": {"diagnostics": [], "only": ["source.organizeImports"]},
            },
        )

        assert result is None or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_raw_lsp_request(self, workspace):
        ws, project = workspace
        main_py = project / "main.py"

        result = await ws.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(main_py)}},
        )

        assert result is not None
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_implementations_not_supported(self, workspace):
        ws, project = workspace
        main_py = project / "main.py"
        content = main_py.read_text()
        line, col = find_line_col(content, "class StorageProtocol")
        col = content.splitlines()[line].index("StorageProtocol")

        with pytest.raises(LSPResponseError) as exc_info:
            await ws.client.send_request(
                "textDocument/implementation",
                {
                    "textDocument": {"uri": path_to_uri(main_py)},
                    "position": {"line": line, "character": col},
                },
            )

        assert exc_info.value.is_method_not_found()


# =============================================================================
# Go Integration Tests (gopls)
# =============================================================================


class TestGoIntegration:
    """Integration tests for Go using gopls."""

    @pytest.fixture(autouse=True)
    def check_gopls(self):
        requires_gopls()

    @pytest.fixture(scope="class")
    def class_temp_dir(self, tmp_path_factory):
        return tmp_path_factory.mktemp("go")

    @pytest.fixture(scope="class")
    def class_project(self, class_temp_dir):
        src = FIXTURES_DIR / "go_project"
        dst = class_temp_dir / "go_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def class_isolated_config(self, class_temp_dir):
        cache_dir = class_temp_dir / "cache"
        config_dir = class_temp_dir / "config"
        cache_dir.mkdir()
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

    @pytest.fixture(scope="class")
    def class_session(self, class_isolated_config):
        return Session()

    @pytest.fixture(scope="class")
    async def workspace(self, class_project, class_session):
        main_go = class_project / "main.go"
        ws = await class_session.get_or_create_workspace(main_go, class_project)
        await ws.ensure_document_open(main_go)
        await ws.client.wait_for_service_ready()
        yield ws, class_project
        await class_session.close_all()

    @pytest.mark.asyncio
    async def test_initialize_server(self, workspace):
        ws, project = workspace
        assert ws.client is not None
        assert ws.client._initialized

    @pytest.mark.asyncio
    async def test_grep_document_symbols(self, workspace):
        ws, project = workspace
        main_go = project / "main.go"

        result = await ws.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(main_go)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "User" in names
        assert "Storage" in names
        assert "MemoryStorage" in names

    @pytest.mark.asyncio
    async def test_find_definition(self, workspace):
        ws, project = workspace
        main_go = project / "main.go"
        content = main_go.read_text()
        line, col = find_line_col(content, "user := createSampleUser()")
        col = content.splitlines()[line].index("createSampleUser")

        result = await ws.client.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_find_references(self, workspace):
        ws, project = workspace
        main_go = project / "main.go"
        content = main_go.read_text()
        line, col = find_line_col(content, "type User struct")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": line, "character": col},
                "context": {"includeDeclaration": True},
            },
        )

        assert result is not None
        assert len(result) >= 2

    @pytest.mark.asyncio
    async def test_find_implementations(self, workspace):
        ws, project = workspace
        main_go = project / "main.go"
        content = main_go.read_text()
        line, col = find_line_col(content, "type Storage interface")
        col = content.splitlines()[line].index("Storage")

        result = await ws.client.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert len(result) == 2  # MemoryStorage and FileStorage

    @pytest.mark.asyncio
    async def test_find_subtypes(self, workspace):
        ws, project = workspace
        main_go = project / "main.go"
        content = main_go.read_text()
        line, col = find_line_col(content, "type Storage interface")
        col = content.splitlines()[line].index("Storage")

        prepare_result = await ws.client.send_request(
            "textDocument/prepareTypeHierarchy",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": line, "character": col},
            },
        )

        if prepare_result:
            result = await ws.client.send_request(
                "typeHierarchy/subtypes",
                {"item": prepare_result[0]},
            )
            assert result is None or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_describe_hover(self, workspace):
        ws, project = workspace
        main_go = project / "main.go"
        content = main_go.read_text()
        line, col = find_line_col(content, "type User struct")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert "contents" in result

    @pytest.mark.asyncio
    async def test_diagnostics(self, workspace):
        ws, project = workspace
        main_go = project / "main.go"

        if ws.client.supports_pull_diagnostics:
            try:
                result = await ws.client.send_request(
                    "textDocument/diagnostic",
                    {"textDocument": {"uri": path_to_uri(main_go)}},
                )
                assert result is None or "items" in result
            except LSPResponseError:
                pass

    @pytest.mark.asyncio
    async def test_rename(self, workspace):
        ws, project = workspace
        main_go = project / "main.go"
        content = main_go.read_text()
        line, col = find_line_col(content, "type User struct")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": line, "character": col},
                "newName": "Person",
            },
        )

        assert result is not None
        assert "changes" in result or "documentChanges" in result

    @pytest.mark.asyncio
    async def test_format(self, workspace):
        ws, project = workspace
        main_go = project / "main.go"

        result = await ws.client.send_request(
            "textDocument/formatting",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "options": {"tabSize": 4, "insertSpaces": False},
            },
        )

        assert result is None or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_organize_imports(self, workspace):
        ws, project = workspace
        main_go = project / "main.go"

        result = await ws.client.send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                "context": {"diagnostics": [], "only": ["source.organizeImports"]},
            },
        )

        assert result is None or isinstance(result, list)


# =============================================================================
# Rust Integration Tests (rust-analyzer)
# =============================================================================


class TestRustIntegration:
    """Integration tests for Rust using rust-analyzer."""

    @pytest.fixture(autouse=True)
    def check_rust_analyzer(self):
        requires_rust_analyzer()

    @pytest.fixture(scope="class")
    def class_temp_dir(self, tmp_path_factory):
        return tmp_path_factory.mktemp("rust")

    @pytest.fixture(scope="class")
    def class_project(self, class_temp_dir):
        src = FIXTURES_DIR / "rust_project"
        dst = class_temp_dir / "rust_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def class_isolated_config(self, class_temp_dir):
        cache_dir = class_temp_dir / "cache"
        config_dir = class_temp_dir / "config"
        cache_dir.mkdir()
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

    @pytest.fixture(scope="class")
    def class_session(self, class_isolated_config):
        return Session()

    @pytest.fixture(scope="class")
    async def workspace(self, class_project, class_session):
        main_rs = class_project / "src" / "main.rs"
        ws = await class_session.get_or_create_workspace(main_rs, class_project)
        await ws.ensure_document_open(main_rs)
        await ws.client.wait_for_service_ready()
        # rust-analyzer needs a bit more time to index
        await asyncio.sleep(2.0)
        yield ws, class_project
        await class_session.close_all()

    @pytest.mark.asyncio
    async def test_initialize_server(self, workspace):
        ws, project = workspace
        assert ws.client is not None
        assert ws.client._initialized

    @pytest.mark.asyncio
    async def test_grep_document_symbols(self, workspace):
        ws, project = workspace
        user_rs = project / "src" / "user.rs"
        await ws.ensure_document_open(user_rs)

        result = await ws.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(user_rs)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "User" in names
        assert "UserRepository" in names

    @pytest.mark.asyncio
    async def test_find_definition(self, workspace):
        ws, project = workspace
        main_rs = project / "src" / "main.rs"
        content = main_rs.read_text()
        line, col = find_line_col(content, "create_sample_user()", not_pattern="fn ")
        col = content.splitlines()[line].index("create_sample_user")

        # rust-analyzer may need retries due to "content modified" during indexing
        for attempt in range(3):
            try:
                result = await ws.client.send_request(
                    "textDocument/definition",
                    {
                        "textDocument": {"uri": path_to_uri(main_rs)},
                        "position": {"line": line, "character": col},
                    },
                )
                break
            except LSPResponseError as e:
                if "content modified" in str(e) and attempt < 2:
                    await asyncio.sleep(1.0)
                    continue
                raise

        assert result is not None

    @pytest.mark.asyncio
    async def test_find_references(self, workspace):
        ws, project = workspace
        user_rs = project / "src" / "user.rs"
        await ws.ensure_document_open(user_rs)
        content = user_rs.read_text()
        line, col = find_line_col(content, "pub struct User")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(user_rs)},
                "position": {"line": line, "character": col},
                "context": {"includeDeclaration": True},
            },
        )

        assert result is not None
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_find_implementations(self, workspace):
        ws, project = workspace
        storage_rs = project / "src" / "storage.rs"
        await ws.ensure_document_open(storage_rs)
        content = storage_rs.read_text()
        line, col = find_line_col(content, "pub trait Storage")
        col = content.splitlines()[line].index("Storage")

        result = await ws.client.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": path_to_uri(storage_rs)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert len(result) >= 2  # MemoryStorage and FileStorage impl blocks

    @pytest.mark.asyncio
    async def test_describe_hover(self, workspace):
        ws, project = workspace
        user_rs = project / "src" / "user.rs"
        await ws.ensure_document_open(user_rs)
        content = user_rs.read_text()
        line, col = find_line_col(content, "pub struct User")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(user_rs)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert "contents" in result

    @pytest.mark.asyncio
    async def test_rename(self, workspace):
        ws, project = workspace
        user_rs = project / "src" / "user.rs"
        await ws.ensure_document_open(user_rs)
        content = user_rs.read_text()
        line, col = find_line_col(content, "pub struct User")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(user_rs)},
                "position": {"line": line, "character": col},
                "newName": "Person",
            },
        )

        assert result is not None
        assert "changes" in result or "documentChanges" in result

    @pytest.mark.asyncio
    async def test_format(self, workspace):
        ws, project = workspace
        main_rs = project / "src" / "main.rs"

        result = await ws.client.send_request(
            "textDocument/formatting",
            {
                "textDocument": {"uri": path_to_uri(main_rs)},
                "options": {"tabSize": 4, "insertSpaces": True},
            },
        )

        assert result is None or isinstance(result, list)


# =============================================================================
# TypeScript Integration Tests (typescript-language-server)
# =============================================================================


class TestTypeScriptIntegration:
    """Integration tests for TypeScript using typescript-language-server."""

    @pytest.fixture(autouse=True)
    def check_typescript_lsp(self):
        requires_typescript_lsp()

    @pytest.fixture(scope="class")
    def class_temp_dir(self, tmp_path_factory):
        return tmp_path_factory.mktemp("typescript")

    @pytest.fixture(scope="class")
    def class_project(self, class_temp_dir):
        src = FIXTURES_DIR / "typescript_project"
        dst = class_temp_dir / "typescript_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def class_isolated_config(self, class_temp_dir):
        cache_dir = class_temp_dir / "cache"
        config_dir = class_temp_dir / "config"
        cache_dir.mkdir()
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

    @pytest.fixture(scope="class")
    def class_session(self, class_isolated_config):
        return Session()

    @pytest.fixture(scope="class")
    async def workspace(self, class_project, class_session):
        main_ts = class_project / "src" / "main.ts"
        ws = await class_session.get_or_create_workspace(main_ts, class_project)
        await ws.ensure_document_open(main_ts)
        await ws.client.wait_for_service_ready()
        yield ws, class_project
        await class_session.close_all()

    @pytest.mark.asyncio
    async def test_initialize_server(self, workspace):
        ws, project = workspace
        assert ws.client is not None
        assert ws.client._initialized

    @pytest.mark.asyncio
    async def test_grep_document_symbols(self, workspace):
        ws, project = workspace
        user_ts = project / "src" / "user.ts"
        await ws.ensure_document_open(user_ts)

        result = await ws.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(user_ts)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "User" in names
        assert "Storage" in names
        assert "MemoryStorage" in names

    @pytest.mark.asyncio
    async def test_find_definition(self, workspace):
        ws, project = workspace
        main_ts = project / "src" / "main.ts"
        content = main_ts.read_text()
        line, col = find_line_col(content, "createSampleUser()", not_pattern="function")
        col = content.splitlines()[line].index("createSampleUser")

        result = await ws.client.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(main_ts)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_find_references(self, workspace):
        ws, project = workspace
        user_ts = project / "src" / "user.ts"
        await ws.ensure_document_open(user_ts)
        content = user_ts.read_text()
        line, col = find_line_col(content, "export class User")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(user_ts)},
                "position": {"line": line, "character": col},
                "context": {"includeDeclaration": True},
            },
        )

        assert result is not None
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_find_implementations(self, workspace):
        ws, project = workspace
        user_ts = project / "src" / "user.ts"
        await ws.ensure_document_open(user_ts)
        content = user_ts.read_text()
        line, col = find_line_col(content, "export interface Storage")
        col = content.splitlines()[line].index("Storage")

        result = await ws.client.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": path_to_uri(user_ts)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert len(result) >= 2  # MemoryStorage and FileStorage

    @pytest.mark.asyncio
    async def test_describe_hover(self, workspace):
        ws, project = workspace
        user_ts = project / "src" / "user.ts"
        await ws.ensure_document_open(user_ts)
        content = user_ts.read_text()
        line, col = find_line_col(content, "export class User")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(user_ts)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert "contents" in result

    @pytest.mark.asyncio
    async def test_rename(self, workspace):
        ws, project = workspace
        user_ts = project / "src" / "user.ts"
        await ws.ensure_document_open(user_ts)
        content = user_ts.read_text()
        line, col = find_line_col(content, "export class User")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(user_ts)},
                "position": {"line": line, "character": col},
                "newName": "Person",
            },
        )

        assert result is not None
        assert "changes" in result or "documentChanges" in result

    @pytest.mark.asyncio
    async def test_format(self, workspace):
        ws, project = workspace
        main_ts = project / "src" / "main.ts"

        result = await ws.client.send_request(
            "textDocument/formatting",
            {
                "textDocument": {"uri": path_to_uri(main_ts)},
                "options": {"tabSize": 2, "insertSpaces": True},
            },
        )

        assert result is None or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_organize_imports(self, workspace):
        ws, project = workspace
        main_ts = project / "src" / "main.ts"

        result = await ws.client.send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": path_to_uri(main_ts)},
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                "context": {"diagnostics": [], "only": ["source.organizeImports"]},
            },
        )

        assert result is None or isinstance(result, list)


# =============================================================================
# Java Integration Tests (jdtls)
# =============================================================================


class TestJavaIntegration:
    """Integration tests for Java using jdtls."""

    @pytest.fixture(autouse=True)
    def check_jdtls(self):
        requires_jdtls()

    @pytest.fixture(scope="class")
    def class_temp_dir(self, tmp_path_factory):
        return tmp_path_factory.mktemp("java")

    @pytest.fixture(scope="class")
    def class_project(self, class_temp_dir):
        src = FIXTURES_DIR / "java_project"
        dst = class_temp_dir / "java_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def class_isolated_config(self, class_temp_dir):
        cache_dir = class_temp_dir / "cache"
        config_dir = class_temp_dir / "config"
        cache_dir.mkdir()
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

    @pytest.fixture(scope="class")
    def class_session(self, class_isolated_config):
        return Session()

    @pytest.fixture(scope="class")
    async def workspace(self, class_project, class_session):
        main_java = class_project / "src" / "main" / "java" / "com" / "example" / "Main.java"
        ws = await class_session.get_or_create_workspace(main_java, class_project)
        await ws.ensure_document_open(main_java)
        await ws.client.wait_for_service_ready()
        # jdtls needs more time to fully index
        await asyncio.sleep(3.0)
        yield ws, class_project
        await class_session.close_all()

    @pytest.mark.asyncio
    async def test_initialize_server(self, workspace):
        ws, project = workspace
        assert ws.client is not None
        assert ws.client._initialized

    @pytest.mark.asyncio
    async def test_grep_document_symbols(self, workspace):
        ws, project = workspace
        user_java = project / "src" / "main" / "java" / "com" / "example" / "User.java"
        await ws.ensure_document_open(user_java)

        result = await ws.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(user_java)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "User" in names

    @pytest.mark.asyncio
    async def test_find_definition(self, workspace):
        ws, project = workspace
        main_java = project / "src" / "main" / "java" / "com" / "example" / "Main.java"
        content = main_java.read_text()
        line, col = find_line_col(content, "createSampleUser()", not_pattern="public static")
        col = content.splitlines()[line].index("createSampleUser")

        result = await ws.client.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(main_java)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_find_references(self, workspace):
        ws, project = workspace
        user_java = project / "src" / "main" / "java" / "com" / "example" / "User.java"
        await ws.ensure_document_open(user_java)
        content = user_java.read_text()
        line, col = find_line_col(content, "public class User")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(user_java)},
                "position": {"line": line, "character": col},
                "context": {"includeDeclaration": True},
            },
        )

        assert result is not None
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_find_implementations(self, workspace):
        ws, project = workspace
        storage_java = project / "src" / "main" / "java" / "com" / "example" / "Storage.java"
        await ws.ensure_document_open(storage_java)
        content = storage_java.read_text()
        line, col = find_line_col(content, "public interface Storage")
        col = content.splitlines()[line].index("Storage")

        result = await ws.client.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": path_to_uri(storage_java)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_find_subtypes(self, workspace):
        ws, project = workspace
        abstract_storage_java = project / "src" / "main" / "java" / "com" / "example" / "AbstractStorage.java"
        await ws.ensure_document_open(abstract_storage_java)
        content = abstract_storage_java.read_text()
        line, col = find_line_col(content, "public abstract class AbstractStorage")
        col = content.splitlines()[line].index("AbstractStorage")

        try:
            prepare_result = await ws.client.send_request(
                "textDocument/prepareTypeHierarchy",
                {
                    "textDocument": {"uri": path_to_uri(abstract_storage_java)},
                    "position": {"line": line, "character": col},
                },
            )

            if prepare_result:
                result = await ws.client.send_request(
                    "typeHierarchy/subtypes",
                    {"item": prepare_result[0]},
                )
                assert result is not None
                assert len(result) >= 2  # MemoryStorage and FileStorage
        except LSPResponseError as e:
            if not e.is_method_not_found():
                raise

    @pytest.mark.asyncio
    async def test_find_supertypes(self, workspace):
        ws, project = workspace
        memory_storage_java = project / "src" / "main" / "java" / "com" / "example" / "MemoryStorage.java"
        await ws.ensure_document_open(memory_storage_java)
        content = memory_storage_java.read_text()
        line, col = find_line_col(content, "public class MemoryStorage")
        col = content.splitlines()[line].index("MemoryStorage")

        try:
            prepare_result = await ws.client.send_request(
                "textDocument/prepareTypeHierarchy",
                {
                    "textDocument": {"uri": path_to_uri(memory_storage_java)},
                    "position": {"line": line, "character": col},
                },
            )

            if prepare_result:
                result = await ws.client.send_request(
                    "typeHierarchy/supertypes",
                    {"item": prepare_result[0]},
                )
                assert result is not None
                assert len(result) >= 1  # AbstractStorage
        except LSPResponseError as e:
            if not e.is_method_not_found():
                raise

    @pytest.mark.asyncio
    async def test_describe_hover(self, workspace):
        ws, project = workspace
        user_java = project / "src" / "main" / "java" / "com" / "example" / "User.java"
        await ws.ensure_document_open(user_java)
        content = user_java.read_text()
        line, col = find_line_col(content, "public class User")
        col = content.splitlines()[line].index("User")

        result = await ws.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(user_java)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert "contents" in result

    @pytest.mark.asyncio
    async def test_rename(self, workspace):
        ws, project = workspace
        user_java = project / "src" / "main" / "java" / "com" / "example" / "User.java"
        await ws.ensure_document_open(user_java)
        content = user_java.read_text()
        line, col = find_line_col(content, "private String name")
        col = content.splitlines()[line].index("name")

        result = await ws.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(user_java)},
                "position": {"line": line, "character": col},
                "newName": "fullName",
            },
        )

        assert result is not None
        assert "changes" in result or "documentChanges" in result

    @pytest.mark.asyncio
    async def test_format(self, workspace):
        ws, project = workspace
        main_java = project / "src" / "main" / "java" / "com" / "example" / "Main.java"

        result = await ws.client.send_request(
            "textDocument/formatting",
            {
                "textDocument": {"uri": path_to_uri(main_java)},
                "options": {"tabSize": 4, "insertSpaces": True},
            },
        )

        assert result is None or isinstance(result, list)


# =============================================================================
# Multi-Language Project Tests
# =============================================================================


class TestMultiLanguageIntegration:
    """Integration tests for multi-language projects."""

    @pytest.fixture(scope="class")
    def class_temp_dir(self, tmp_path_factory):
        return tmp_path_factory.mktemp("multi")

    @pytest.fixture(scope="class")
    def class_project(self, class_temp_dir):
        src = FIXTURES_DIR / "multi_language_project"
        dst = class_temp_dir / "multi_language_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def class_isolated_config(self, class_temp_dir):
        cache_dir = class_temp_dir / "cache"
        config_dir = class_temp_dir / "config"
        cache_dir.mkdir()
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

    @pytest.fixture(scope="class")
    def class_session(self, class_isolated_config):
        return Session()

    @pytest.mark.asyncio
    async def test_python_in_multi_project(self, class_project, class_session):
        requires_pyright()

        app_py = class_project / "app.py"
        ws = await class_session.get_or_create_workspace(app_py, class_project)
        await ws.ensure_document_open(app_py)
        await ws.client.wait_for_service_ready()

        result = await ws.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(app_py)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "PythonService" in names
        assert "PythonUser" in names

    @pytest.mark.asyncio
    async def test_go_in_multi_project(self, class_project, class_session):
        requires_gopls()

        main_go = class_project / "main.go"
        ws = await class_session.get_or_create_workspace(main_go, class_project)
        await ws.ensure_document_open(main_go)
        await ws.client.wait_for_service_ready()

        result = await ws.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(main_go)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "GoService" in names
        assert "GoUser" in names

    @pytest.mark.asyncio
    async def test_both_languages_simultaneously(self, class_project, class_session):
        requires_pyright()
        requires_gopls()

        app_py = class_project / "app.py"
        main_go = class_project / "main.go"

        py_ws = await class_session.get_or_create_workspace(app_py, class_project)
        await py_ws.ensure_document_open(app_py)
        await py_ws.client.wait_for_service_ready()

        go_ws = await class_session.get_or_create_workspace(main_go, class_project)
        await go_ws.ensure_document_open(main_go)
        await go_ws.client.wait_for_service_ready()

        py_result = await py_ws.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(app_py)}},
        )

        go_result = await go_ws.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(main_go)}},
        )

        assert py_result is not None
        assert go_result is not None

        py_names = [s["name"] for s in py_result]
        go_names = [s["name"] for s in go_result]

        assert "PythonService" in py_names
        assert "GoService" in go_names

        assert py_ws.server_config.name == "pyright"
        assert go_ws.server_config.name == "gopls"

    @pytest.mark.asyncio
    async def test_python_cross_file_hover(self, class_project, class_session):
        requires_pyright()

        app_py = class_project / "app.py"
        ws = await class_session.get_or_create_workspace(app_py, class_project)
        await ws.ensure_document_open(app_py)
        await ws.client.wait_for_service_ready()

        content = app_py.read_text()
        line, col = find_line_col(content, "class PythonService")
        col = content.splitlines()[line].index("PythonService")

        result = await ws.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(app_py)},
                "position": {"line": line, "character": col},
            },
        )

        assert result is not None
        assert "contents" in result


# =============================================================================
# Daemon Server Handler Tests
# =============================================================================


class TestDaemonHandlers:
    """Test the daemon server request handlers end-to-end."""

    @pytest.fixture(scope="class")
    def class_temp_dir(self, tmp_path_factory):
        return tmp_path_factory.mktemp("daemon")

    @pytest.fixture(scope="class")
    def class_project(self, class_temp_dir):
        src = FIXTURES_DIR / "python_project"
        dst = class_temp_dir / "python_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def class_isolated_config(self, class_temp_dir):
        cache_dir = class_temp_dir / "cache"
        config_dir = class_temp_dir / "config"
        cache_dir.mkdir()
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

    @pytest.fixture(scope="class")
    def class_daemon_server(self, class_isolated_config):
        return DaemonServer()

    @pytest.mark.asyncio
    async def test_list_symbols_handler(self, class_project, class_daemon_server):
        requires_pyright()

        main_py = class_project / "main.py"
        result = await class_daemon_server._handle_list_symbols({
            "path": str(main_py),
            "workspace_root": str(class_project),
        })

        assert isinstance(result, list)
        names = [s["name"] for s in result]
        assert "User" in names
        assert "UserRepository" in names

    @pytest.mark.asyncio
    async def test_find_definition_handler(self, class_project, class_daemon_server):
        requires_pyright()

        main_py = class_project / "main.py"
        content = main_py.read_text()
        line, col = find_line_col(content, "user = create_sample_user()")
        col = content.splitlines()[line].index("create_sample_user")

        result = await class_daemon_server._handle_find_definition({
            "path": str(main_py),
            "workspace_root": str(class_project),
            "line": line + 1,  # 1-based for handler
            "column": col,
        })

        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_hover_handler(self, class_project, class_daemon_server):
        requires_pyright()

        main_py = class_project / "main.py"
        content = main_py.read_text()
        line, col = find_line_col(content, "class User:")
        col = content.splitlines()[line].index("User")

        result = await class_daemon_server._handle_hover({
            "path": str(main_py),
            "workspace_root": str(class_project),
            "line": line + 1,
            "column": col,
        })

        assert "contents" in result

    @pytest.mark.asyncio
    async def test_fetch_symbol_docs_handler(self, class_project, class_daemon_server):
        requires_pyright()

        main_py = class_project / "main.py"
        symbols = await class_daemon_server._handle_list_symbols({
            "path": str(main_py),
            "workspace_root": str(class_project),
        })

        result = await class_daemon_server._handle_fetch_symbol_docs({
            "symbols": symbols[:3],
            "workspace_root": str(class_project),
        })

        assert isinstance(result, list)
        for sym in result:
            assert "documentation" in sym

        await class_daemon_server.session.close_all()
