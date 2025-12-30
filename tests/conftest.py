import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def python_project(temp_dir):
    src = FIXTURES_DIR / "python_project"
    dst = temp_dir / "python_project"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture
def rust_project(temp_dir):
    src = FIXTURES_DIR / "rust_project"
    dst = temp_dir / "rust_project"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture
def typescript_project(temp_dir):
    src = FIXTURES_DIR / "typescript_project"
    dst = temp_dir / "typescript_project"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture
def go_project(temp_dir):
    src = FIXTURES_DIR / "go_project"
    dst = temp_dir / "go_project"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture
def isolated_config(temp_dir, monkeypatch):
    cache_dir = temp_dir / "cache"
    config_dir = temp_dir / "config"
    cache_dir.mkdir()
    config_dir.mkdir()

    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))

    return {"cache": cache_dir, "config": config_dir}


def has_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def require_command(cmd: str, name: str):
    if not has_command(cmd):
        raise RuntimeError(
            f"{name} not installed (command '{cmd}' not found). "
            f"Install it to run this test."
        )


def requires_pyright():
    require_command("pyright-langserver", "pyright")


def requires_rust_analyzer():
    require_command("rust-analyzer", "rust-analyzer")
    require_command("cargo", "cargo")


def requires_typescript_lsp():
    require_command("typescript-language-server", "typescript-language-server")


def requires_gopls():
    require_command("gopls", "gopls")


def requires_jdtls():
    require_command("jdtls", "jdtls")
