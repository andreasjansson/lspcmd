import asyncio
import os
from pathlib import Path

import pytest

from lspcmd.daemon.session import Session
from lspcmd.utils.uri import path_to_uri

from .conftest import requires_pyright, requires_rust_analyzer, requires_gopls

os.environ["LSPCMD_REQUEST_TIMEOUT"] = "30"


@pytest.fixture
def session(isolated_config):
    return Session()


class TestPythonIntegration:
    @pytest.fixture(autouse=True)
    def check_pyright(self):
        requires_pyright()

    @pytest.mark.asyncio
    async def test_initialize_server(self, python_project, session):
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)

        assert workspace.client is not None
        assert workspace.client._initialized

        await session.close_all()

    @pytest.mark.asyncio
    async def test_hover(self, python_project, session):
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        result = await workspace.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": 5, "character": 6},
            },
        )

        assert result is not None
        await session.close_all()

    @pytest.mark.asyncio
    async def test_find_definition(self, python_project, session):
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        result = await workspace.client.send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": 36, "character": 11},
            },
        )

        assert result is not None
        await session.close_all()

    @pytest.mark.asyncio
    async def test_find_references(self, python_project, session):
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        result = await workspace.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": 5, "character": 6},
                "context": {"includeDeclaration": True},
            },
        )

        assert result is not None
        assert len(result) >= 1
        await session.close_all()

    @pytest.mark.asyncio
    async def test_document_symbols(self, python_project, session):
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
        await session.close_all()

    @pytest.mark.asyncio
    async def test_rename(self, python_project, session):
        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        result = await workspace.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(main_py)},
                "position": {"line": 5, "character": 6},
                "newName": "Person",
            },
        )

        assert result is not None
        await session.close_all()

    @pytest.mark.asyncio
    async def test_code_actions(self, python_project, session):
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

        await session.close_all()

    @pytest.mark.asyncio
    async def test_implementations_not_supported(self, python_project, session):
        """Python/pyright doesn't support textDocument/implementation."""
        from lspcmd.lsp.protocol import LSPResponseError

        main_py = python_project / "main.py"
        workspace = await session.get_or_create_workspace(main_py, python_project)
        await workspace.ensure_document_open(main_py)

        # Pyright should return an error for implementation requests
        with pytest.raises(LSPResponseError) as exc_info:
            await workspace.client.send_request(
                "textDocument/implementation",
                {
                    "textDocument": {"uri": path_to_uri(main_py)},
                    "position": {"line": 5, "character": 6},
                },
            )

        assert exc_info.value.is_method_not_found()

        await session.close_all()


class TestRustIntegration:
    @pytest.fixture(autouse=True)
    def check_rust_analyzer(self):
        requires_rust_analyzer()

    @pytest.mark.asyncio
    async def test_initialize_server(self, rust_project, session):
        main_rs = rust_project / "src" / "main.rs"
        workspace = await session.get_or_create_workspace(main_rs, rust_project)

        assert workspace.client is not None
        assert workspace.client._initialized

        await session.close_all()

    @pytest.mark.asyncio
    async def test_hover(self, rust_project, session):
        main_rs = rust_project / "src" / "main.rs"
        workspace = await session.get_or_create_workspace(main_rs, rust_project)
        await workspace.ensure_document_open(main_rs)

        await asyncio.sleep(2)

        result = await workspace.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(main_rs)},
                "position": {"line": 4, "character": 4},
            },
        )

        await session.close_all()

    @pytest.mark.asyncio
    async def test_document_symbols(self, rust_project, session):
        main_rs = rust_project / "src" / "main.rs"
        workspace = await session.get_or_create_workspace(main_rs, rust_project)
        await workspace.ensure_document_open(main_rs)

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": path_to_uri(main_rs)}},
        )

        assert result is not None
        await session.close_all()


class TestGoIntegration:
    @pytest.fixture(autouse=True)
    def check_gopls(self):
        requires_gopls()

    @pytest.mark.asyncio
    async def test_initialize_server(self, go_project, session):
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)

        assert workspace.client is not None
        assert workspace.client._initialized

        await session.close_all()

    @pytest.mark.asyncio
    async def test_hover(self, go_project, session):
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)

        result = await workspace.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": 4, "character": 5},
            },
        )

        await session.close_all()

    @pytest.mark.asyncio
    async def test_document_symbols(self, go_project, session):
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
        assert "UserRepository" in names
        await session.close_all()

    @pytest.mark.asyncio
    async def test_implementations(self, go_project, session):
        main_go = go_project / "main.go"
        workspace = await session.get_or_create_workspace(main_go, go_project)
        await workspace.ensure_document_open(main_go)

        # Find implementations of the Storage interface (line 16, 0-indexed = 15)
        result = await workspace.client.send_request(
            "textDocument/implementation",
            {
                "textDocument": {"uri": path_to_uri(main_go)},
                "position": {"line": 15, "character": 5},
            },
        )

        assert result is not None
        assert len(result) == 2  # MemoryStorage and FileStorage

        # Extract the struct names from the results
        content = main_go.read_text()
        lines = content.splitlines()
        impl_names = []
        for loc in result:
            line_num = loc["range"]["start"]["line"]
            impl_names.append(lines[line_num])

        assert any("MemoryStorage" in name for name in impl_names)
        assert any("FileStorage" in name for name in impl_names)

        await session.close_all()
