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
        root = Path(root_str)
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
    
    If cwd is provided, the workspace root must contain cwd (i.e., we won't
    descend into nested workspaces that are deeper than cwd).
    
    Priority:
    1. Known workspace root containing the path (and cwd if provided)
    2. Detected workspace root (via markers like .git, go.mod, etc.)
    3. None if no workspace found
    """
    path = path.resolve()
    if cwd:
        cwd = cwd.resolve()
    
    detected = detect_workspace_root(path)
    known = get_known_workspace_root(path, config)
    
    # If cwd is provided, filter out roots that don't contain cwd
    if cwd:
        if detected:
            try:
                cwd.relative_to(detected)
            except ValueError:
                detected = None
        if known:
            try:
                cwd.relative_to(known)
            except ValueError:
                known = None
        
        # Also try detecting from cwd if file detection gave a nested workspace
        if not detected and not known:
            detected = detect_workspace_root(cwd)
    
    if detected and known:
        # Prefer the deeper (more specific) workspace
        if len(detected.parts) >= len(known.parts):
            return detected
        return known
    
    return detected or known


def add_workspace_root(root: Path, config: dict) -> None:
    roots = config.setdefault("workspaces", {}).setdefault("roots", [])
    root_str = str(root.resolve())
    if root_str not in roots:
        roots.append(root_str)
        save_config(config)
