import asyncio
import fnmatch
import json
import logging
import os
import re
import signal
from pathlib import Path
from typing import Any

from .session import Session, Workspace
from .pidfile import write_pid, remove_pid
from ..cache import LMDBCache
from ..lsp.protocol import LSPResponseError, LSPMethodNotSupported, LanguageServerNotFound
from ..lsp.types import SymbolKind, CodeActionKind
from ..utils.config import get_socket_path, get_pid_path, get_log_dir, get_cache_dir, load_config
from ..utils.uri import path_to_uri, uri_to_path
from ..utils.text import read_file_content, get_lines_around, get_language_id

logger = logging.getLogger(__name__)

DEFAULT_CACHE_SIZE_BYTES = 256 * 1024 * 1024  # 256MB

DEFAULT_EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "target", "build", "dist", ".tox", ".mypy_cache", ".pytest_cache",
    ".eggs", ".cache", ".coverage", ".hypothesis", ".nox", ".ruff_cache",
    "__pypackages__", ".pants.d", ".pyre", ".pytype",
    "vendor", "third_party", ".bundle",
    ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache",
    "coverage", ".nyc_output",
}


class DaemonServer:
    def __init__(self, hover_cache_bytes: int | None = None, symbol_cache_bytes: int | None = None):
        self.session = Session()
        self.server: asyncio.Server | None = None
        self._shutdown_event = asyncio.Event()
        self._hover_cache_bytes = hover_cache_bytes or DEFAULT_CACHE_SIZE_BYTES
        self._symbol_cache_bytes = symbol_cache_bytes or DEFAULT_CACHE_SIZE_BYTES
        
        cache_dir = get_cache_dir()
        self._hover_cache = LMDBCache(
            cache_dir / "hover_cache.lmdb",
            self._hover_cache_bytes,
        )
        self._symbol_cache = LMDBCache(
            cache_dir / "symbol_cache.lmdb",
            self._symbol_cache_bytes,
        )

    async def start(self) -> None:
        self.session.config = load_config()

        socket_path = get_socket_path()
        socket_path.parent.mkdir(parents=True, exist_ok=True)

        if socket_path.exists():
            socket_path.unlink()

        self.server = await asyncio.start_unix_server(self._handle_client, path=str(socket_path))

        pid_path = get_pid_path()
        write_pid(pid_path, os.getpid())

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self._shutdown()))

        logger.info(f"Daemon started, listening on {socket_path}")

        await self._shutdown_event.wait()

    async def _shutdown(self) -> None:
        logger.info("Shutting down daemon")
        await self.session.close_all()

        self._hover_cache.close()
        self._symbol_cache.close()

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        remove_pid(get_pid_path())
        socket_path = get_socket_path()
        if socket_path.exists():
            socket_path.unlink()

        self._shutdown_event.set()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await reader.read()
            if not data:
                return

            request = json.loads(data.decode())
            response = await self._handle_request(request)

            writer.write(json.dumps(response).encode())
            await writer.drain()
        except json.JSONDecodeError as e:
            logger.exception(f"Failed to parse client request: {e}")
            error_response = {"error": f"Internal error: malformed request (got {len(data)} bytes). This is a bug in lspcmd."}
            writer.write(json.dumps(error_response).encode())
            await writer.drain()
        except Exception as e:
            logger.exception(f"Error handling client: {e}")
            error_response = {"error": str(e)}
            writer.write(json.dumps(error_response).encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_request(self, request: dict) -> dict:
        method = request.get("method")
        params = request.get("params", {})

        handlers = {
            "shutdown": self._handle_shutdown,
            "describe-session": self._handle_describe_session,
            "describe": self._handle_hover,
            "definition": self._handle_definition,
            "declaration": self._handle_declaration,
            "implementations": self._handle_implementations,
            "references": self._handle_references,
            "subtypes": self._handle_subtypes,
            "supertypes": self._handle_supertypes,
            "diagnostics": self._handle_diagnostics,
            "workspace-diagnostics": self._handle_workspace_diagnostics,
            "raw-lsp-request": self._handle_raw_lsp_request,
            "format": self._handle_format,
            "organize-imports": self._handle_organize_imports,
            "rename": self._handle_rename,
            "move-file": self._handle_move_file,
            "replace-function": self._handle_replace_function,
            "grep": self._handle_grep,
            "tree": self._handle_tree,
            "restart-workspace": self._handle_restart_workspace,
            "resolve-symbol": self._handle_resolve_symbol,
        }

        handler = handlers.get(method)
        if not handler:
            return {"error": f"Unknown method: {method}"}

        try:
            result = await handler(params)
            return {"result": result}
        except LanguageServerNotFound as e:
            return {"error": str(e)}
        except LSPMethodNotSupported as e:
            return {"error": str(e)}
        except LSPResponseError as e:
            logger.error(f"LSP error in {method}: {e.message} (code={e.code})")
            return {"error": f"LSP error: {e.message}"}
        except Exception as e:
            logger.exception(f"Error in handler {method}")
            return {"error": str(e)}

    async def _get_workspace_and_document(self, params: dict):
        path = Path(params["path"]).resolve()
        workspace_root = Path(params["workspace_root"]).resolve()

        workspace = await self.session.get_or_create_workspace(path, workspace_root)
        doc = await workspace.ensure_document_open(path)

        return workspace, doc, path

    def _parse_position(self, params: dict) -> tuple[int, int]:
        line = params["line"] - 1
        column = params["column"]
        return line, column

    def _relative_path(self, path: Path, workspace_root: Path) -> str:
        try:
            return str(path.resolve().relative_to(workspace_root.resolve()))
        except ValueError:
            return str(path)

    async def _handle_shutdown(self, params: dict) -> dict:
        asyncio.create_task(self._shutdown())
        return {"status": "shutting_down"}

    async def _handle_describe_session(self, params: dict) -> dict:
        result = self.session.to_dict()
        result["daemon_pid"] = os.getpid()
        result["caches"] = {
            "hover_cache": {
                "current_bytes": self._hover_cache.current_bytes,
                "max_bytes": self._hover_cache.max_bytes,
                "entries": len(self._hover_cache),
            },
            "symbol_cache": {
                "current_bytes": self._symbol_cache.current_bytes,
                "max_bytes": self._symbol_cache.max_bytes,
                "entries": len(self._symbol_cache),
            },
        }
        return result

    async def _handle_raw_lsp_request(self, params: dict) -> Any:
        workspace_root = Path(params["workspace_root"]).resolve()
        lsp_method = params["method"]
        lsp_params = params.get("params", {})
        language = params.get("language", "python")

        workspace = await self.session.get_or_create_workspace_for_language(
            language, workspace_root
        )
        if not workspace or not workspace.client:
            raise ValueError(f"No LSP server for language: {language}")

        await workspace.client.wait_for_service_ready()

        return await workspace.client.send_request(lsp_method, lsp_params)

    async def _handle_hover(self, params: dict) -> dict:
        workspace, doc, path = await self._get_workspace_and_document(params)
        line, column = self._parse_position(params)

        result = await workspace.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": doc.uri},
                "position": {"line": line, "character": column},
            },
        )

        if not result:
            return {"contents": None}

        contents = result.get("contents")
        if isinstance(contents, dict):
            return {"contents": contents.get("value", str(contents))}
        elif isinstance(contents, list):
            return {"contents": "\n".join(str(c.get("value", c) if isinstance(c, dict) else c) for c in contents)}
        else:
            return {"contents": str(contents)}

    async def _handle_grep(self, params: dict) -> list[dict] | dict:
        workspace_root = Path(params["workspace_root"]).resolve()
        pattern = params.get("pattern", ".*")
        kinds = params.get("kinds")
        case_sensitive = params.get("case_sensitive", False)
        include_docs = params.get("include_docs", False)
        paths = params.get("paths")
        exclude_patterns = params.get("exclude_patterns", [])

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern '{pattern}': {e}")

        kinds_set = set(k.lower() for k in kinds) if kinds else None

        if paths:
            symbols = await self._collect_symbols_for_paths(
                [Path(p) for p in paths], workspace_root
            )
        else:
            symbols = await self._collect_all_workspace_symbols(workspace_root, "")

        if exclude_patterns:
            def is_excluded(rel_path: str) -> bool:
                path_parts = Path(rel_path).parts
                for pat in exclude_patterns:
                    if fnmatch.fnmatch(rel_path, pat):
                        return True
                    if "/" not in pat and "*" not in pat and "?" not in pat:
                        if pat in path_parts:
                            return True
                    if fnmatch.fnmatch(Path(rel_path).name, pat):
                        return True
                return False

            symbols = [s for s in symbols if not is_excluded(s.get("path", ""))]

        symbols = [s for s in symbols if regex.search(s.get("name", ""))]

        if kinds_set:
            symbols = [s for s in symbols if s.get("kind", "").lower() in kinds_set]

        if include_docs and symbols:
            for sym in symbols:
                sym["documentation"] = await self._get_symbol_documentation(
                    workspace_root, sym["path"], sym["line"], sym.get("column", 0)
                )

        if not symbols and r"\|" in pattern:
            return {
                "warning": f"No results. Note: use '|' for alternation, not '\\|' (e.g., 'foo|bar' not 'foo\\|bar')"
            }

        return symbols

    async def _handle_tree(self, params: dict) -> dict:
        workspace_root = Path(params["workspace_root"]).resolve()
        exclude_patterns = params.get("exclude_patterns", [])

        files = self._find_all_source_files(workspace_root)

        if exclude_patterns:
            def is_excluded(file_path: Path) -> bool:
                rel_path = self._relative_path(file_path, workspace_root)
                path_parts = Path(rel_path).parts
                for pat in exclude_patterns:
                    if fnmatch.fnmatch(rel_path, pat):
                        return True
                    if "/" not in pat and "*" not in pat and "?" not in pat:
                        if pat in path_parts:
                            return True
                    if fnmatch.fnmatch(file_path.name, pat):
                        return True
                return False

            files = [f for f in files if not is_excluded(f)]

        tree_data: dict[str, dict] = {}
        total_bytes = 0
        total_files = 0

        for file_path in sorted(files):
            rel_path = self._relative_path(file_path, workspace_root)
            try:
                size = file_path.stat().st_size
            except Exception:
                size = 0

            tree_data[rel_path] = {"size": size}
            total_bytes += size
            total_files += 1

        return {
            "root": str(workspace_root),
            "files": tree_data,
            "total_files": total_files,
            "total_bytes": total_bytes,
        }

    async def _handle_definition(self, params: dict) -> list[dict] | dict:
        body = params.get("body", False)

        if params.get("direct_location"):
            return await self._handle_direct_definition(params, body)

        if body:
            return await self._handle_definition_body(params)
        return await self._handle_location_request(params, "textDocument/definition")

    async def _handle_direct_definition(self, params: dict, body: bool) -> list[dict] | dict:
        path = Path(params["path"]).resolve()
        workspace_root = Path(params["workspace_root"]).resolve()
        line = params["line"]
        context = params.get("context", 0)
        head = params.get("head", 200)
        symbol_name = params.get("symbol")

        rel_path = self._relative_path(path, workspace_root)
        content = read_file_content(path)
        lines = content.splitlines()

        if body:
            range_start = params.get("range_start_line")
            range_end = params.get("range_end_line")

            if range_start is not None and range_end is not None:
                start = range_start - 1
                end = range_end - 1
            else:
                workspace = await self.session.get_or_create_workspace(path, workspace_root)
                doc = await workspace.ensure_document_open(path)
                result = await workspace.client.send_request(
                    "textDocument/documentSymbol",
                    {"textDocument": {"uri": doc.uri}},
                )
                if result:
                    symbol = self._find_symbol_at_line(result, line - 1)
                    if symbol and "range" in symbol:
                        start = symbol["range"]["start"]["line"]
                        end = symbol["range"]["end"]["line"]
                    else:
                        start = end = line - 1
                else:
                    start = end = line - 1

            if context > 0:
                start = max(0, start - context)
                end = min(len(lines) - 1, end + context)

            total_lines = end - start + 1
            truncated = total_lines > head
            if truncated:
                end = start + head - 1

            return {
                "path": rel_path,
                "start_line": start + 1,
                "end_line": end + 1,
                "content": "\n".join(lines[start : end + 1]),
                "truncated": truncated,
                "total_lines": total_lines,
                "head": head,
                "symbol": symbol_name,
            }
        else:
            location = {
                "path": rel_path,
                "line": line,
                "column": params.get("column", 0),
            }

            if context > 0 and path.exists():
                ctx_lines, start, end = get_lines_around(content, line - 1, context)
                location["context_lines"] = ctx_lines
                location["context_start"] = start + 1

            return [location]

    async def _handle_definition_body(self, params: dict) -> dict:
        locations = await self._handle_location_request(params, "textDocument/definition")
        if not locations:
            return {"error": "Definition not found"}

        loc = locations[0]
        workspace_root = Path(params["workspace_root"]).resolve()
        rel_path = loc["path"]
        file_path = workspace_root / rel_path
        target_line = loc["line"] - 1
        context = params.get("context", 0)
        head = params.get("head", 200)
        symbol_name = params.get("symbol")

        workspace, doc, _ = await self._get_workspace_and_document(
            {
                "path": str(file_path),
                "workspace_root": params["workspace_root"],
            }
        )

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": doc.uri}},
        )

        content = read_file_content(file_path)
        lines = content.splitlines()

        if result:
            symbol = self._find_symbol_at_line(result, target_line)
            if symbol:
                if "range" in symbol:
                    start = symbol["range"]["start"]["line"]
                    end = symbol["range"]["end"]["line"]
                    if context > 0:
                        start = max(0, start - context)
                        end = min(len(lines) - 1, end + context)

                    total_lines = end - start + 1
                    truncated = total_lines > head
                    if truncated:
                        end = start + head - 1

                    return {
                        "path": rel_path,
                        "start_line": start + 1,
                        "end_line": end + 1,
                        "content": "\n".join(lines[start : end + 1]),
                        "truncated": truncated,
                        "total_lines": total_lines,
                        "head": head,
                        "symbol": symbol_name,
                    }
                else:
                    return {"error": "Language server does not provide symbol ranges"}

        return {
            "path": rel_path,
            "start_line": loc["line"],
            "end_line": loc["line"],
            "content": lines[target_line] if target_line < len(lines) else "",
        }

    async def _handle_location_request(self, params: dict, method: str) -> list[dict]:
        workspace, doc, path = await self._get_workspace_and_document(params)
        line, column = self._parse_position(params)
        context = params.get("context", 0)

        try:
            result = await workspace.client.send_request(
                method,
                {
                    "textDocument": {"uri": doc.uri},
                    "position": {"line": line, "character": column},
                },
            )
        except LSPResponseError as e:
            if e.is_method_not_found():
                raise LSPMethodNotSupported(method, workspace.server_config.name)
            raise

        return self._format_locations(result, workspace.root, context)

    def _format_locations(
        self, result: Any, workspace_root: Path, context: int = 0
    ) -> list[dict]:
        if not result:
            return []

        if isinstance(result, dict):
            result = [result]

        locations = []
        for item in result:
            if "targetUri" in item:
                uri = item["targetUri"]
                range_ = item["targetSelectionRange"]
            else:
                uri = item["uri"]
                range_ = item["range"]

            file_path = uri_to_path(uri)
            start_line = range_["start"]["line"]

            location = {
                "path": self._relative_path(file_path, workspace_root),
                "line": start_line + 1,
                "column": range_["start"]["character"],
            }

            if context > 0 and file_path.exists():
                content = read_file_content(file_path)
                lines, start, end = get_lines_around(content, start_line, context)
                location["context_lines"] = lines
                location["context_start"] = start + 1

            locations.append(location)

        return locations

    async def _handle_declaration(self, params: dict) -> list[dict]:
        return await self._handle_location_request(params, "textDocument/declaration")

    async def _handle_implementations(self, params: dict) -> list[dict]:
        workspace, _, _ = await self._get_workspace_and_document(params)
        caps = workspace.client.capabilities
        if not caps.get("implementationProvider"):
            server_name = workspace.server_config.name
            return [
                {
                    "error": f"Server '{server_name}' does not support implementations (may require a license)"
                }
            ]
        return await self._handle_location_request(params, "textDocument/implementation")

    async def _handle_subtypes(self, params: dict) -> list[dict]:
        return await self._handle_type_hierarchy_request(params, "typeHierarchy/subtypes")

    async def _handle_supertypes(self, params: dict) -> list[dict]:
        return await self._handle_type_hierarchy_request(params, "typeHierarchy/supertypes")

    async def _handle_type_hierarchy_request(
        self, params: dict, method: str
    ) -> list[dict]:
        workspace, doc, path = await self._get_workspace_and_document(params)
        line, column = self._parse_position(params)
        context = params.get("context", 0)

        await workspace.client.wait_for_service_ready()

        try:
            prepare_result = await workspace.client.send_request(
                "textDocument/prepareTypeHierarchy",
                {
                    "textDocument": {"uri": doc.uri},
                    "position": {"line": line, "character": column},
                },
            )
        except LSPResponseError as e:
            if e.is_method_not_found():
                raise LSPMethodNotSupported(
                    "textDocument/prepareTypeHierarchy", workspace.server_config.name
                )
            raise

        if not prepare_result:
            return []

        item = prepare_result[0]

        try:
            result = await workspace.client.send_request(method, {"item": item})
        except LSPResponseError as e:
            if e.is_method_not_found():
                raise LSPMethodNotSupported(method, workspace.server_config.name)
            raise

        return self._format_type_hierarchy_items(result, workspace.root, context)

    def _format_type_hierarchy_items(
        self, result: Any, workspace_root: Path, context: int = 0
    ) -> list[dict]:
        if not result:
            return []

        locations = []
        for item in result:
            uri = item["uri"]
            range_ = item.get("selectionRange", item.get("range"))

            file_path = uri_to_path(uri)
            start_line = range_["start"]["line"]

            location = {
                "path": self._relative_path(file_path, workspace_root),
                "line": start_line + 1,
                "column": range_["start"]["character"],
                "name": item.get("name"),
                "kind": SymbolKind(item.get("kind", 0)).name if item.get("kind") else None,
                "detail": item.get("detail"),
            }

            if context > 0 and file_path.exists():
                content = read_file_content(file_path)
                lines, start, end = get_lines_around(content, start_line, context)
                location["context_lines"] = lines
                location["context_start"] = start + 1

            locations.append(location)

        return locations

    async def _handle_references(self, params: dict) -> list[dict]:
        workspace, doc, path = await self._get_workspace_and_document(params)
        line, column = self._parse_position(params)

        result = await workspace.client.send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": doc.uri},
                "position": {"line": line, "character": column},
                "context": {"includeDeclaration": True},
            },
        )

        return self._format_locations(result, workspace.root, params.get("context", 0))

    async def _handle_diagnostics(self, params: dict) -> list[dict]:
        workspace, doc, path = await self._get_workspace_and_document(params)

        await workspace.client.wait_for_service_ready()

        just_discovered_no_pull = False
        if workspace.client.supports_pull_diagnostics:
            try:
                result = await workspace.client.send_request(
                    "textDocument/diagnostic",
                    {"textDocument": {"uri": doc.uri}},
                )
                if result and result.get("items"):
                    return self._format_diagnostics(result["items"], path, workspace.root)
            except LSPResponseError as e:
                if e.is_method_not_found() or e.is_unsupported():
                    workspace.client.supports_pull_diagnostics = False
                    just_discovered_no_pull = True
                else:
                    raise

        wait_time = 2.0 if just_discovered_no_pull else 1.0
        await asyncio.sleep(wait_time)
        stored = workspace.client.get_stored_diagnostics(doc.uri)
        if stored:
            return self._format_diagnostics(stored, path, workspace.root)

        return []

    def _format_diagnostics(
        self, items: list, path: Path, workspace_root: Path
    ) -> list[dict]:
        severity_names = {1: "error", 2: "warning", 3: "info", 4: "hint"}
        rel_path = self._relative_path(path, workspace_root)

        diagnostics = []
        for item in items:
            range_ = item["range"]
            diag = {
                "path": rel_path,
                "line": range_["start"]["line"] + 1,
                "column": range_["start"]["character"],
                "end_line": range_["end"]["line"] + 1,
                "end_column": range_["end"]["character"],
                "message": item["message"],
                "severity": severity_names.get(item.get("severity", 1), "error"),
                "code": item.get("code"),
                "source": item.get("source"),
            }
            diagnostics.append(diag)

        return diagnostics

    async def _handle_workspace_diagnostics(self, params: dict) -> list[dict]:
        workspace_root = Path(params["workspace_root"]).resolve()

        all_diagnostics = []

        all_files = list(self._find_all_source_files(workspace_root))
        if not all_files:
            return []

        files_by_language: dict[str, list[Path]] = {}
        for file_path in all_files:
            lang = get_language_id(file_path)
            if lang:
                files_by_language.setdefault(lang, []).append(file_path)

        for lang, files in files_by_language.items():
            try:
                workspace = await self.session.get_or_create_workspace(
                    files[0], workspace_root
                )
            except ValueError:
                continue

            if not workspace.client:
                continue

            await workspace.client.wait_for_service_ready()

            use_pull = workspace.client.supports_pull_diagnostics

            if use_pull:
                first_file = files[0]
                doc = await workspace.ensure_document_open(first_file)
                try:
                    result = await workspace.client.send_request(
                        "textDocument/diagnostic",
                        {"textDocument": {"uri": doc.uri}},
                        timeout=2.0,
                    )
                    if result and result.get("items"):
                        all_diagnostics.extend(
                            self._format_diagnostics(
                                result["items"], first_file, workspace_root
                            )
                        )
                except (LSPResponseError, asyncio.TimeoutError) as e:
                    if isinstance(e, LSPResponseError) and not (
                        e.is_method_not_found() or e.is_unsupported()
                    ):
                        raise
                    workspace.client.supports_pull_diagnostics = False
                    use_pull = False
                finally:
                    await workspace.close_document(first_file)

                if use_pull:
                    for file_path in files[1:]:
                        doc = await workspace.ensure_document_open(file_path)
                        try:
                            result = await workspace.client.send_request(
                                "textDocument/diagnostic",
                                {"textDocument": {"uri": doc.uri}},
                            )
                            if result and result.get("items"):
                                all_diagnostics.extend(
                                    self._format_diagnostics(
                                        result["items"], file_path, workspace_root
                                    )
                                )
                        except LSPResponseError:
                            pass
                        finally:
                            await workspace.close_document(file_path)

            if not use_pull:
                opened_files = []
                for file_path in files:
                    doc = await workspace.ensure_document_open(file_path)
                    opened_files.append((file_path, doc))

                await asyncio.sleep(1.0)

                for file_path, doc in opened_files:
                    stored = workspace.client.get_stored_diagnostics(doc.uri)
                    if stored:
                        all_diagnostics.extend(
                            self._format_diagnostics(stored, file_path, workspace_root)
                        )
                    await workspace.close_document(file_path)

        all_diagnostics.sort(key=lambda d: (d["path"], d["line"], d["column"]))
        return all_diagnostics

    def _find_all_source_files(self, workspace_root: Path) -> list[Path]:
        source_extensions = {
            ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs",
            ".java", ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".rb",
            ".ex", ".exs", ".hs", ".ml", ".mli", ".lua", ".zig", ".php",
        }
        exclude_dirs = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            "target", "build", "dist", ".tox", ".mypy_cache", ".pytest_cache",
            ".eggs", "*.egg-info",
        }

        files = []
        for root, dirs, filenames in os.walk(workspace_root):
            dirs[:] = [
                d for d in dirs
                if d not in exclude_dirs and not d.endswith(".egg-info")
            ]

            for filename in filenames:
                if Path(filename).suffix in source_extensions:
                    files.append(Path(root) / filename)

        return files

    async def _handle_move_file(self, params: dict) -> dict:
        old_path = Path(params["old_path"]).resolve()
        new_path = Path(params["new_path"]).resolve()
        workspace_root = Path(params["workspace_root"]).resolve()

        if not old_path.exists():
            raise ValueError(f"Source file does not exist: {old_path}")

        if new_path.exists():
            raise ValueError(f"Destination already exists: {new_path}")

        workspace = await self.session.get_or_create_workspace(old_path, workspace_root)
        if not workspace or not workspace.client:
            raise ValueError(f"No language server available for {old_path.suffix} files")

        await workspace.client.wait_for_service_ready()

        server_name = workspace.server_config.name
        supports_will_rename = workspace.client.capabilities.get("workspace", {}).get(
            "fileOperations", {}
        ).get("willRename")

        if not supports_will_rename:
            raise ValueError(f"move-file is not supported by {server_name}")

        opened_for_indexing = []
        if old_path.suffix == ".py":
            python_files = self._find_all_source_files(workspace_root)
            python_files = [
                f for f in python_files if f.suffix == ".py" and f != old_path
            ]
            for file_path in python_files:
                if str(file_path) not in workspace.open_documents:
                    await workspace.ensure_document_open(file_path)
                    opened_for_indexing.append(file_path)
            if opened_for_indexing:
                await asyncio.sleep(0.5)

        old_uri = path_to_uri(old_path)
        new_uri = path_to_uri(new_path)

        try:
            workspace_edit = await workspace.client.send_request(
                "workspace/willRenameFiles",
                {"files": [{"oldUri": old_uri, "newUri": new_uri}]},
            )

        except LSPResponseError as e:
            if e.is_method_not_found():
                raise ValueError(f"move-file is not supported by {server_name}")
            raise
        finally:
            for file_path in opened_for_indexing:
                await workspace.close_document(file_path)

        files_modified = []
        imports_updated = False
        file_already_moved = False

        if workspace_edit:
            additional_files, file_already_moved = await self._apply_workspace_edit_for_move(
                workspace_edit, workspace_root, old_path, new_path
            )
            files_modified.extend(additional_files)
            imports_updated = (
                len([f for f in additional_files if f != self._relative_path(new_path, workspace_root)]) > 0
            )

        if not file_already_moved:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            files_modified.append(self._relative_path(new_path, workspace_root))

        return {
            "moved": True,
            "imports_updated": imports_updated,
            "files_modified": list(dict.fromkeys(files_modified)),
        }

    async def _apply_workspace_edit_for_move(
        self, edit: dict, workspace_root: Path, move_old_path: Path, move_new_path: Path
    ) -> tuple[list[str], bool]:
        files_modified = []
        file_moved = False

        if edit.get("changes"):
            for uri, text_edits in edit["changes"].items():
                file_path = uri_to_path(uri)
                await self._apply_text_edits(file_path, text_edits)
                files_modified.append(self._relative_path(file_path, workspace_root))

        if edit.get("documentChanges"):
            for change in edit["documentChanges"]:
                kind = change.get("kind")
                if kind == "create":
                    file_path = uri_to_path(change["uri"])
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.touch()
                    files_modified.append(self._relative_path(file_path, workspace_root))
                elif kind == "rename":
                    old_path = uri_to_path(change["oldUri"])
                    new_path = uri_to_path(change["newUri"])
                    if old_path == move_old_path and new_path == move_new_path:
                        file_moved = True
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    old_path.rename(new_path)
                    files_modified.append(self._relative_path(new_path, workspace_root))
                elif kind == "delete":
                    file_path = uri_to_path(change["uri"])
                    file_path.unlink(missing_ok=True)
                    files_modified.append(self._relative_path(file_path, workspace_root))
                elif "textDocument" in change:
                    file_path = uri_to_path(change["textDocument"]["uri"])
                    await self._apply_text_edits(file_path, change["edits"])
                    files_modified.append(self._relative_path(file_path, workspace_root))

        return files_modified, file_moved

    async def _apply_text_edits(self, file_path: Path, edits: list[dict]) -> None:
        content = read_file_content(file_path)
        lines = content.splitlines(keepends=True)

        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"

        sorted_edits = sorted(
            edits,
            key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]),
            reverse=True,
        )

        for edit in sorted_edits:
            start = edit["range"]["start"]
            end = edit["range"]["end"]
            new_text = edit["newText"]

            start_line = start["line"]
            start_char = start["character"]
            end_line = end["line"]
            end_char = end["character"]

            if start_line >= len(lines):
                lines.extend([""] * (start_line - len(lines) + 1))

            if start_line == end_line:
                line = lines[start_line] if start_line < len(lines) else ""
                lines[start_line] = line[:start_char] + new_text + line[end_char:]
            else:
                first_line = lines[start_line][:start_char] if start_line < len(lines) else ""
                last_line = lines[end_line][end_char:] if end_line < len(lines) else ""
                lines[start_line : end_line + 1] = [first_line + new_text + last_line]

        result = "".join(lines)
        if result.endswith("\n\n") and not content.endswith("\n\n"):
            result = result[:-1]

        file_path.write_text(result)

    async def _handle_format(self, params: dict) -> dict:
        workspace, doc, path = await self._get_workspace_and_document(params)
        config = self.session.config.get("formatting", {})

        result = await workspace.client.send_request(
            "textDocument/formatting",
            {
                "textDocument": {"uri": doc.uri},
                "options": {
                    "tabSize": config.get("tab_size", 4),
                    "insertSpaces": config.get("insert_spaces", True),
                },
            },
        )

        if result:
            await self._apply_text_edits(path, result)
            return {"formatted": True, "edits_applied": len(result)}

        return {"formatted": False}

    async def _handle_organize_imports(self, params: dict) -> dict:
        workspace, doc, path = await self._get_workspace_and_document(params)

        result = await workspace.client.send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": doc.uri},
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 0},
                },
                "context": {
                    "diagnostics": [],
                    "only": [CodeActionKind.SourceOrganizeImports],
                },
            },
        )

        if not result:
            return {"organized": False, "error": "No organize imports action available"}

        action = result[0]

        if action.get("edit"):
            await self._apply_workspace_edit(action["edit"], workspace.root)
            return {"organized": True}

        if action.get("command"):
            cmd = action["command"]
            await workspace.client.send_request(
                "workspace/executeCommand",
                {"command": cmd["command"], "arguments": cmd.get("arguments", [])},
            )
            return {"organized": True}

        return {"organized": False}

    async def _apply_workspace_edit(self, edit: dict, workspace_root: Path) -> list[str]:
        files_modified = []

        if edit.get("changes"):
            for uri, text_edits in edit["changes"].items():
                file_path = uri_to_path(uri)
                await self._apply_text_edits(file_path, text_edits)
                files_modified.append(self._relative_path(file_path, workspace_root))

        if edit.get("documentChanges"):
            for change in edit["documentChanges"]:
                kind = change.get("kind")
                if kind == "create":
                    file_path = uri_to_path(change["uri"])
                    file_path.touch()
                    files_modified.append(self._relative_path(file_path, workspace_root))
                elif kind == "rename":
                    old_path = uri_to_path(change["oldUri"])
                    new_path = uri_to_path(change["newUri"])
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    old_path.rename(new_path)
                    files_modified.append(self._relative_path(new_path, workspace_root))
                elif kind == "delete":
                    file_path = uri_to_path(change["uri"])
                    file_path.unlink(missing_ok=True)
                    files_modified.append(self._relative_path(file_path, workspace_root))
                elif "textDocument" in change:
                    file_path = uri_to_path(change["textDocument"]["uri"])
                    await self._apply_text_edits(file_path, change["edits"])
                    files_modified.append(self._relative_path(file_path, workspace_root))

        return files_modified

    async def _handle_rename(self, params: dict) -> dict:
        workspace, doc, path = await self._get_workspace_and_document(params)
        line, column = self._parse_position(params)
        new_name = params["new_name"]

        result = await workspace.client.send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": doc.uri},
                "position": {"line": line, "character": column},
                "newName": new_name,
            },
        )

        if not result:
            return {"renamed": False, "error": "Rename not supported or failed"}

        files_modified = await self._apply_workspace_edit(result, workspace.root)
        return {"renamed": True, "files_modified": files_modified}

    async def _handle_replace_function(self, params: dict) -> dict:
        workspace_root = Path(params["workspace_root"]).resolve()
        symbol = params["symbol"]
        new_contents = params["new_contents"]
        check_signature = params.get("check_signature", True)

        resolved = await self._handle_resolve_symbol({
            "workspace_root": str(workspace_root),
            "symbol_path": symbol,
        })
        if "error" in resolved:
            return resolved

        kind = resolved.get("kind")
        if kind not in ("Function", "Method"):
            return {"error": f"Symbol '{symbol}' is a {kind}, not a Function or Method"}

        file_path = Path(resolved["path"]).resolve()
        line = resolved["line"]
        column = resolved.get("column", 0)
        range_start = resolved.get("range_start_line")
        range_end = resolved.get("range_end_line")

        if range_start is None or range_end is None:
            return {"error": "Language server does not provide symbol ranges"}

        workspace = await self.session.get_or_create_workspace(file_path, workspace_root)
        await workspace.ensure_document_open(file_path)

        old_signature = await self._extract_function_signature(
            workspace, file_path, line, column
        )

        original_content = read_file_content(file_path)
        backup_path = file_path.with_suffix(file_path.suffix + ".lspcmd.bkup")

        try:
            backup_path.write_text(original_content)

            new_content, new_line_count = self._apply_function_replacement(
                original_content, new_contents, range_start, range_end
            )

            file_path.write_text(new_content)

            doc = workspace.open_documents.get(path_to_uri(file_path))
            if doc:
                doc.version += 1
                doc.content = new_content
                await workspace.client.send_notification(
                    "textDocument/didChange",
                    {
                        "textDocument": {"uri": doc.uri, "version": doc.version},
                        "contentChanges": [{"text": new_content}],
                    },
                )

            if check_signature:
                await asyncio.sleep(0.2)

                new_signature = await self._extract_function_signature(
                    workspace, file_path, range_start, column
                )

                should_revert = False
                error_result = None

                if new_signature is None:
                    should_revert = True
                    error_result = {
                        "error": "Could not extract signature from new content - the content may be invalid",
                        "hint": "Use --no-check-signature to replace anyway",
                    }
                elif old_signature and not self._signatures_match(old_signature, new_signature):
                    should_revert = True
                    error_result = {
                        "error": "Signature mismatch",
                        "old_signature": old_signature,
                        "new_signature": new_signature,
                        "hint": "Use --no-check-signature to replace anyway",
                    }

                if should_revert:
                    file_path.write_text(original_content)
                    backup_path.unlink(missing_ok=True)
                    if doc:
                        doc.version += 1
                        doc.content = original_content
                        await workspace.client.send_notification(
                            "textDocument/didChange",
                            {
                                "textDocument": {"uri": doc.uri, "version": doc.version},
                                "contentChanges": [{"text": original_content}],
                            },
                        )
                    return error_result

            backup_path.unlink(missing_ok=True)

            rel_path = self._relative_path(file_path, workspace_root)
            return {
                "replaced": True,
                "path": rel_path,
                "old_range": f"{range_start}-{range_end}",
                "new_range": f"{range_start}-{range_start + new_line_count - 1}",
            }

        except Exception as e:
            if backup_path.exists():
                file_path.write_text(backup_path.read_text())
                backup_path.unlink()
            raise

    def _apply_function_replacement(
        self, original_content: str, new_contents: str, range_start: int, range_end: int
    ) -> tuple[str, int]:
        lines = original_content.splitlines(keepends=True)
        start_line_idx = range_start - 1
        end_line_idx = range_end - 1

        if start_line_idx >= 0 and start_line_idx < len(lines):
            original_line = lines[start_line_idx]
            leading_ws = len(original_line) - len(original_line.lstrip())
            indentation = original_line[:leading_ws]
        else:
            indentation = ""

        new_lines = new_contents.splitlines(keepends=True)
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"

        if new_lines:
            first_line = new_lines[0]
            first_line_ws = len(first_line) - len(first_line.lstrip())

            reindented = []
            for line in new_lines:
                if line.strip() == "":
                    reindented.append(line)
                elif len(line) >= first_line_ws and line[:first_line_ws].strip() == "":
                    reindented.append(indentation + line[first_line_ws:])
                else:
                    reindented.append(indentation + line.lstrip())
            new_lines = reindented

        result_lines = lines[:start_line_idx] + new_lines + lines[end_line_idx + 1:]
        return "".join(result_lines), len(new_lines)

    async def _extract_function_signature(
        self, workspace, file_path: Path, line: int, column: int
    ) -> str | None:
        doc = await workspace.ensure_document_open(file_path)

        symbols_result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": doc.uri}},
        )
        if symbols_result:
            symbol = self._find_symbol_at_line(symbols_result, line - 1)
            if symbol and symbol.get("detail"):
                return self._format_signature_from_detail(symbol)

        hover_result = await workspace.client.send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": doc.uri},
                "position": {"line": line - 1, "character": column},
            },
        )
        if not hover_result:
            return None
        return self._parse_signature_from_hover(hover_result)

    def _format_signature_from_detail(self, symbol: dict) -> str:
        name = symbol.get("name", "")
        detail = symbol.get("detail", "")
        if detail.startswith("func"):
            return f"func {name}{detail[4:]}"
        elif detail.startswith("fn"):
            return f"fn {name}{detail[2:]}"
        return f"{name} {detail}"

    def _parse_signature_from_hover(self, hover_result: dict) -> str | None:
        contents = hover_result.get("contents")
        if not contents:
            return None

        if isinstance(contents, dict):
            value = contents.get("value", "")
        elif isinstance(contents, list):
            value = "\n".join(
                c.get("value", str(c)) if isinstance(c, dict) else str(c)
                for c in contents
            )
        else:
            value = str(contents)

        code_match = re.search(r"```\w*\n(.+?)```", value, re.DOTALL)
        if code_match:
            code_block = code_match.group(1).strip()
            return self._extract_full_signature(code_block)

        return self._extract_full_signature(value.strip())

    def _extract_full_signature(self, code_block: str) -> str | None:
        lines = code_block.split("\n")
        if not lines:
            return None

        signature_parts = []
        paren_depth = 0
        bracket_depth = 0
        found_start = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if not found_start:
                if any(kw in stripped for kw in ["def ", "func ", "fn ", "function ", "(function)", "(method)"]):
                    found_start = True
                elif stripped.startswith("class ") or stripped.startswith("type "):
                    return stripped
                else:
                    continue

            for char in stripped:
                if char == '(':
                    paren_depth += 1
                elif char == ')':
                    paren_depth -= 1
                elif char == '[':
                    bracket_depth += 1
                elif char == ']':
                    bracket_depth -= 1

            signature_parts.append(stripped)

            if paren_depth == 0 and bracket_depth == 0:
                full_sig = " ".join(signature_parts)
                colon_idx = full_sig.rfind(":")
                brace_idx = full_sig.rfind("{")
                if brace_idx > 0 and (colon_idx < 0 or brace_idx < colon_idx):
                    full_sig = full_sig[:brace_idx].strip()
                elif colon_idx > 0:
                    pass
                return full_sig

        return " ".join(signature_parts) if signature_parts else lines[0].strip()

    def _signatures_match(self, old_sig: str, new_sig: str) -> bool:
        old_normalized = self._normalize_signature(old_sig)
        new_normalized = self._normalize_signature(new_sig)

        if old_normalized == new_normalized:
            return True

        old_params = self._extract_params_only(old_normalized)
        new_params = self._extract_params_only(new_normalized)
        return old_params == new_params

    def _extract_params_only(self, sig: str) -> str:
        match = re.match(r"^((?:def|func|fn|function)\s+\w+\s*\([^)]*\))", sig)
        if match:
            return match.group(1)
        return sig

    def _normalize_signature(self, sig: str) -> str:
        sig = re.sub(r"^\(function\)\s*", "", sig)
        sig = re.sub(r"^\(method\)\s*", "", sig)
        sig = re.sub(r"^function\s+", "", sig)
        sig = re.sub(r"^func\s+", "func ", sig)
        sig = re.sub(r"^def\s+", "def ", sig)
        sig = re.sub(r"^fn\s+", "fn ", sig)

        sig = re.sub(r"\bself:\s*Self@\w+", "self", sig)
        sig = re.sub(r"\bself:\s*Unknown", "self", sig)
        sig = re.sub(r"\bcls:\s*type\[Self@\w+\]", "cls", sig)
        sig = re.sub(r"\bcls:\s*Unknown", "cls", sig)

        sig = re.sub(r"\s*\(\+\d+\s*overload[s]?\)", "", sig)

        sig = re.sub(r"\s*,\s*", ", ", sig)
        sig = re.sub(r"\(\s+", "(", sig)
        sig = re.sub(r"\s+\)", ")", sig)
        sig = re.sub(r"\[\s+", "[", sig)
        sig = re.sub(r"\s+\]", "]", sig)
        sig = re.sub(r"\s*:\s*", ": ", sig)
        sig = re.sub(r"\s*->\s*", " -> ", sig)
        sig = re.sub(r"\s+", " ", sig)
        sig = sig.strip()
        return sig

    async def _handle_restart_workspace(self, params: dict) -> dict:
        workspace_root = Path(params["workspace_root"]).resolve()
        servers = self.session.workspaces.get(workspace_root, {})

        if servers:
            restarted = []
            for server_name, workspace in list(servers.items()):
                if workspace.client is not None:
                    await workspace.stop_server()
                await workspace.start_server()
                restarted.append(server_name)
            return {"restarted": True, "servers": restarted}

        languages = self._discover_languages(workspace_root)
        if not languages:
            return {"error": f"No supported source files found in {workspace_root}"}

        started = []
        for lang_id in languages:
            workspace = await self.session.get_or_create_workspace_for_language(
                lang_id, workspace_root
            )
            if workspace and workspace.client:
                started.append(workspace.server_config.name)

        return {"restarted": True, "servers": started}

    def _discover_languages(self, workspace_root: Path) -> list[str]:
        from ..servers.registry import get_server_for_language

        skip_dirs = {
            "node_modules", "__pycache__", ".git", "venv", ".venv",
            "build", "dist", ".tox", ".eggs",
        }
        excluded_languages = set(
            self.session.config.get("workspaces", {}).get("excluded_languages", [])
        )
        languages = set()

        for file_path in workspace_root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(
                part.startswith(".") or part in skip_dirs or part.endswith(".egg-info")
                for part in file_path.parts
            ):
                continue

            lang_id = get_language_id(file_path)
            if lang_id == "plaintext" or lang_id in excluded_languages:
                continue

            server_config = get_server_for_language(lang_id, self.session.config)
            if server_config:
                languages.add(lang_id)

        return list(languages)

    async def _handle_resolve_symbol(self, params: dict) -> dict:
        workspace_root = Path(params["workspace_root"]).resolve()
        symbol_path = params["symbol_path"]

        path_filter = None
        line_filter = None

        colon_count = symbol_path.count(":")
        if colon_count == 2:
            path_filter, line_str, symbol_path = symbol_path.split(":", 2)
            try:
                line_filter = int(line_str)
            except ValueError:
                return {"error": f"Invalid line number: '{line_str}'"}
        elif colon_count == 1:
            path_filter, symbol_path = symbol_path.split(":", 1)

        parts = symbol_path.split(".")

        all_symbols = await self._collect_all_workspace_symbols(workspace_root, "")

        if path_filter:
            def matches_path(rel_path: str) -> bool:
                if fnmatch.fnmatch(rel_path, path_filter):
                    return True
                if fnmatch.fnmatch(rel_path, f"**/{path_filter}"):
                    return True
                if fnmatch.fnmatch(rel_path, f"{path_filter}/**"):
                    return True
                if "/" not in path_filter:
                    if fnmatch.fnmatch(Path(rel_path).name, path_filter):
                        return True
                    if path_filter in Path(rel_path).parts:
                        return True
                return False

            all_symbols = [s for s in all_symbols if matches_path(s.get("path", ""))]

        if line_filter is not None:
            all_symbols = [s for s in all_symbols if s.get("line") == line_filter]

        target_name = parts[-1]

        def name_matches(sym_name: str, target: str) -> bool:
            if sym_name == target:
                return True
            if self._normalize_symbol_name(sym_name) == target:
                return True
            return False

        if len(parts) == 1:
            matches = []
            for s in all_symbols:
                sym_name = s.get("name", "")
                if name_matches(sym_name, target_name):
                    matches.append(s)
                elif sym_name.endswith(f").{target_name}"):
                    matches.append(s)
        else:
            container_parts = parts[:-1]
            matches = []
            container_str = ".".join(container_parts)

            for sym in all_symbols:
                sym_name = sym.get("name", "")

                go_style_name = f"(*{container_str}).{target_name}"
                go_style_name_val = f"({container_str}).{target_name}"
                if sym_name == go_style_name or sym_name == go_style_name_val:
                    matches.append(sym)
                    continue

                if not name_matches(sym_name, target_name):
                    continue

                sym_container = sym.get("container", "") or ""
                sym_container_normalized = self._normalize_container(sym_container)
                sym_path = sym.get("path", "")
                module_name = self._get_module_name(sym_path)

                full_container = (
                    f"{module_name}.{sym_container_normalized}"
                    if sym_container_normalized
                    else module_name
                )

                if sym_container_normalized == container_str:
                    matches.append(sym)
                elif sym_container == container_str:
                    matches.append(sym)
                elif full_container == container_str:
                    matches.append(sym)
                elif full_container.endswith(f".{container_str}"):
                    matches.append(sym)
                elif len(container_parts) == 1 and container_parts[0] == module_name:
                    matches.append(sym)

        if not matches:
            error_parts = []
            if path_filter:
                error_parts.append(f"in files matching '{path_filter}'")
            if line_filter is not None:
                error_parts.append(f"on line {line_filter}")
            suffix = " " + " ".join(error_parts) if error_parts else ""
            return {"error": f"Symbol '{symbol_path}' not found{suffix}"}

        preferred_kinds = {
            "Class", "Struct", "Interface", "Enum", "Module", "Namespace", "Package",
        }
        type_matches = [m for m in matches if m.get("kind") in preferred_kinds]
        if len(type_matches) == 1 and len(matches) > 1:
            matches = type_matches

        if len(matches) == 1:
            sym = matches[0]
            return {
                "path": str(workspace_root / sym["path"]),
                "line": sym["line"],
                "column": sym.get("column", 0),
                "name": sym["name"],
                "kind": sym.get("kind"),
                "container": sym.get("container"),
                "range_start_line": sym.get("range_start_line"),
                "range_end_line": sym.get("range_end_line"),
            }

        matches_info = []
        for sym in matches[:10]:
            ref = self._generate_unambiguous_ref(sym, matches, target_name)
            info = {
                "path": sym["path"],
                "line": sym["line"],
                "name": sym["name"],
                "kind": sym.get("kind"),
                "container": sym.get("container"),
                "detail": sym.get("detail"),
                "ref": ref,
            }
            matches_info.append(info)

        return {
            "error": f"Symbol '{symbol_path}' is ambiguous ({len(matches)} matches)",
            "matches": matches_info,
            "total_matches": len(matches),
        }

    def _normalize_symbol_name(self, name: str) -> str:
        match = re.match(r"^(\w+)\([^)]*\)$", name)
        if match:
            return match.group(1)
        match = re.match(r"^\(\*?\w+\)\.(\w+)$", name)
        if match:
            return match.group(1)
        return name

    def _get_effective_container(self, sym: dict) -> str:
        container = sym.get("container", "") or ""
        if container:
            return self._normalize_container(container)

        sym_name = sym.get("name", "")
        match = re.match(r"^\(\*?(\w+)\)\.", sym_name)
        if match:
            return match.group(1)

        return ""

    def _generate_unambiguous_ref(
        self, sym: dict, all_matches: list[dict], target_name: str
    ) -> str:
        sym_path = sym.get("path", "")
        sym_line = sym.get("line", 0)
        sym_container = self._get_effective_container(sym)
        filename = Path(sym_path).name
        normalized_name = self._normalize_symbol_name(target_name)

        if sym_container:
            ref = f"{sym_container}.{normalized_name}"
            if self._ref_resolves_uniquely(ref, sym, all_matches):
                return ref

        ref = f"{filename}:{normalized_name}"
        if self._ref_resolves_uniquely(ref, sym, all_matches):
            return ref

        if sym_container:
            ref = f"{filename}:{sym_container}.{normalized_name}"
            if self._ref_resolves_uniquely(ref, sym, all_matches):
                return ref

        return f"{filename}:{sym_line}:{normalized_name}"

    def _ref_resolves_uniquely(
        self, ref: str, target_sym: dict, all_matches: list[dict]
    ) -> bool:
        path_filter = None
        symbol_path = ref

        colon_count = ref.count(":")
        if colon_count >= 1:
            parts = ref.split(":")
            if colon_count == 1:
                path_filter, symbol_path = parts[0], parts[1]
            elif colon_count == 2:
                path_filter = parts[0]
                try:
                    line_filter = int(parts[1])
                    matching = [
                        s for s in all_matches
                        if Path(s.get("path", "")).name == path_filter
                        and s.get("line") == line_filter
                    ]
                    return len(matching) == 1 and matching[0] is target_sym
                except ValueError:
                    symbol_path = f"{parts[1]}:{parts[2]}" if len(parts) > 2 else parts[1]

        if path_filter:
            candidates = [
                s for s in all_matches
                if Path(s.get("path", "")).name == path_filter
            ]
        else:
            candidates = all_matches

        sym_parts = symbol_path.split(".")
        if len(sym_parts) == 1:
            matching = [s for s in candidates if self._normalize_symbol_name(s.get("name", "")) == sym_parts[0]]
        else:
            container_str = ".".join(sym_parts[:-1])
            target_name = sym_parts[-1]
            matching = []

            for s in candidates:
                if self._normalize_symbol_name(s.get("name", "")) != target_name:
                    continue

                s_container = s.get("container", "") or ""
                s_container_normalized = self._normalize_container(s_container)
                s_path = s.get("path", "")
                s_module = self._get_module_name(s_path)
                full_container = f"{s_module}.{s_container_normalized}" if s_container_normalized else s_module

                s_effective_container = self._get_effective_container(s)

                if s_container_normalized == container_str:
                    matching.append(s)
                elif s_container == container_str:
                    matching.append(s)
                elif s_effective_container == container_str:
                    matching.append(s)
                elif full_container == container_str:
                    matching.append(s)
                elif full_container.endswith(f".{container_str}"):
                    matching.append(s)
                elif len(sym_parts) == 2 and sym_parts[0] == s_module:
                    matching.append(s)

        return len(matching) == 1 and matching[0] is target_sym

    def _get_module_name(self, rel_path: str) -> str:
        path = Path(rel_path)
        return path.stem

    def _normalize_container(self, container: str) -> str:
        match = re.match(r"^\(\*?(\w+)\)$", container)
        if match:
            return match.group(1)
        match = re.match(r"^impl\s+\w+(?:<[^>]+>)?\s+for\s+(\w+)", container)
        if match:
            return match.group(1)
        match = re.match(r"^impl\s+(\w+)", container)
        if match:
            return match.group(1)
        return container

    async def _collect_symbols_for_paths(
        self, paths: list[Path], workspace_root: Path
    ) -> list[dict]:
        files_by_language: dict[str, list[Path]] = {}
        for file_path in paths:
            if not file_path.exists():
                continue
            lang = get_language_id(file_path)
            if lang and lang != "plaintext":
                files_by_language.setdefault(lang, []).append(file_path)

        all_symbols = []
        for lang, files in files_by_language.items():
            try:
                workspace = await self.session.get_or_create_workspace(
                    files[0], workspace_root
                )
            except ValueError:
                continue

            if not workspace or not workspace.client:
                continue

            symbols = await self._collect_symbols_from_files(workspace, workspace_root, files)
            all_symbols.extend(symbols)

        return all_symbols

    async def _collect_all_workspace_symbols(
        self, workspace_root: Path, query: str
    ) -> list[dict]:
        from ..servers.registry import get_server_for_language

        skip_dirs = {
            "node_modules", "__pycache__", ".git", "venv", ".venv",
            "build", "dist", ".tox", ".eggs",
        }
        excluded_languages = set(
            self.session.config.get("workspaces", {}).get("excluded_languages", [])
        )

        languages_found: dict[str, list[Path]] = {}
        for file_path in workspace_root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(
                part.startswith(".") or part in skip_dirs or part.endswith(".egg-info")
                for part in file_path.parts
            ):
                continue

            lang_id = get_language_id(file_path)
            if lang_id == "plaintext" or lang_id in excluded_languages:
                continue

            server_config = get_server_for_language(lang_id, self.session.config)
            if server_config is None:
                continue

            if lang_id not in languages_found:
                languages_found[lang_id] = []
            languages_found[lang_id].append(file_path)

        all_symbols = []

        for lang_id, files in languages_found.items():
            workspace = await self.session.get_or_create_workspace_for_language(
                lang_id, workspace_root
            )

            if not workspace or not workspace.client:
                continue

            symbols = await self._collect_symbols_from_files(workspace, workspace_root, files)
            all_symbols.extend(symbols)

        return all_symbols

    async def _collect_symbols_from_files(
        self, workspace: Workspace, workspace_root: Path, files: list[Path], close_after: bool = True
    ) -> list[dict]:
        symbols = []
        opened_files = []

        for file_path in files:
            file_symbols = await self._get_file_symbols_cached(
                workspace, workspace_root, file_path
            )
            symbols.extend(file_symbols)
            if str(file_path) in workspace.open_documents:
                opened_files.append(file_path)

        if close_after:
            for file_path in opened_files:
                await workspace.close_document(file_path)

        return symbols

    async def _get_file_symbols_cached(
        self, workspace: Workspace, workspace_root: Path, file_path: Path
    ) -> list[dict]:
        file_sha = self._get_file_sha(file_path)
        cache_key = (str(file_path), file_sha)

        cached = self._symbol_cache.get(cache_key)
        if cached is not None:
            return cached

        symbols = []
        try:
            doc = await workspace.ensure_document_open(file_path)
            result = await workspace.client.send_request(
                "textDocument/documentSymbol",
                {"textDocument": {"uri": doc.uri}},
            )
            if result:
                rel_path = self._relative_path(file_path, workspace_root)
                self._flatten_symbols(result, rel_path, symbols)

            self._symbol_cache[cache_key] = symbols
        except Exception as e:
            logger.warning(f"Failed to get symbols for {file_path}: {e}")
            self._symbol_cache[cache_key] = []

        return symbols

    def _flatten_symbols(
        self, items: list, file_path: str, output: list, container: str | None = None
    ) -> None:
        for item in items:
            if "location" in item:
                output.append(
                    {
                        "name": item["name"],
                        "kind": SymbolKind(item["kind"]).name,
                        "path": file_path,
                        "line": item["location"]["range"]["start"]["line"] + 1,
                        "column": item["location"]["range"]["start"]["character"],
                        "container": item.get("containerName"),
                    }
                )
            else:
                sel_range = item.get("selectionRange", item["range"])
                full_range = item["range"]
                output.append(
                    {
                        "name": item["name"],
                        "kind": SymbolKind(item["kind"]).name,
                        "path": file_path,
                        "line": sel_range["start"]["line"] + 1,
                        "column": sel_range["start"]["character"],
                        "container": container,
                        "detail": item.get("detail"),
                        "range_start_line": full_range["start"]["line"] + 1,
                        "range_end_line": full_range["end"]["line"] + 1,
                    }
                )
                if item.get("children"):
                    self._flatten_symbols(item["children"], file_path, output, item["name"])

    async def _get_symbol_documentation(
        self, workspace_root: Path, rel_path: str, line: int, column: int
    ) -> str | None:
        file_path = workspace_root / rel_path

        workspace = self.session.get_workspace_for_file(file_path)
        if not workspace or not workspace.client:
            return None

        try:
            file_sha = self._get_file_sha(file_path)
            cache_key = (str(file_path), line, column, file_sha)

            if cache_key in self._hover_cache:
                return self._hover_cache[cache_key] or None

            doc = await workspace.ensure_document_open(file_path)
            result = await workspace.client.send_request(
                "textDocument/hover",
                {
                    "textDocument": {"uri": doc.uri},
                    "position": {"line": line - 1, "character": column},
                },
            )

            if not result:
                self._hover_cache[cache_key] = ""
                return None

            contents = result.get("contents")
            if isinstance(contents, dict):
                doc_str = contents.get("value")
            elif isinstance(contents, list):
                doc_str = "\n".join(
                    c.get("value", str(c)) if isinstance(c, dict) else str(c)
                    for c in contents
                )
            else:
                doc_str = str(contents) if contents else None

            self._hover_cache[cache_key] = doc_str or ""
            return doc_str
        except Exception as e:
            logger.debug(f"Failed to get hover for {rel_path}:{line}: {e}")
            return None

    def _get_file_sha(self, file_path: Path) -> str:
        import hashlib

        try:
            content = file_path.read_bytes()
            return hashlib.sha256(content).hexdigest()[:16]
        except Exception:
            return ""

    def _find_symbol_at_line(self, symbols: list, line: int) -> dict | None:
        for sym in symbols:
            if "range" in sym:
                start = sym["range"]["start"]["line"]
                end = sym["range"]["end"]["line"]
                if start <= line <= end:
                    if sym.get("children"):
                        child = self._find_symbol_at_line(sym["children"], line)
                        if child:
                            return child
                    return sym
            elif "location" in sym:
                sym_line = sym["location"]["range"]["start"]["line"]
                if sym_line == line:
                    return sym
        return None


async def run_daemon() -> None:
    log_dir = get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "daemon.log"),
        ],
    )

    config = load_config()
    daemon_config = config.get("daemon", {})
    hover_cache_bytes = daemon_config.get("hover_cache_size", DEFAULT_CACHE_SIZE_BYTES)
    symbol_cache_bytes = daemon_config.get("symbol_cache_size", DEFAULT_CACHE_SIZE_BYTES)

    daemon = DaemonServer(
        hover_cache_bytes=hover_cache_bytes,
        symbol_cache_bytes=symbol_cache_bytes,
    )
    await daemon.start()
