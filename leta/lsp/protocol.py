import json
import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class JsonRpcRequest:
    method: str
    params: dict[str, Any] | list[Any] | None
    id: int | str | None = None


@dataclass
class JsonRpcResponse:
    id: int | str | None
    result: Any = None
    error: dict[str, Any] | None = None


@dataclass
class JsonRpcNotification:
    method: str
    params: dict[str, Any] | list[Any] | None = None


class LSPProtocolError(Exception):
    pass


class LSPResponseError(Exception):
    code: int
    message: str
    data: object | None

    def __init__(self, code: int, message: str, data: object | None = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"LSP Error {code}: {message}")

    def is_method_not_found(self) -> bool:
        return (
            self.code == -32601
            or "not found" in self.message.lower()
            or "not yet implemented" in self.message.lower()
        )

    def is_unsupported(self) -> bool:
        msg = self.message.lower()
        return "unsupported" in msg or ("internal error" in msg and self.code == -32603)


class LSPMethodNotSupported(Exception):
    method: str
    server_name: str

    def __init__(self, method: str, server_name: str):
        self.method = method
        self.server_name = server_name
        super().__init__(f"{method} is not supported by {server_name}")


class LanguageServerNotFound(Exception):
    server_name: str
    language: str
    install_cmd: str | None

    def __init__(self, server_name: str, language: str, install_cmd: str | None = None):
        self.server_name = server_name
        self.language = language
        self.install_cmd = install_cmd
        if install_cmd:
            msg = f"Language server '{server_name}' for {language} not found. Install with: {install_cmd}"
        else:
            msg = f"Language server '{server_name}' for {language} not found"
        super().__init__(msg)


KNOWN_ERROR_SOLUTIONS = [
    (
        "Unknown binary 'rust-analyzer' in official toolchain",
        "rust-analyzer is not installed in your Rust toolchain.\n"
        + "Fix: rustup component add rust-analyzer",
    ),
    (
        "could not find `Cargo.toml`",
        "rust-analyzer requires a Cargo.toml file to work.\n"
        + "This directory doesn't appear to be a valid Rust project.",
    ),
    (
        "No such file or directory (os error 2)",
        "The language server binary was not found.\n"
        + "Make sure it's installed and in your PATH.",
    ),
]


def get_known_error_solution(server_log: str | None) -> str | None:
    if not server_log:
        return None
    for pattern, solution in KNOWN_ERROR_SOLUTIONS:
        if pattern in server_log:
            return solution
    return None


class LanguageServerStartupError(Exception):
    server_name: str
    language: str
    workspace_root: str
    original_error: Exception
    server_log: str | None
    log_path: str | None

    def __init__(
        self,
        server_name: str,
        language: str,
        workspace_root: str,
        original_error: Exception,
        server_log: str | None = None,
        log_path: str | None = None,
    ):
        self.server_name = server_name
        self.language = language
        self.workspace_root = workspace_root
        self.original_error = original_error
        self.server_log = server_log
        self.log_path = log_path

        lines = [
            f"Language server '{server_name}' failed to start for {language} files in {workspace_root}",
            "",
            f"Error: {original_error}",
        ]

        known_solution = get_known_error_solution(server_log)
        if known_solution:
            lines.append("")
            lines.append("Solution:")
            for line in known_solution.splitlines():
                lines.append(f"  {line}")

        if server_log and server_log.strip():
            lines.append("")
            lines.append("Server log (last 20 lines):")
            for line in server_log.strip().splitlines()[-20:]:
                lines.append(f"  {line}")

        if log_path:
            lines.append("")
            lines.append(f"Full server log: {log_path}")

        if not known_solution:
            lines.append("")
            lines.append("Possible causes:")
            lines.append(
                f"  - The project may not be a valid {language} project (missing config files)"
            )
            lines.append("  - The language server may have crashed or timed out")
            lines.append(
                f"  - Try running '{server_name}' directly in that directory to see detailed errors"
            )

        lines.append("")
        lines.append(
            "To exclude these files, use: leta grep PATTERN 'your/path/*.ext' -x 'path/to/exclude/*'"
        )

        super().__init__("\n".join(lines))


def encode_message(obj: dict[str, Any]) -> bytes:
    content = json.dumps(obj).encode("utf-8")
    header = f"Content-Length: {len(content)}\r\n\r\n".encode("ascii")
    return header + content


async def read_message(reader: asyncio.StreamReader) -> dict[str, Any]:
    headers: dict[str, str] = {}

    while True:
        line = await reader.readline()
        if not line:
            raise LSPProtocolError("Connection closed")

        line_str = line.decode("ascii").strip()
        if not line_str:
            break

        if ":" in line_str:
            key, value = line_str.split(":", 1)
            headers[key.strip()] = value.strip()

    if "Content-Length" not in headers:
        raise LSPProtocolError("Missing Content-Length header")

    content_length = int(headers["Content-Length"])
    content = await reader.readexactly(content_length)

    return json.loads(content.decode("utf-8"))
