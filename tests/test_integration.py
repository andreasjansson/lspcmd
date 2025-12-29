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


@requires_pyright
class TestPythonIntegration:
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


@requires_rust_analyzer
class TestRustIntegration:
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


@requires_gopls
class TestGoIntegration:
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
