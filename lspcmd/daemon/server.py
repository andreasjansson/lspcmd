import asyncio
import json
import logging
import os
import signal
from functools import lru_cache
from pathlib import Path
from typing import Any

from .session import Session, Workspace
from .pidfile import write_pid, remove_pid
from ..lsp.protocol import LSPResponseError, LSPMethodNotSupported, LanguageServerNotFound
from ..utils.config import get_socket_path, get_pid_path, get_log_dir, load_config
from ..utils.uri import path_to_uri, uri_to_path
from ..utils.text import read_file_content, get_lines_around, get_language_id
from ..lsp.types import (
    TextEdit,
    WorkspaceEdit,
    SymbolKind,
    CodeActionKind,
    FormattingOptions,
)

logger = logging.getLogger(__name__)

HOVER_CACHE_SIZE = 50000


class LRUCache:
    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self.cache: dict[tuple, str] = {}
        self.order: list[tuple] = []
    
    def __contains__(self, key: tuple) -> bool:
        return key in self.cache
    
    def __getitem__(self, key: tuple) -> str:
        self.order.remove(key)
        self.order.append(key)
        return self.cache[key]
    
    def __setitem__(self, key: tuple, value: str) -> None:
        if key in self.cache:
            self.order.remove(key)
        elif len(self.cache) >= self.maxsize:
            oldest = self.order.pop(0)
            del self.cache[oldest]
        self.cache[key] = value
        self.order.append(key)


