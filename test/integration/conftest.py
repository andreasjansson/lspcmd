"""Integration tests for lspcmd.

Tests LSP features using the MCP-based CLI interface.
Uses pytest-xdist for parallel execution to test concurrent daemon access.

Run with: pytest test/integration/ -v
"""

import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import click
import httpx
import pytest

from lspcmd.cli import call_mcp_tool, ensure_daemon_running, strip_mcp_error_prefix
from lspcmd.output.formatters import format_output as _format_output
from lspcmd.utils.config import add_workspace_root, load_config

from ..conftest import (
    FIXTURES_DIR,
    requires_basedpyright,
    requires_clangd,
    requires_gopls,
    requires_intelephense,
    requires_jdtls,
    requires_lua_ls,
    requires_rust_analyzer,
    requires_solargraph,
    requires_typescript_lsp,
    requires_zls,
)

os.environ["LSPCMD_REQUEST_TIMEOUT"] = "60"


def run_request(method: str, params: dict) -> dict:
    """Compatibility wrapper for old-style requests.
    
    Maps the old method names to MCP tool calls and returns
    results in the old format for test compatibility.
    """
    workspace_root = params.get("workspace_root", "")
    
    method_mapping = {
        "grep": "grep",
        "definition": "show",
        "declaration": "declaration",
        "references": "ref",
        "implementations": "implementations",
        "subtypes": "subtypes",
        "supertypes": "supertypes",
        "diagnostics": "diagnostics",
        "workspace-diagnostics": "diagnostics",
        "format": "format_file",
        "organize-imports": "organize_imports",
        "rename": "rename",
        "move-file": "move_file",
        "describe-session": "daemon_info",
        "shutdown": "daemon_shutdown",
        "restart-workspace": "workspace_restart",
        "raw-lsp-request": "raw_lsp_request",
        "describe": "show",
        "tree": "tree",
        "resolve-symbol": "_resolve_symbol",
    }
    
    tool_name = method_mapping.get(method)
    if not tool_name:
        raise ValueError(f"Unknown method: {method}")
    
    if method == "grep":
        mcp_args = {
            "workspace_root": workspace_root,
            "pattern": params.get("pattern", ".*"),
            "kinds": params.get("kinds"),
            "case_sensitive": params.get("case_sensitive", False),
            "include_docs": params.get("include_docs", False),
            "paths": params.get("paths"),
            "exclude_patterns": params.get("exclude_patterns", []),
            "output_format": "json",
        }
    elif method == "definition":
        return _call_definition_request(params)
    elif method == "describe":
        return _call_hover_request(params)
    elif method in ("declaration", "references", "implementations"):
        return _call_location_request(method, params)
    elif method in ("subtypes", "supertypes"):
        return _call_type_hierarchy_request(method, params)
    elif method in ("diagnostics", "workspace-diagnostics"):
        mcp_args = {
            "workspace_root": workspace_root,
            "path": params.get("path"),
            "severity": params.get("severity"),
            "output_format": "json",
        }
    elif method == "rename":
        return _call_rename_request(params)
    elif method == "move-file":
        return _call_move_file_request(params)
    elif method == "format":
        mcp_args = {
            "workspace_root": workspace_root,
            "path": params.get("path", ""),
            "output_format": "json",
        }
    elif method == "organize-imports":
        mcp_args = {
            "workspace_root": workspace_root,
            "path": params.get("path", ""),
            "output_format": "json",
        }
    elif method == "tree":
        mcp_args = {
            "workspace_root": workspace_root,
            "exclude_patterns": params.get("exclude_patterns", []),
            "output_format": "json",
        }
    elif method == "describe-session":
        mcp_args = {"output_format": "json"}
    elif method == "shutdown":
        mcp_args = {}
    elif method == "restart-workspace":
        mcp_args = {
            "workspace_root": workspace_root,
            "output_format": "json",
        }
    elif method == "raw-lsp-request":
        mcp_args = {
            "workspace_root": workspace_root,
            "method": params.get("method", ""),
            "params": json.dumps(params.get("params", {})),
            "language": params.get("language", "python"),
        }
    elif method == "resolve-symbol":
        return _call_resolve_symbol_request(params)
    else:
        raise ValueError(f"Unhandled method: {method}")
    
    result_text = call_mcp_tool(tool_name, mcp_args)
    try:
        return {"result": json.loads(result_text)}
    except json.JSONDecodeError:
        return {"result": result_text}


