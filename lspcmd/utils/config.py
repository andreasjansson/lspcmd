import os
from pathlib import Path
from typing import Any

import tomli
import tomli_w


def get_cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".cache"
    return base / "lspcmd"


def get_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".config"
    return base / "lspcmd"


def get_config_path() -> Path:
    return get_config_dir() / "config.toml"


def get_socket_path() -> Path:
    return get_cache_dir() / "lspcmd.sock"


def get_pid_path() -> Path:
    return get_cache_dir() / "lspcmd.pid"


def get_log_dir() -> Path:
    return get_cache_dir() / "log"


DEFAULT_CONFIG: dict[str, Any] = {
    "daemon": {
        "log_level": "info",
        "request_timeout": 30,
        "hover_cache_size": 256 * 1024 * 1024,  # 256MB
        "symbol_cache_size": 256 * 1024 * 1024,  # 256MB
    },
    "workspaces": {
        "roots": [],
        "excluded_languages": ["json", "yaml", "html"],
    },
    "formatting": {
        "tab_size": 4,
        "insert_spaces": True,
    },
    "servers": {},
}


def load_config() -> dict[str, Any]:
    config_path = get_config_path()
    config = dict(DEFAULT_CONFIG)

    if config_path.exists():
        with open(config_path, "rb") as f:
            user_config = tomli.load(f)
            _merge_config(config, user_config)

    return config


def save_config(config: dict[str, Any]) -> None:
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "wb") as f:
        tomli_w.dump(config, f)


def _merge_config(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _merge_config(base[key], value)
        else:
            base[key] = value


WORKSPACE_MARKERS = [
    ".git",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "package.json",
    "go.mod",
    "Makefile",
    "CMakeLists.txt",
    ".project",
    "build.gradle",
    "pom.xml",
    "mix.exs",
    "Gemfile",
    "requirements.txt",
]


def detect_workspace_root(path: Path) -> Path | None:
    """Detect workspace root by walking up from path and finding workspace markers.
    
    Returns the deepest (closest to path) directory containing a workspace marker.
    """
    path = path.resolve()
    if path.is_file():
        path = path.parent

    current = path
    while current != current.parent:
        for marker in WORKSPACE_MARKERS:
            if (current / marker).exists():
                return current
        current = current.parent

    return None


def get_known_workspace_root(path: Path, config: dict) -> Path | None:
    """Get the deepest known workspace root that contains path.
    
    If path is in multiple known workspaces (nested), returns the deepest one.
    """
    path = path.resolve()
    roots = config.get("workspaces", {}).get("roots", [])

    best_root = None
    best_depth = -1
    
    for root_str in roots:
        root = Path(root_str).resolve()
        try:
            path.relative_to(root)
            depth = len(root.parts)
            if depth > best_depth:
                best_depth = depth
                best_root = root
        except ValueError:
            continue

    return best_root


def get_best_workspace_root(path: Path, config: dict, cwd: Path | None = None) -> Path | None:
    """Get the best workspace root for a path.
    
    Only returns explicitly initialized workspace roots (from config).
    
    Returns None if no initialized workspace contains the path.
    Use `lspcmd workspace init` to initialize a workspace.
    
    The cwd parameter is ignored (kept for API compatibility).
    """
    path = path.resolve()
    return get_known_workspace_root(path, config)


def add_workspace_root(root: Path, config: dict) -> None:
    roots = config.setdefault("workspaces", {}).setdefault("roots", [])
    root_str = str(root.resolve())
    if root_str not in roots:
        roots.append(root_str)
        save_config(config)


def cleanup_stale_workspace_roots(config: dict) -> list[str]:
    """Remove workspace roots that no longer exist on disk.
    
    Returns list of removed roots.
    """
    roots = config.get("workspaces", {}).get("roots", [])
    if not roots:
        return []
    
    removed = []
    valid_roots = []
    
    for root_str in roots:
        root = Path(root_str)
        if root.exists() and root.is_dir():
            valid_roots.append(root_str)
        else:
            removed.append(root_str)
    
    if removed:
        config.setdefault("workspaces", {})["roots"] = valid_roots
        save_config(config)
    
    return removed
