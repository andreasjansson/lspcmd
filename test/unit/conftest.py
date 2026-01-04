import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def isolated_config(temp_dir, monkeypatch):
    cache_dir = temp_dir / "cache"
    config_dir = temp_dir / "config"
    cache_dir.mkdir()
    config_dir.mkdir()

    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))

    return {"cache": cache_dir, "config": config_dir}
