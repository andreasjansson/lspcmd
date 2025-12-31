"""Tests for the MCP server interface.

These tests verify that the MCP server exposes the correct tools
and that external MCP clients can connect and use them.
"""

import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import httpx
import pytest

from lspcmd.cli import ensure_daemon_running
from lspcmd.utils.config import add_workspace_root, load_config, get_mcp_url

from .conftest import requires_basedpyright, FIXTURES_DIR


class TestMCPServer:
    """Tests for the MCP server interface."""

    @pytest.fixture(scope="class")
    def class_temp_dir(self, tmp_path_factory):
        return tmp_path_factory.mktemp("mcp_test")

    @pytest.fixture(scope="class")
    def class_isolated_config(self, class_temp_dir):
        cache_dir = Path(tempfile.mkdtemp(prefix="lspcmd_mcp_test_"))
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
    def mcp_url(self, class_isolated_config):
        url = ensure_daemon_running()
        time.sleep(0.5)
        yield url
        # Shutdown daemon
        try:
            asyncio.run(self._shutdown_daemon(url))
        except Exception:
            pass

    async def _shutdown_daemon(self, mcp_url: str):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            init_resp = await client.post(
                mcp_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0.1.0"},
                    },
                },
            )
            session_id = init_resp.headers.get("mcp-session-id")
            if session_id:
                client.headers["mcp-session-id"] = session_id
            await client.post(
                mcp_url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            await client.post(
                mcp_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "daemon_shutdown", "arguments": {}},
                },
            )

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "python_project"
        dst = class_temp_dir / "python_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, mcp_url, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        return project

    def test_mcp_initialize(self, mcp_url):
        """Test that MCP initialization works."""
        async def do_test():
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                resp = await client.post(
                    mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "0.1.0"},
                        },
                    },
                )
                assert resp.status_code == 200
                result = resp.json()
                assert "result" in result
                assert result["result"]["serverInfo"]["name"] == "lspcmd"

        asyncio.run(do_test())

    def test_mcp_list_tools(self, mcp_url):
        """Test that MCP tools/list returns all expected tools."""
        async def do_test():
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                # Initialize first
                init_resp = await client.post(
                    mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "0.1.0"},
                        },
                    },
                )
                session_id = init_resp.headers.get("mcp-session-id")
                if session_id:
                    client.headers["mcp-session-id"] = session_id

                await client.post(
                    mcp_url,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )

                # List tools
                resp = await client.post(
                    mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {},
                    },
                )
                assert resp.status_code == 200
                result = resp.json()
                assert "result" in result
                tools = {t["name"] for t in result["result"]["tools"]}
                
                # Check that all main tools are present
                expected_tools = {
                    "grep",
                    "show",
                    "ref",
                    "implementations",
                    "subtypes",
                    "supertypes",
                    "declaration",
                    "diagnostics",
                    "rename",
                    "move_file",
                    "format_file",
                    "organize_imports",
                    "tree",
                    "daemon_info",
                    "daemon_shutdown",
                    "workspace_restart",
                    "raw_lsp_request",
                }
                assert expected_tools.issubset(tools), f"Missing tools: {expected_tools - tools}"

        asyncio.run(do_test())

    def test_mcp_call_daemon_info(self, mcp_url):
        """Test calling the daemon_info tool via MCP."""
        async def do_test():
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                init_resp = await client.post(
                    mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "0.1.0"},
                        },
                    },
                )
                session_id = init_resp.headers.get("mcp-session-id")
                if session_id:
                    client.headers["mcp-session-id"] = session_id

                await client.post(
                    mcp_url,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )

                resp = await client.post(
                    mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "daemon_info",
                            "arguments": {"output_format": "plain"},
                        },
                    },
                )
                assert resp.status_code == 200
                result = resp.json()
                assert "result" in result
                assert result["result"]["isError"] is False
                content = result["result"]["content"]
                assert len(content) > 0
                assert content[0]["type"] == "text"
                assert "Daemon PID:" in content[0]["text"]

        asyncio.run(do_test())

    def test_mcp_call_grep(self, mcp_url, workspace):
        """Test calling the grep tool via MCP."""
        requires_basedpyright()

        async def do_test():
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
                init_resp = await client.post(
                    mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "0.1.0"},
                        },
                    },
                )
                session_id = init_resp.headers.get("mcp-session-id")
                if session_id:
                    client.headers["mcp-session-id"] = session_id

                await client.post(
                    mcp_url,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )

                resp = await client.post(
                    mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "grep",
                            "arguments": {
                                "workspace_root": str(workspace),
                                "pattern": "^User$",
                                "kinds": ["class"],
                                "output_format": "plain",
                            },
                        },
                    },
                )
                assert resp.status_code == 200
                result = resp.json()
                assert "result" in result
                assert result["result"]["isError"] is False
                content = result["result"]["content"]
                assert len(content) > 0
                text = content[0]["text"]
                assert "[Class] User" in text

        asyncio.run(do_test())

    def test_mcp_call_show(self, mcp_url, workspace):
        """Test calling the show tool via MCP."""
        requires_basedpyright()

        async def do_test():
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
                init_resp = await client.post(
                    mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "0.1.0"},
                        },
                    },
                )
                session_id = init_resp.headers.get("mcp-session-id")
                if session_id:
                    client.headers["mcp-session-id"] = session_id

                await client.post(
                    mcp_url,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )

                resp = await client.post(
                    mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "show",
                            "arguments": {
                                "workspace_root": str(workspace),
                                "symbol": "User",
                                "output_format": "plain",
                            },
                        },
                    },
                )
                assert resp.status_code == 200
                result = resp.json()
                assert "result" in result
                assert result["result"]["isError"] is False
                content = result["result"]["content"]
                assert len(content) > 0
                text = content[0]["text"]
                assert "class User:" in text

        asyncio.run(do_test())

    def test_mcp_json_output_format(self, mcp_url, workspace):
        """Test that JSON output format returns valid JSON."""
        requires_basedpyright()

        async def do_test():
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
                init_resp = await client.post(
                    mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "0.1.0"},
                        },
                    },
                )
                session_id = init_resp.headers.get("mcp-session-id")
                if session_id:
                    client.headers["mcp-session-id"] = session_id

                await client.post(
                    mcp_url,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )

                resp = await client.post(
                    mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "grep",
                            "arguments": {
                                "workspace_root": str(workspace),
                                "pattern": "^User$",
                                "kinds": ["class"],
                                "output_format": "json",
                            },
                        },
                    },
                )
                assert resp.status_code == 200
                result = resp.json()
                assert "result" in result
                content = result["result"]["content"]
                text = content[0]["text"]
                # Should be valid JSON
                parsed = json.loads(text)
                assert isinstance(parsed, list)
                assert len(parsed) > 0
                assert parsed[0]["name"] == "User"
                assert parsed[0]["kind"] == "Class"

        asyncio.run(do_test())
