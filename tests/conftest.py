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


requires_pyright = pytest.mark.skipif(
    not has_command("pyright-langserver"),
    reason="pyright-langserver not installed"
)

requires_rust_analyzer = pytest.mark.skipif(
    not has_command("rust-analyzer"),
    reason="rust-analyzer not installed"
)

requires_typescript_lsp = pytest.mark.skipif(
    not has_command("typescript-language-server"),
    reason="typescript-language-server not installed"
)

requires_gopls = pytest.mark.skipif(
    not has_command("gopls"),
    reason="gopls not installed"
)
