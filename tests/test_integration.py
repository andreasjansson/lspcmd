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
)

os.environ["LSPCMD_REQUEST_TIMEOUT"] = "60"


@pytest.fixture
def session(isolated_config):
    return Session()


@pytest.fixture
def daemon_server(isolated_config):
    return DaemonServer()


async def wait_for_indexing(workspace, delay: float = 1.0):
    """Wait for the language server to finish indexing."""
    await workspace.client.wait_for_service_ready()
    await asyncio.sleep(delay)


# =============================================================================
# Python Integration Tests (pyright)
# =============================================================================


class TestPythonIntegration:
    """Integration tests for Python using pyright."""

    @pytest.fixture(autouse=True)
    def check_pyright(self):
        requires_pyright()

    @pytest.fixture
    def workspace_config(self, python_project, isolated_config):
        config = {"workspaces": {"roots": [str(python_project)]}}
        add_workspace_root(python_project, config)
        return config

    # --- Basic Server Tests ---

    @pytest.mark.asyncio
    async def test_initialize_server(self, python_project, session):
        """Test that pyright initializes correctly."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)

        assert workspace.client is not None
        assert workspace.client._initialized

        await session.close_all()

    # --- grep (document symbols) ---

    @pytest.mark.asyncio
    async def test_grep_document_symbols(self, python_project, session):
        """Test listing symbols from a document."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(main_py)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "User" in names
        assert "UserRepository" in names
        assert "StorageProtocol" in names
        assert "MemoryStorage" in names
        assert "FileStorage" in names

        await session.close_all()

    # --- definition ---

    @pytest.mark.asyncio
    async def test_find_definition(self, python_project, session):
        """Test finding definition of a symbol."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        content = main_py.read_text()
        lines = content.splitlines()
        # Find the line with "user = create_sample_user()"
        for i, line in enumerate(lines):
            if "user = create_sample_user()" in line:
                target_line = i
                target_col = line.index("create_sample_user")
                break

        result = await workspace.client.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert len(result) >= 1

        await session.close_all()

    # --- references ---

    @pytest.mark.asyncio
    async def test_find_references(self, python_project, session):
        """Test finding all references to a symbol."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        content = main_py.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "class User:" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": target_line, "character": target_col},
                "context": {"includeDeclaration": True},
            },
        )

        assert result is not None
        assert len(result) >= 2  # Declaration + at least one usage

        await session.close_all()

    # --- describe (hover) ---

    @pytest.mark.asyncio
    async def test_describe_hover(self, python_project, session):
        """Test getting hover information."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        content = main_py.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "class User:" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert "contents" in result

        await session.close_all()

    # --- diagnostics ---

    @pytest.mark.asyncio
    async def test_diagnostics(self, python_project, session):
        """Test getting diagnostics from pyright."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)
        await wait_for_indexing(workspace)

        # The main.py has an unused import (sys), pyright should report it
        stored = workspace.client.get_stored_diagnostics(path_to_uri(main_py))
        # Diagnostics may or may not be present depending on pyright config
        # Just verify we can retrieve them without error
        assert stored is not None or stored == []

        await session.close_all()

    # --- rename ---

    @pytest.mark.asyncio
    async def test_rename(self, python_project, session):
        """Test renaming a symbol."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        content = main_py.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "class User:" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": target_line, "character": target_col},
                "newName": "Person",
            },
        )

        assert result is not None
        assert "changes" in result or "documentChanges" in result

        await session.close_all()

    # --- list-code-actions ---

    @pytest.mark.asyncio
    async def test_list_code_actions(self, python_project, session):
        """Test listing available code actions."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        result = await workspace.client.send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 0},
                },
                "context": {"diagnostics": []},
            },
        )

        # Code actions may or may not be available
        assert result is None or isinstance(result, list)

        await session.close_all()

    # --- format ---

    @pytest.mark.asyncio
    async def test_format(self, python_project, session):
        """Test document formatting."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        # Pyright doesn't support formatting, but we should handle the response gracefully
        try:
            result = await workspace.client.send_request(
                "textDocument/formatting",
                {
                    "textDocument": {"uri": path_to_uri(main_py)},
                    "options": {"tabSize": 4, "insertSpaces": True},
                },
            )
            # If it returns, it should be a list of edits or null
            assert result is None or isinstance(result, list)
        except LSPResponseError:
            # Pyright may not support formatting
            pass

        await session.close_all()

    # --- organize-imports ---

    @pytest.mark.asyncio
    async def test_organize_imports(self, python_project, session):
        """Test organizing imports."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        result = await workspace.client.send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 0},
                },
                "context": {
                    "diagnostics": [],
                    "only": ["source.organizeImports"],
                },
            },
        )

        # May or may not return organize imports action
        assert result is None or isinstance(result, list)

        await session.close_all()

    # --- raw-lsp-request ---

    @pytest.mark.asyncio
    async def test_raw_lsp_request(self, python_project, session):
        """Test sending a raw LSP request."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        # Send a raw documentSymbol request
        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(main_py)}},
        )

        assert result is not None
        assert isinstance(result, list)

        await session.close_all()

    # --- implementations (not supported by pyright) ---

    @pytest.mark.asyncio
    async def test_implementations_not_supported(self, python_project, session):
        """Test that implementations returns proper error for pyright."""
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        content = main_py.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "class StorageProtocol" in line:
                target_line = i
                target_col = line.index("StorageProtocol")
                break

        with pytest.raises(LSPResponseError) as exc_info:
            await workspace.client.send_request(
                "textDocument/implementation",
                {
                    "textDocument": {"uri": path_to_uri(main_py)},
                    "position": {"line": target_line, "character": target_col},
                },
            )

        assert exc_info.value.is_method_not_found()

        await session.close_all()


# =============================================================================
# Go Integration Tests (gopls)
# =============================================================================


class TestGoIntegration:
    """Integration tests for Go using gopls."""

    @pytest.fixture(autouse=True)
    def check_gopls(self):
        requires_gopls()

    # --- Basic Server Tests ---

    @pytest.mark.asyncio
    async def test_initialize_server(self, go_project, session):
        """Test that gopls initializes correctly."""
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)

        assert workspace.client is not None
        assert workspace.client._initialized

        await session.close_all()

    # --- grep (document symbols) ---

    @pytest.mark.asyncio
    async def test_grep_document_symbols(self, go_project, session):
        """Test listing symbols from a document."""
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(main_go)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "User" in names
        assert "Storage" in names
        assert "MemoryStorage" in names
        assert "FileStorage" in names
        assert "UserRepository" in names

        await session.close_all()

    # --- definition ---

    @pytest.mark.asyncio
    async def test_find_definition(self, go_project, session):
        """Test finding definition of a symbol."""
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)

        content = main_go.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "user := createSampleUser()" in line:
                target_line = i
                target_col = line.index("createSampleUser")
                break

        result = await workspace.client.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert len(result) >= 1

        await session.close_all()

    # --- references ---

    @pytest.mark.asyncio
    async def test_find_references(self, go_project, session):
        """Test finding all references to a symbol."""
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)

        content = main_go.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "type User struct" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": target_line, "character": target_col},
                "context": {"includeDeclaration": True},
            },
        )

        assert result is not None
        assert len(result) >= 2

        await session.close_all()

    # --- implementations ---

    @pytest.mark.asyncio
    async def test_find_implementations(self, go_project, session):
        """Test finding implementations of an interface."""
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)
        await wait_for_indexing(workspace, delay=2.0)

        content = main_go.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "type Storage interface" in line:
                target_line = i
                target_col = line.index("Storage")
                break

        result = await workspace.client.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert len(result) == 2  # MemoryStorage and FileStorage

        await session.close_all()

    # --- subtypes (type hierarchy) ---

    @pytest.mark.asyncio
    async def test_find_subtypes(self, go_project, session):
        """Test finding subtypes via type hierarchy."""
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)
        await wait_for_indexing(workspace, delay=2.0)

        content = main_go.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "type Storage interface" in line:
                target_line = i
                target_col = line.index("Storage")
                break

        # First prepare type hierarchy
        prepare_result = await workspace.client.send_request(
            "textDocument/prepareTypeHierarchy",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        if prepare_result:
            result = await workspace.client.send_request(
                "typeHierarchy/subtypes",
                {"item": prepare_result[0]},
            )
            # gopls should find implementations as subtypes
            assert result is None or isinstance(result, list)

        await session.close_all()

    # --- describe (hover) ---

    @pytest.mark.asyncio
    async def test_describe_hover(self, go_project, session):
        """Test getting hover information."""
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)

        content = main_go.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "type User struct" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert "contents" in result

        await session.close_all()

    # --- diagnostics ---

    @pytest.mark.asyncio
    async def test_diagnostics(self, go_project, session):
        """Test getting diagnostics from gopls."""
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)
        await wait_for_indexing(workspace)

        # Try pull diagnostics first
        if workspace.client.supports_pull_diagnostics:
            try:
                result = await workspace.client.send_request(
                    "textDocument/diagnostic",
                    {"textDocument": {"uri": path_to_uri(main_go)}},
                )
                assert result is None or "items" in result
            except LSPResponseError:
                pass

        await session.close_all()

    # --- rename ---

    @pytest.mark.asyncio
    async def test_rename(self, go_project, session):
        """Test renaming a symbol."""
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)

        content = main_go.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "type User struct" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": target_line, "character": target_col},
                "newName": "Person",
            },
        )

        assert result is not None
        assert "changes" in result or "documentChanges" in result

        await session.close_all()

    # --- format ---

    @pytest.mark.asyncio
    async def test_format(self, go_project, session):
        """Test document formatting."""
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)

        result = await workspace.client.send_request(
            "textDocument/formatting",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "options": {"tabSize": 4, "insertSpaces": False},
            },
        )

        # gopls supports formatting
        assert result is None or isinstance(result, list)

        await session.close_all()

    # --- organize-imports ---

    @pytest.mark.asyncio
    async def test_organize_imports(self, go_project, session):
        """Test organizing imports."""
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)

        result = await workspace.client.send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 0},
                },
                "context": {
                    "diagnostics": [],
                    "only": ["source.organizeImports"],
                },
            },
        )

        assert result is None or isinstance(result, list)

        await session.close_all()


# =============================================================================
# Rust Integration Tests (rust-analyzer)
# =============================================================================


class TestRustIntegration:
    """Integration tests for Rust using rust-analyzer."""

    @pytest.fixture(autouse=True)
    def check_rust_analyzer(self):
        requires_rust_analyzer()

    # --- Basic Server Tests ---

    @pytest.mark.asyncio
    async def test_initialize_server(self, rust_project, session):
        """Test that rust-analyzer initializes correctly."""
        main_rs = rust_project / "src" / "main.rs"
        workspace = await session.get_or_create_workspace(main_rs, rust_project)

        assert workspace.client is not None
        assert workspace.client._initialized

        await session.close_all()

    # --- grep (document symbols) ---

    @pytest.mark.asyncio
    async def test_grep_document_symbols(self, rust_project, session):
        """Test listing symbols from a document."""
        user_rs = rust_project / "src" / "user.rs"
        workspace = await session.get_or_create_workspace(user_rs, rust_project)
        await workspace.ensure_document_open(user_rs)
        await wait_for_indexing(workspace, delay=3.0)

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(user_rs)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "User" in names
        assert "UserRepository" in names

        await session.close_all()

    # --- definition ---

    @pytest.mark.asyncio
    async def test_find_definition(self, rust_project, session):
        """Test finding definition of a symbol."""
        main_rs = rust_project / "src" / "main.rs"
        workspace = await session.get_or_create_workspace(main_rs, rust_project)
        await workspace.ensure_document_open(main_rs)
        await wait_for_indexing(workspace, delay=3.0)

        content = main_rs.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "create_sample_user()" in line and "fn" not in line:
                target_line = i
                target_col = line.index("create_sample_user")
                break

        result = await workspace.client.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(main_rs)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None

        await session.close_all()

    # --- references ---

    @pytest.mark.asyncio
    async def test_find_references(self, rust_project, session):
        """Test finding all references to a symbol."""
        user_rs = rust_project / "src" / "user.rs"
        workspace = await session.get_or_create_workspace(user_rs, rust_project)
        await workspace.ensure_document_open(user_rs)
        await wait_for_indexing(workspace, delay=3.0)

        content = user_rs.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "pub struct User" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(user_rs)},
                "position": {"line": target_line, "character": target_col},
                "context": {"includeDeclaration": True},
            },
        )

        assert result is not None
        assert len(result) >= 1

        await session.close_all()

    # --- implementations ---

    @pytest.mark.asyncio
    async def test_find_implementations(self, rust_project, session):
        """Test finding implementations of a trait."""
        storage_rs = rust_project / "src" / "storage.rs"
        workspace = await session.get_or_create_workspace(storage_rs, rust_project)
        await workspace.ensure_document_open(storage_rs)
        await wait_for_indexing(workspace, delay=3.0)

        content = storage_rs.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "pub trait Storage" in line:
                target_line = i
                target_col = line.index("Storage")
                break

        result = await workspace.client.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": path_to_uri(storage_rs)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert len(result) >= 2  # MemoryStorage and FileStorage impl blocks

        await session.close_all()

    # --- describe (hover) ---

    @pytest.mark.asyncio
    async def test_describe_hover(self, rust_project, session):
        """Test getting hover information."""
        user_rs = rust_project / "src" / "user.rs"
        workspace = await session.get_or_create_workspace(user_rs, rust_project)
        await workspace.ensure_document_open(user_rs)
        await wait_for_indexing(workspace, delay=3.0)

        content = user_rs.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "pub struct User" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(user_rs)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert "contents" in result

        await session.close_all()

    # --- rename ---

    @pytest.mark.asyncio
    async def test_rename(self, rust_project, session):
        """Test renaming a symbol."""
        user_rs = rust_project / "src" / "user.rs"
        workspace = await session.get_or_create_workspace(user_rs, rust_project)
        await workspace.ensure_document_open(user_rs)
        await wait_for_indexing(workspace, delay=3.0)

        content = user_rs.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "pub struct User" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(user_rs)},
                "position": {"line": target_line, "character": target_col},
                "newName": "Person",
            },
        )

        assert result is not None
        assert "changes" in result or "documentChanges" in result

        await session.close_all()

    # --- format ---

    @pytest.mark.asyncio
    async def test_format(self, rust_project, session):
        """Test document formatting."""
        main_rs = rust_project / "src" / "main.rs"
        workspace = await session.get_or_create_workspace(main_rs, rust_project)
        await workspace.ensure_document_open(main_rs)
        await wait_for_indexing(workspace, delay=3.0)

        result = await workspace.client.send_request(
            "textDocument/formatting",
            {
                "textDocument": {"uri": path_to_uri(main_rs)},
                "options": {"tabSize": 4, "insertSpaces": True},
            },
        )

        # rust-analyzer supports formatting via rustfmt
        assert result is None or isinstance(result, list)

        await session.close_all()


# =============================================================================
# TypeScript Integration Tests (typescript-language-server)
# =============================================================================


class TestTypeScriptIntegration:
    """Integration tests for TypeScript using typescript-language-server."""

    @pytest.fixture(autouse=True)
    def check_typescript_lsp(self):
        requires_typescript_lsp()

    # --- Basic Server Tests ---

    @pytest.mark.asyncio
    async def test_initialize_server(self, typescript_project, session):
        """Test that typescript-language-server initializes correctly."""
        main_ts = typescript_project / "src" / "main.ts"
        workspace = await session.get_or_create_workspace(main_ts, typescript_project)

        assert workspace.client is not None
        assert workspace.client._initialized

        await session.close_all()

    # --- grep (document symbols) ---

    @pytest.mark.asyncio
    async def test_grep_document_symbols(self, typescript_project, session):
        """Test listing symbols from a document."""
        user_ts = typescript_project / "src" / "user.ts"
        workspace = await session.get_or_create_workspace(user_ts, typescript_project)
        await workspace.ensure_document_open(user_ts)

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(user_ts)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "User" in names
        assert "Storage" in names
        assert "MemoryStorage" in names
        assert "UserRepository" in names

        await session.close_all()

    # --- definition ---

    @pytest.mark.asyncio
    async def test_find_definition(self, typescript_project, session):
        """Test finding definition of a symbol."""
        main_ts = typescript_project / "src" / "main.ts"
        workspace = await session.get_or_create_workspace(main_ts, typescript_project)
        await workspace.ensure_document_open(main_ts)

        content = main_ts.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "createSampleUser()" in line and "function" not in line:
                target_line = i
                target_col = line.index("createSampleUser")
                break

        result = await workspace.client.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(main_ts)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert len(result) >= 1

        await session.close_all()

    # --- references ---

    @pytest.mark.asyncio
    async def test_find_references(self, typescript_project, session):
        """Test finding all references to a symbol."""
        user_ts = typescript_project / "src" / "user.ts"
        workspace = await session.get_or_create_workspace(user_ts, typescript_project)
        await workspace.ensure_document_open(user_ts)

        content = user_ts.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "export class User" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(user_ts)},
                "position": {"line": target_line, "character": target_col},
                "context": {"includeDeclaration": True},
            },
        )

        assert result is not None
        assert len(result) >= 1

        await session.close_all()

    # --- implementations ---

    @pytest.mark.asyncio
    async def test_find_implementations(self, typescript_project, session):
        """Test finding implementations of an interface."""
        user_ts = typescript_project / "src" / "user.ts"
        workspace = await session.get_or_create_workspace(user_ts, typescript_project)
        await workspace.ensure_document_open(user_ts)
        await wait_for_indexing(workspace)

        content = user_ts.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "export interface Storage" in line:
                target_line = i
                target_col = line.index("Storage")
                break

        result = await workspace.client.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": path_to_uri(user_ts)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert len(result) >= 2  # MemoryStorage and FileStorage

        await session.close_all()

    # --- describe (hover) ---

    @pytest.mark.asyncio
    async def test_describe_hover(self, typescript_project, session):
        """Test getting hover information."""
        user_ts = typescript_project / "src" / "user.ts"
        workspace = await session.get_or_create_workspace(user_ts, typescript_project)
        await workspace.ensure_document_open(user_ts)

        content = user_ts.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "export class User" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(user_ts)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert "contents" in result

        await session.close_all()

    # --- rename ---

    @pytest.mark.asyncio
    async def test_rename(self, typescript_project, session):
        """Test renaming a symbol."""
        user_ts = typescript_project / "src" / "user.ts"
        workspace = await session.get_or_create_workspace(user_ts, typescript_project)
        await workspace.ensure_document_open(user_ts)

        content = user_ts.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "export class User" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(user_ts)},
                "position": {"line": target_line, "character": target_col},
                "newName": "Person",
            },
        )

        assert result is not None
        assert "changes" in result or "documentChanges" in result

        await session.close_all()

    # --- format ---

    @pytest.mark.asyncio
    async def test_format(self, typescript_project, session):
        """Test document formatting."""
        main_ts = typescript_project / "src" / "main.ts"
        workspace = await session.get_or_create_workspace(main_ts, typescript_project)
        await workspace.ensure_document_open(main_ts)

        result = await workspace.client.send_request(
            "textDocument/formatting",
            {
                "textDocument": {"uri": path_to_uri(main_ts)},
                "options": {"tabSize": 2, "insertSpaces": True},
            },
        )

        # typescript-language-server supports formatting
        assert result is None or isinstance(result, list)

        await session.close_all()

    # --- organize-imports ---

    @pytest.mark.asyncio
    async def test_organize_imports(self, typescript_project, session):
        """Test organizing imports."""
        main_ts = typescript_project / "src" / "main.ts"
        workspace = await session.get_or_create_workspace(main_ts, typescript_project)
        await workspace.ensure_document_open(main_ts)

        result = await workspace.client.send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": path_to_uri(main_ts)},
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 0},
                },
                "context": {
                    "diagnostics": [],
                    "only": ["source.organizeImports"],
                },
            },
        )

        # Should have organize imports action due to unused 'path' import
        assert result is None or isinstance(result, list)

        await session.close_all()


# =============================================================================
# Java Integration Tests (jdtls)
# =============================================================================


class TestJavaIntegration:
    """Integration tests for Java using jdtls."""

    @pytest.fixture(autouse=True)
    def check_jdtls(self):
        requires_jdtls()

    @pytest.fixture
    def java_project(self, temp_dir):
        """Copy java project and ensure proper structure."""
        from .conftest import FIXTURES_DIR
        src = FIXTURES_DIR / "java_project"
        dst = temp_dir / "java_project"
        shutil.copytree(src, dst)
        return dst

    # --- Basic Server Tests ---

    @pytest.mark.asyncio
    async def test_initialize_server(self, java_project, session):
        """Test that jdtls initializes correctly."""
        main_java = java_project / "src" / "main" / "java" / "com" / "example" / "Main.java"
        workspace = await session.get_or_create_workspace(main_java, java_project)

        assert workspace.client is not None
        assert workspace.client._initialized

        await session.close_all()

    # --- grep (document symbols) ---

    @pytest.mark.asyncio
    async def test_grep_document_symbols(self, java_project, session):
        """Test listing symbols from a document."""
        user_java = java_project / "src" / "main" / "java" / "com" / "example" / "User.java"
        workspace = await session.get_or_create_workspace(user_java, java_project)
        await workspace.ensure_document_open(user_java)
        await wait_for_indexing(workspace, delay=5.0)

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(user_java)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "User" in names

        await session.close_all()

    # --- definition ---

    @pytest.mark.asyncio
    async def test_find_definition(self, java_project, session):
        """Test finding definition of a symbol."""
        main_java = java_project / "src" / "main" / "java" / "com" / "example" / "Main.java"
        workspace = await session.get_or_create_workspace(main_java, java_project)
        await workspace.ensure_document_open(main_java)
        await wait_for_indexing(workspace, delay=5.0)

        content = main_java.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "createSampleUser()" in line and "public static" not in line:
                target_line = i
                target_col = line.index("createSampleUser")
                break

        result = await workspace.client.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(main_java)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None

        await session.close_all()

    # --- references ---

    @pytest.mark.asyncio
    async def test_find_references(self, java_project, session):
        """Test finding all references to a symbol."""
        user_java = java_project / "src" / "main" / "java" / "com" / "example" / "User.java"
        workspace = await session.get_or_create_workspace(user_java, java_project)
        await workspace.ensure_document_open(user_java)
        await wait_for_indexing(workspace, delay=5.0)

        content = user_java.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "public class User" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(user_java)},
                "position": {"line": target_line, "character": target_col},
                "context": {"includeDeclaration": True},
            },
        )

        assert result is not None
        assert len(result) >= 1

        await session.close_all()

    # --- implementations ---

    @pytest.mark.asyncio
    async def test_find_implementations(self, java_project, session):
        """Test finding implementations of an interface."""
        storage_java = java_project / "src" / "main" / "java" / "com" / "example" / "Storage.java"
        workspace = await session.get_or_create_workspace(storage_java, java_project)
        await workspace.ensure_document_open(storage_java)
        await wait_for_indexing(workspace, delay=5.0)

        content = storage_java.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "public interface Storage" in line:
                target_line = i
                target_col = line.index("Storage")
                break

        result = await workspace.client.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": path_to_uri(storage_java)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        # jdtls should find AbstractStorage (which implements Storage)
        assert result is not None
        assert len(result) >= 1

        await session.close_all()

    # --- subtypes (type hierarchy) ---

    @pytest.mark.asyncio
    async def test_find_subtypes(self, java_project, session):
        """Test finding subtypes via type hierarchy."""
        abstract_storage_java = java_project / "src" / "main" / "java" / "com" / "example" / "AbstractStorage.java"
        workspace = await session.get_or_create_workspace(abstract_storage_java, java_project)
        await workspace.ensure_document_open(abstract_storage_java)
        await wait_for_indexing(workspace, delay=5.0)

        content = abstract_storage_java.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "public abstract class AbstractStorage" in line:
                target_line = i
                target_col = line.index("AbstractStorage")
                break

        # First prepare type hierarchy
        try:
            prepare_result = await workspace.client.send_request(
                "textDocument/prepareTypeHierarchy",
                {
                    "textDocument": {"uri": path_to_uri(abstract_storage_java)},
                    "position": {"line": target_line, "character": target_col},
                },
            )

            if prepare_result:
                result = await workspace.client.send_request(
                    "typeHierarchy/subtypes",
                    {"item": prepare_result[0]},
                )
                # Should find MemoryStorage and FileStorage as subtypes
                assert result is not None
                assert len(result) >= 2
        except LSPResponseError as e:
            if not e.is_method_not_found():
                raise

        await session.close_all()

    # --- supertypes (type hierarchy) ---

    @pytest.mark.asyncio
    async def test_find_supertypes(self, java_project, session):
        """Test finding supertypes via type hierarchy."""
        memory_storage_java = java_project / "src" / "main" / "java" / "com" / "example" / "MemoryStorage.java"
        workspace = await session.get_or_create_workspace(memory_storage_java, java_project)
        await workspace.ensure_document_open(memory_storage_java)
        await wait_for_indexing(workspace, delay=5.0)

        content = memory_storage_java.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "public class MemoryStorage" in line:
                target_line = i
                target_col = line.index("MemoryStorage")
                break

        try:
            prepare_result = await workspace.client.send_request(
                "textDocument/prepareTypeHierarchy",
                {
                    "textDocument": {"uri": path_to_uri(memory_storage_java)},
                    "position": {"line": target_line, "character": target_col},
                },
            )

            if prepare_result:
                result = await workspace.client.send_request(
                    "typeHierarchy/supertypes",
                    {"item": prepare_result[0]},
                )
                # Should find AbstractStorage as supertype
                assert result is not None
                assert len(result) >= 1
        except LSPResponseError as e:
            if not e.is_method_not_found():
                raise

        await session.close_all()

    # --- describe (hover) ---

    @pytest.mark.asyncio
    async def test_describe_hover(self, java_project, session):
        """Test getting hover information."""
        user_java = java_project / "src" / "main" / "java" / "com" / "example" / "User.java"
        workspace = await session.get_or_create_workspace(user_java, java_project)
        await workspace.ensure_document_open(user_java)
        await wait_for_indexing(workspace, delay=5.0)

        content = user_java.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "public class User" in line:
                target_line = i
                target_col = line.index("User")
                break

        result = await workspace.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(user_java)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert "contents" in result

        await session.close_all()

    # --- rename ---

    @pytest.mark.asyncio
    async def test_rename(self, java_project, session):
        """Test renaming a symbol."""
        user_java = java_project / "src" / "main" / "java" / "com" / "example" / "User.java"
        workspace = await session.get_or_create_workspace(user_java, java_project)
        await workspace.ensure_document_open(user_java)
        await wait_for_indexing(workspace, delay=5.0)

        content = user_java.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "private String name" in line:
                target_line = i
                target_col = line.index("name")
                break

        result = await workspace.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(user_java)},
                "position": {"line": target_line, "character": target_col},
                "newName": "fullName",
            },
        )

        assert result is not None
        assert "changes" in result or "documentChanges" in result

        await session.close_all()

    # --- format ---

    @pytest.mark.asyncio
    async def test_format(self, java_project, session):
        """Test document formatting."""
        main_java = java_project / "src" / "main" / "java" / "com" / "example" / "Main.java"
        workspace = await session.get_or_create_workspace(main_java, java_project)
        await workspace.ensure_document_open(main_java)
        await wait_for_indexing(workspace, delay=5.0)

        result = await workspace.client.send_request(
            "textDocument/formatting",
            {
                "textDocument": {"uri": path_to_uri(main_java)},
                "options": {"tabSize": 4, "insertSpaces": True},
            },
        )

        # jdtls supports formatting
        assert result is None or isinstance(result, list)

        await session.close_all()


# =============================================================================
# Multi-Language Project Tests
# =============================================================================


class TestMultiLanguageIntegration:
    """Integration tests for multi-language projects."""

    @pytest.fixture
    def multi_project(self, temp_dir):
        """Copy multi-language project."""
        from .conftest import FIXTURES_DIR
        src = FIXTURES_DIR / "multi_language_project"
        dst = temp_dir / "multi_language_project"
        shutil.copytree(src, dst)
        return dst

    # --- Python in multi-language project ---

    @pytest.mark.asyncio
    async def test_python_in_multi_project(self, multi_project, session):
        """Test Python LSP in a multi-language project."""
        requires_pyright()

        app_py = multi_project / "app.py"
        workspace = await session.get_or_create_workspace(app_py, multi_project)
        await workspace.ensure_document_open(app_py)

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(app_py)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "PythonService" in names
        assert "PythonUser" in names

        await session.close_all()

    # --- Go in multi-language project ---

    @pytest.mark.asyncio
    async def test_go_in_multi_project(self, multi_project, session):
        """Test Go LSP in a multi-language project."""
        requires_gopls()

        main_go = multi_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, multi_project)
        await workspace.ensure_document_open(main_go)

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(main_go)}},
        )

        assert result is not None
        names = [s["name"] for s in result]
        assert "GoService" in names
        assert "GoUser" in names

        await session.close_all()

    # --- Both languages simultaneously ---

    @pytest.mark.asyncio
    async def test_both_languages_simultaneously(self, multi_project, session):
        """Test that both Python and Go LSP servers work simultaneously."""
        requires_pyright()
        requires_gopls()

        app_py = multi_project / "app.py"
        main_go = multi_project / "main.go"

        # Start Python workspace
        py_workspace = await session.get_or_create_workspace(app_py, multi_project)
        await py_workspace.ensure_document_open(app_py)

        # Start Go workspace
        go_workspace = await session.get_or_create_workspace(main_go, multi_project)
        await go_workspace.ensure_document_open(main_go)

        # Query both
        py_result = await py_workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(app_py)}},
        )

        go_result = await go_workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(main_go)}},
        )

        assert py_result is not None
        assert go_result is not None

        py_names = [s["name"] for s in py_result]
        go_names = [s["name"] for s in go_result]

        assert "PythonService" in py_names
        assert "GoService" in go_names

        # Verify we have two different workspaces
        assert py_workspace.server_config.name == "pyright"
        assert go_workspace.server_config.name == "gopls"

        await session.close_all()

    # --- Cross-file references in same language ---

    @pytest.mark.asyncio
    async def test_python_cross_file_hover(self, multi_project, session):
        """Test hover works across files in Python."""
        requires_pyright()

        app_py = multi_project / "app.py"
        workspace = await session.get_or_create_workspace(app_py, multi_project)
        await workspace.ensure_document_open(app_py)

        content = app_py.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "class PythonService" in line:
                target_line = i
                target_col = line.index("PythonService")
                break

        result = await workspace.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(app_py)},
                "position": {"line": target_line, "character": target_col},
            },
        )

        assert result is not None
        assert "contents" in result

        await session.close_all()


# =============================================================================
# Daemon Server Handler Tests
# =============================================================================


class TestDaemonHandlers:
    """Test the daemon server request handlers end-to-end."""

    @pytest.mark.asyncio
    async def test_list_symbols_handler(self, python_project, daemon_server, isolated_config):
        """Test the list-symbols handler."""
        requires_pyright()

        main_py = python_project / "main.py"
        result = await daemon_server._handle_list_symbols({
            "path": str(main_py),
            "workspace_root": str(python_project),
        })

        assert isinstance(result, list)
        names = [s["name"] for s in result]
        assert "User" in names
        assert "UserRepository" in names

        await daemon_server.session.close_all()

    @pytest.mark.asyncio
    async def test_find_definition_handler(self, python_project, daemon_server, isolated_config):
        """Test the find-definition handler."""
        requires_pyright()

        main_py = python_project / "main.py"
        content = main_py.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "user = create_sample_user()" in line:
                target_line = i + 1  # 1-based for handler
                target_col = line.index("create_sample_user")
                break

        result = await daemon_server._handle_find_definition({
            "path": str(main_py),
            "workspace_root": str(python_project),
            "line": target_line,
            "column": target_col,
        })

        assert isinstance(result, list)
        assert len(result) >= 1

        await daemon_server.session.close_all()

    @pytest.mark.asyncio
    async def test_hover_handler(self, python_project, daemon_server, isolated_config):
        """Test the describe (hover) handler."""
        requires_pyright()

        main_py = python_project / "main.py"
        content = main_py.read_text()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "class User:" in line:
                target_line = i + 1
                target_col = line.index("User")
                break

        result = await daemon_server._handle_hover({
            "path": str(main_py),
            "workspace_root": str(python_project),
            "line": target_line,
            "column": target_col,
        })

        assert "contents" in result

        await daemon_server.session.close_all()

    @pytest.mark.asyncio
    async def test_fetch_symbol_docs_handler(self, python_project, daemon_server, isolated_config):
        """Test the fetch-symbol-docs handler."""
        requires_pyright()

        main_py = python_project / "main.py"
        # First get symbols
        symbols = await daemon_server._handle_list_symbols({
            "path": str(main_py),
            "workspace_root": str(python_project),
        })

        # Then fetch docs for them
        result = await daemon_server._handle_fetch_symbol_docs({
            "symbols": symbols[:3],  # Just first 3 to speed up test
            "workspace_root": str(python_project),
        })

        assert isinstance(result, list)
        # Each symbol should now have a documentation field
        for sym in result:
            assert "documentation" in sym

        await daemon_server.session.close_all()