class DaemonServer:
    def __init__(self):
        self.session = Session()
        self.server: asyncio.Server | None = None
        self._shutdown_event = asyncio.Event()
        self._hover_cache = LRUCache(HOVER_CACHE_SIZE)

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
            "list-code-actions": self._handle_list_code_actions,
            "raw-lsp-request": self._handle_raw_lsp_request,
            "execute-code-action": self._handle_execute_code_action,
            "format": self._handle_format,
            "organize-imports": self._handle_organize_imports,
            "rename": self._handle_rename,
            "grep": self._handle_grep,
            "fetch-symbol-docs": self._handle_fetch_symbol_docs,
            "restart-workspace": self._handle_restart_workspace,
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

    async def _handle_shutdown(self, params: dict) -> dict:
        asyncio.create_task(self._shutdown())
        return {"status": "shutting_down"}

    async def _handle_describe_session(self, params: dict) -> dict:
        return self.session.to_dict()

    async def _handle_raw_lsp_request(self, params: dict) -> Any:
        workspace_root = Path(params["workspace_root"]).resolve()
        lsp_method = params["method"]
        lsp_params = params.get("params", {})
        language = params.get("language", "python")
        
        workspace = await self.session.get_or_create_workspace_for_language(language, workspace_root)
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

    def _format_locations(self, result: Any, workspace_root: Path, context: int = 0) -> list[dict]:
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

    async def _handle_definition(self, params: dict) -> list[dict] | dict:
        body = params.get("body", False)
        if body:
            return await self._handle_definition_body(params)
        return await self._handle_location_request(params, "textDocument/definition")

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

        workspace, doc, _ = await self._get_workspace_and_document({
            "path": str(file_path),
            "workspace_root": params["workspace_root"],
        })

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": doc.uri}},
        )

        content = read_file_content(file_path)
        lines = content.splitlines()

        if result:
            symbol = self._find_symbol_at_line(result, target_line)
            if symbol:
                start = symbol["range"]["start"]["line"]
                end = symbol["range"]["end"]["line"]
                if context > 0:
                    start = max(0, start - context)
                    end = min(len(lines) - 1, end + context)
                return {
                    "path": rel_path,
                    "start_line": start + 1,
                    "end_line": end + 1,
                    "content": "\n".join(lines[start : end + 1]),
                }

        return {
            "path": rel_path,
            "start_line": loc["line"],
            "end_line": loc["line"],
            "content": lines[target_line] if target_line < len(lines) else "",
        }

    async def _handle_declaration(self, params: dict) -> list[dict]:
        return await self._handle_location_request(params, "textDocument/declaration")

    async def _handle_implementations(self, params: dict) -> list[dict]:
        return await self._handle_location_request(params, "textDocument/implementation")

    async def _handle_subtypes(self, params: dict) -> list[dict]:
        return await self._handle_type_hierarchy_request(params, "typeHierarchy/subtypes")

    async def _handle_supertypes(self, params: dict) -> list[dict]:
        return await self._handle_type_hierarchy_request(params, "typeHierarchy/supertypes")

    async def _handle_type_hierarchy_request(self, params: dict, method: str) -> list[dict]:
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
                raise LSPMethodNotSupported("textDocument/prepareTypeHierarchy", workspace.server_config.name)
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

    def _format_type_hierarchy_items(self, result: Any, workspace_root: Path, context: int = 0) -> list[dict]:
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

        if workspace.client.supports_pull_diagnostics:
            try:
                result = await workspace.client.send_request(
                    "textDocument/diagnostic",
                    {"textDocument": {"uri": doc.uri}},
                )
                if result and result.get("items"):
                    return self._format_diagnostics(result["items"], path, workspace.root)
                return []
            except LSPResponseError as e:
                if e.is_method_not_found():
                    workspace.client.supports_pull_diagnostics = False
                else:
                    raise

        # Use stored diagnostics from publishDiagnostics notifications
        # Wait briefly for server to analyze and push diagnostics
        await asyncio.sleep(0.5)
        stored = workspace.client.get_stored_diagnostics(doc.uri)
        if stored:
            return self._format_diagnostics(stored, path, workspace.root)

        return []

    def _format_diagnostics(self, items: list, path: Path, workspace_root: Path) -> list[dict]:
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
                workspace = await self.session.get_or_create_workspace(files[0], workspace_root)
            except ValueError:
                continue
            
            if not workspace.client:
                continue
                
            await workspace.client.wait_for_service_ready()
            
            use_pull = workspace.client.supports_pull_diagnostics
            
            if use_pull:
                # Probe first file with short timeout to check if pull is supported
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
                            self._format_diagnostics(result["items"], first_file, workspace_root)
                        )
                except (LSPResponseError, asyncio.TimeoutError) as e:
                    if isinstance(e, LSPResponseError) and not e.is_method_not_found():
                        raise
                    workspace.client.supports_pull_diagnostics = False
                    use_pull = False
                finally:
                    await workspace.close_document(first_file)
                
                # Process remaining files if pull is supported
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
                                    self._format_diagnostics(result["items"], file_path, workspace_root)
                                )
                        except LSPResponseError:
                            pass
                        finally:
                            await workspace.close_document(file_path)
            
            if not use_pull:
                # For push diagnostics: open all files, wait, then collect
                opened_files = []
                for file_path in files:
                    doc = await workspace.ensure_document_open(file_path)
                    opened_files.append((file_path, doc))
                
                # Wait for server to analyze and push diagnostics
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
            ".ex", ".exs", ".hs", ".ml", ".mli", ".lua", ".zig",
        }
        exclude_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", 
                       "target", "build", "dist", ".tox", ".mypy_cache", ".pytest_cache",
                       ".eggs", "*.egg-info"}
        
        files = []
        for root, dirs, filenames in os.walk(workspace_root):
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.endswith(".egg-info")]
            
            for filename in filenames:
                if Path(filename).suffix in source_extensions:
                    files.append(Path(root) / filename)
        
        return files

    async def _handle_list_code_actions(self, params: dict) -> list[dict]:
        workspace, doc, path = await self._get_workspace_and_document(params)
        line, column = self._parse_position(params)

        result = await workspace.client.send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": doc.uri},
                "range": {
                    "start": {"line": line, "character": column},
                    "end": {"line": line, "character": column},
                },
                "context": {"diagnostics": []},
            },
        )

        if not result:
            return []

        return [
            {
                "title": action.get("title"),
                "kind": action.get("kind"),
                "is_preferred": action.get("isPreferred", False),
            }
            for action in result
        ]

    async def _handle_execute_code_action(self, params: dict) -> dict:
        workspace, doc, path = await self._get_workspace_and_document(params)
        line, column = self._parse_position(params)
        action_title = params["action_title"]

        result = await workspace.client.send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": doc.uri},
                "range": {
                    "start": {"line": line, "character": column},
                    "end": {"line": line, "character": column},
                },
                "context": {"diagnostics": []},
            },
        )

        if not result:
            return {"error": "No code actions available"}

        action = None
        for a in result:
            if a.get("title") == action_title:
                action = a
                break

        if not action:
            return {"error": f"Code action not found: {action_title}"}

        if action.get("edit"):
            files_modified = await self._apply_workspace_edit(action["edit"], workspace.root)
            return {"files_modified": files_modified}

        if action.get("command"):
            cmd = action["command"]
            await workspace.client.send_request(
                "workspace/executeCommand",
                {"command": cmd["command"], "arguments": cmd.get("arguments", [])},
            )
            return {"command_executed": cmd["command"]}

        return {"status": "ok"}

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

    async def _handle_format_buffer(self, params: dict) -> dict:
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

    async def _handle_list_symbols(self, params: dict) -> list[dict]:
        if params.get("path"):
            return await self._handle_document_symbols(params)
        else:
            return await self._handle_workspace_symbols(params)

    async def _handle_document_symbols(self, params: dict) -> list[dict]:
        workspace, doc, path = await self._get_workspace_and_document(params)

        await workspace.client.wait_for_service_ready()

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": doc.uri}},
        )

        if not result:
            return []

        rel_path = self._relative_path(path, workspace.root)
        symbols = []
        self._flatten_symbols(result, rel_path, symbols)
        return symbols

    def _relative_path(self, path: Path, workspace_root: Path) -> str:
        try:
            return str(path.relative_to(workspace_root))
        except ValueError:
            return str(path)

    def _flatten_symbols(self, items: list, file_path: str, output: list, container: str | None = None) -> None:
        for item in items:
            if "location" in item:
                output.append({
                    "name": item["name"],
                    "kind": SymbolKind(item["kind"]).name,
                    "path": file_path,
                    "line": item["location"]["range"]["start"]["line"] + 1,
                    "column": item["location"]["range"]["start"]["character"],
                    "container": item.get("containerName"),
                })
            else:
                # Use selectionRange for the symbol name position (for hover)
                sel_range = item.get("selectionRange", item["range"])
                output.append({
                    "name": item["name"],
                    "kind": SymbolKind(item["kind"]).name,
                    "path": file_path,
                    "line": item["range"]["start"]["line"] + 1,
                    "column": sel_range["start"]["character"],
                    "container": container,
                    "detail": item.get("detail"),
                })
                if item.get("children"):
                    self._flatten_symbols(item["children"], file_path, output, item["name"])

    async def _handle_workspace_symbols(self, params: dict) -> list[dict]:
        query = params.get("query", "")

        workspace_root_param = params.get("workspace_root")
        if not workspace_root_param:
            # Find any existing workspace
            for servers in self.session.workspaces.values():
                if servers:
                    workspace = next(iter(servers.values()))
                    workspace_root = workspace.root
                    break
            else:
                return []
        else:
            workspace_root = Path(workspace_root_param).resolve()

        # Discover all languages in the workspace and collect symbols from each
        return await self._collect_all_workspace_symbols(workspace_root, query)

    async def _collect_all_workspace_symbols(self, workspace_root: Path, query: str) -> list[dict]:
        from ..utils.text import get_language_id
        from ..servers.registry import get_server_for_language

        skip_dirs = {"node_modules", "__pycache__", ".git", "venv", ".venv", "build", "dist", ".tox", ".eggs"}
        excluded_languages = set(self.session.config.get("workspaces", {}).get("excluded_languages", []))
        
        languages_found: dict[str, list[Path]] = {}
        for file_path in workspace_root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part.startswith(".") or part in skip_dirs or part.endswith(".egg-info")
                   for part in file_path.parts):
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
            workspace = await self.session.get_or_create_workspace_for_language(lang_id, workspace_root)
            
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
            try:
                doc = await workspace.ensure_document_open(file_path)
                opened_files.append(file_path)
                result = await workspace.client.send_request(
                    "textDocument/documentSymbol",
                    {"textDocument": {"uri": doc.uri}},
                )
                if result:
                    rel_path = self._relative_path(file_path, workspace_root)
                    self._flatten_symbols(result, rel_path, symbols)
            except Exception as e:
                logger.warning(f"Failed to get symbols for {file_path}: {e}")

        if close_after:
            for file_path in opened_files:
                await workspace.close_document(file_path)

        return symbols

    async def _handle_fetch_symbol_docs(self, params: dict) -> list[dict]:
        """Fetch documentation for a list of symbols."""
        symbols = params.get("symbols", [])
        workspace_root = Path(params.get("workspace_root", ".")).resolve()
        
        for sym in symbols:
            sym["documentation"] = await self._get_symbol_documentation(
                workspace_root, sym["path"], sym["line"], sym.get("column", 0)
            )
        
        return symbols

    async def _get_symbol_documentation(self, workspace_root: Path, rel_path: str, line: int, column: int) -> str | None:
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

    async def _handle_print_definition(self, params: dict) -> dict:
        locations = await self._handle_find_definition(params)

        if not locations:
            return {"error": "Definition not found"}

        loc = locations[0]
        workspace_root = Path(params["workspace_root"]).resolve()
        rel_path = loc["path"]
        file_path = workspace_root / rel_path
        target_line = loc["line"] - 1

        workspace, doc, _ = await self._get_workspace_and_document({
            "path": str(file_path),
            "workspace_root": params["workspace_root"],
        })

        result = await workspace.client.send_request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": doc.uri}},
        )

        content = read_file_content(file_path)
        lines = content.splitlines()

        if result:
            symbol = self._find_symbol_at_line(result, target_line)
            if symbol:
                start = symbol["range"]["start"]["line"]
                end = symbol["range"]["end"]["line"]
                return {
                    "path": rel_path,
                    "start_line": start + 1,
                    "end_line": end + 1,
                    "content": "\n".join(lines[start : end + 1]),
                }

        return {
            "path": rel_path,
            "start_line": loc["line"],
            "end_line": loc["line"],
            "content": lines[target_line] if target_line < len(lines) else "",
        }

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

    async def _handle_restart_workspace(self, params: dict) -> dict:
        workspace_root = Path(params["workspace_root"]).resolve()
        servers = self.session.workspaces.get(workspace_root, {})

        if servers:
            # Restart existing servers
            restarted = []
            for server_name, workspace in list(servers.items()):
                if workspace.client is not None:
                    await workspace.stop_server()
                await workspace.start_server()
                restarted.append(server_name)
            return {"restarted": True, "servers": restarted}
        
        # No servers running - discover languages and start servers
        languages = self._discover_languages(workspace_root)
        if not languages:
            return {"error": f"No supported source files found in {workspace_root}"}

        started = []
        for lang_id in languages:
            workspace = await self.session.get_or_create_workspace_for_language(lang_id, workspace_root)
            if workspace and workspace.client:
                started.append(workspace.server_config.name)

        return {"restarted": True, "servers": started}

    def _discover_languages(self, workspace_root: Path) -> list[str]:
        from ..utils.text import get_language_id
        from ..servers.registry import get_server_for_language

        skip_dirs = {"node_modules", "__pycache__", ".git", "venv", ".venv", "build", "dist", ".tox", ".eggs"}
        excluded_languages = set(self.session.config.get("workspaces", {}).get("excluded_languages", []))
        languages = set()

        for file_path in workspace_root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part.startswith(".") or part in skip_dirs or part.endswith(".egg-info")
                   for part in file_path.parts):
                continue
            
            lang_id = get_language_id(file_path)
            if lang_id == "plaintext" or lang_id in excluded_languages:
                continue
            
            server_config = get_server_for_language(lang_id, self.session.config)
            if server_config:
                languages.add(lang_id)

        return list(languages)


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

    daemon = DaemonServer()
    await daemon.start()
