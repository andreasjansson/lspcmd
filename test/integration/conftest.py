"""Integration tests for leta.

Tests LSP features using the Unix socket-based daemon.
Uses pytest-xdist for parallel execution to test concurrent daemon access.

Run with: pytest test/integration/ -v
"""

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import TypeVar

import click
import pytest
from pydantic import BaseModel

from leta.cli import run_request as cli_run_request, ensure_daemon_running
from leta.daemon.rpc import (
    CallsResult,
    DeclarationResult,
    DescribeSessionResult,
    FilesResult,
    GrepResult,
    ImplementationsResult,
    MoveFileResult,
    ReferencesResult,
    RemoveWorkspaceResult,
    RenameResult,
    ResolveSymbolResult,
    RestartWorkspaceResult,
    ShowResult,
    SubtypesResult,
    SupertypesResult,
)
from leta.output.formatters import format_result

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

os.environ["LETA_REQUEST_TIMEOUT"] = "60"

METHOD_TO_RESULT_TYPE: dict[str, type[BaseModel]] = {
    "grep": GrepResult,
    "files": FilesResult,
    "show": ShowResult,
    "declaration": DeclarationResult,
    "references": ReferencesResult,
    "implementations": ImplementationsResult,
    "subtypes": SubtypesResult,
    "supertypes": SupertypesResult,
    "calls": CallsResult,
    "rename": RenameResult,
    "move-file": MoveFileResult,
    "restart-workspace": RestartWorkspaceResult,
    "remove-workspace": RemoveWorkspaceResult,
    "describe-session": DescribeSessionResult,
    "resolve-symbol": ResolveSymbolResult,
}

T = TypeVar("T", bound=BaseModel)


class ErrorResult(BaseModel):
    """Result type for tests that expect errors."""
    error: str


def run_request(method: str, params: dict[str, object], expect_error: bool = False) -> BaseModel:
    """Run a request against the daemon and return a typed result model.

    The result type is inferred from the method name.

    Args:
        method: The daemon method to call
        params: Parameters for the method
        expect_error: If True, return ErrorResult instead of raising on error
    """
    try:
        response = cli_run_request(method, params)
    except click.ClickException as e:
        if expect_error:
            return ErrorResult(error=e.message)
        raise AssertionError(f"Request failed: {e.message}")

    result_type = METHOD_TO_RESULT_TYPE.get(method)
    if result_type is None:
        raise ValueError(f"Unknown method: {method}")

    return result_type.model_validate(response["result"])


def format_output(result: BaseModel, output_format: str = "plain") -> str:
    """Format a result model for display."""
    return format_result(result, output_format)


@pytest.fixture(scope="class")
def class_temp_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("integration")


@pytest.fixture(scope="class")
def class_isolated_config(class_temp_dir):
    cache_dir = Path(tempfile.mkdtemp(prefix="leta_test_"))
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
        cli_run_request("shutdown", {})
    except Exception:
        pass
