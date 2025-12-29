from pathlib import Path
from urllib.parse import quote, unquote, urlparse


def path_to_uri(path: str | Path) -> str:
    path = Path(path).resolve()
    return "file://" + quote(str(path), safe="/:")


def uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Not a file URI: {uri}")
    return Path(unquote(parsed.path))