async def _mcp_call_tool(mcp_url: str, tool_name: str, arguments: dict, raise_on_error: bool = False) -> dict:
    """Shared helper to call an MCP tool."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    
    async with httpx.AsyncClient(timeout=120.0, headers=headers) as client:
        init_resp = await client.post(
            mcp_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "lspcmd-test", "version": "0.1.0"},
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
        
        response = await client.post(
            mcp_url,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            },
        )
        result = response.json()
        
        if "error" in result:
            error_msg = result["error"].get("message", str(result["error"]))
            error_msg = strip_mcp_error_prefix(error_msg)
            if raise_on_error:
                raise click.ClickException(error_msg)
            return {"error": error_msg}
        
        mcp_result = result.get("result", {})
        if mcp_result.get("isError"):
            content = mcp_result.get("content", [])
            if content and isinstance(content, list):
                error_msg = content[0].get("text", "Unknown error")
                error_msg = strip_mcp_error_prefix(error_msg)
                if raise_on_error:
                    raise click.ClickException(error_msg)
                return {"error": error_msg}
        
        content = mcp_result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "")
            try:
                return {"result": json.loads(text)}
            except json.JSONDecodeError:
                return {"result": text}
        return {"result": {}}


def _call_definition_request(params: dict) -> dict:
    """Call definition request directly via daemon internal method."""
    mcp_url = ensure_daemon_running()
    return asyncio.run(_mcp_call_tool(mcp_url, "_internal_definition", {
        "workspace_root": params.get("workspace_root", ""),
        "path": params.get("path", ""),
        "line": params.get("line", 1),
        "column": params.get("column", 0),
        "context": params.get("context", 0),
        "body": params.get("body", False),
    }))


def _call_hover_request(params: dict) -> dict:
    """Call hover request directly."""
    mcp_url = ensure_daemon_running()
    result = asyncio.run(_mcp_call_tool(mcp_url, "_internal_hover", {
        "workspace_root": params.get("workspace_root", ""),
        "path": params.get("path", ""),
        "line": params.get("line", 1),
        "column": params.get("column", 0),
    }))
    if "result" in result and isinstance(result["result"], dict):
        if "contents" not in result["result"]:
            result["result"] = {"contents": result["result"].get("contents")}
    return result


def _call_location_request(method: str, params: dict) -> dict:
    """Call location-based request (references, implementations, declaration)."""
    mcp_url = ensure_daemon_running()
    return asyncio.run(_mcp_call_tool(mcp_url, f"_internal_{method}", {
        "workspace_root": params.get("workspace_root", ""),
        "path": params.get("path", ""),
        "line": params.get("line", 1),
        "column": params.get("column", 0),
        "context": params.get("context", 0),
    }, raise_on_error=True))


def _call_type_hierarchy_request(method: str, params: dict) -> dict:
    """Call type hierarchy request (subtypes, supertypes)."""
    mcp_url = ensure_daemon_running()
    return asyncio.run(_mcp_call_tool(mcp_url, f"_internal_{method}", {
        "workspace_root": params.get("workspace_root", ""),
        "path": params.get("path", ""),
        "line": params.get("line", 1),
        "column": params.get("column", 0),
        "context": params.get("context", 0),
    }, raise_on_error=True))


def _call_rename_request(params: dict) -> dict:
    """Call rename request."""
    mcp_url = ensure_daemon_running()
    return asyncio.run(_mcp_call_tool(mcp_url, "_internal_rename", {
        "workspace_root": params.get("workspace_root", ""),
        "path": params.get("path", ""),
        "line": params.get("line", 1),
        "column": params.get("column", 0),
        "new_name": params.get("new_name", ""),
    }))


def _call_resolve_symbol_request(params: dict) -> dict:
    """Call resolve-symbol request."""
    mcp_url = ensure_daemon_running()
    return asyncio.run(_mcp_call_tool(mcp_url, "_internal_resolve_symbol", {
        "workspace_root": params.get("workspace_root", ""),
        "symbol_path": params.get("symbol_path", ""),
    }))


def _call_move_file_request(params: dict) -> dict:
    """Call move-file request."""
    mcp_url = ensure_daemon_running()
    return asyncio.run(_mcp_call_tool(mcp_url, "move_file", {
        "workspace_root": params.get("workspace_root", ""),
        "old_path": params.get("old_path", ""),
        "new_path": params.get("new_path", ""),
        "output_format": "json",
    }, raise_on_error=True))


def _call_replace_function_request(params: dict) -> dict:
    """Call replace-function request."""
    mcp_url = ensure_daemon_running()
    return asyncio.run(_mcp_call_tool(mcp_url, "replace_function", {
        "workspace_root": params.get("workspace_root", ""),
        "symbol": params.get("symbol", ""),
        "new_contents": params.get("new_contents", ""),
        "check_signature": params.get("check_signature", True),
        "output_format": "json",
    }))


def format_output(data, output_format: str = "plain") -> str:
    """Format output for tests - with MCP we receive pre-formatted output."""
    return _format_output(data, output_format)


@pytest.fixture(scope="class")
def class_temp_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("integration")


@pytest.fixture(scope="class")
def class_isolated_config(class_temp_dir):
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
