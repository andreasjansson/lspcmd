"""Integration tests for lspcmd.

Tests LSP features using the Unix socket-based daemon.
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
import pytest

from lspcmd.cli import run_request as cli_run_request, ensure_daemon_running
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


def run_request(method: str, params: dict, raise_on_error: bool = False) -> dict:
    """Run a request against the daemon and return the result.
    
    Wraps the CLI run_request to handle click exceptions and return
    a dict with either 'result' or 'error'.
    
    Args:
        method: The daemon method to call
        params: Parameters for the method
        raise_on_error: If True, re-raise click.ClickException instead of returning error dict
    """
    try:
        return cli_run_request(method, params)
    except click.ClickException as e:
        if raise_on_error:
            raise
        return {"error": str(e.message)}


def format_output(data, output_format: str = "plain") -> str:
    """Format output for tests."""
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
