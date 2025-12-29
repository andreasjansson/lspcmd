import asyncio
import json
import logging
import os
import signal
from pathlib import Path
from typing import Any

from .session import Session, Workspace
from .pidfile import write_pid, remove_pid
from ..lsp.protocol import LSPResponseError, LanguageServerNotFound
from ..utils.config import get_socket_path, get_pid_path, get_log_dir, load_config
from ..utils.uri import path_to_uri, uri_to_path
from ..utils.text import read_file_content, get_lines_around
from ..lsp.types import (
    TextEdit,
    WorkspaceEdit,
    SymbolKind,
    CodeActionKind,
    FormattingOptions,
)

logger = logging.getLogger(__name__)


class DaemonServer:
    def __init__(self):
        self.session = Session()
        self.server: asyncio.Server | None = None
        self._shutdown_event = asyncio.Event()

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
            data = await reader.read(1024 * 1024)
            if not data:
                return

            request = json.loads(data.decode())
            response = await self._handle_request(request)

            writer.write(json.dumps(response).encode())
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
            "describe-thing-at-point": self._handle_hover,
            "find-definition": self._handle_find_definition,
            "find-declaration": self._handle_find_declaration,
            "find-implementation": self._handle_find_implementation,
            "find-type-definition": self._handle_find_type_definition,
            "find-references": self._handle_find_references,
            "list-code-actions": self._handle_list_code_actions,
            "execute-code-action": self._handle_execute_code_action,
            "format-buffer": self._handle_format_buffer,
            "organize-imports": self._handle_organize_imports,
            "rename": self._handle_rename,
            "list-symbols": self._handle_list_symbols,
            "search-symbol": self._handle_search_symbol,
            "list-signatures": self._handle_list_signatures,
            "print-definition": self._handle_print_definition,
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

        result = await workspace.client.send_request(
            method,
            {
                "textDocument": {"uri": doc.uri},
                "position": {"line": line, "character": column},
            },
        )

        return self._format_locations(result, context)

    def _format_locations(self, result: Any, context: int = 0) -> list[dict]:
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
                "path": str(file_path),
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

    async def _handle_find_definition(self, params: dict) -> list[dict]:
        return await self._handle_location_request(params, "textDocument/definition")

    async def _handle_find_declaration(self, params: dict) -> list[dict]:
        return await self._handle_location_request(params, "textDocument/declaration")

    async def _handle_find_implementation(self, params: dict) -> list[dict]:
        return await self._handle_location_request(params, "textDocument/implementation")

    async def _handle_find_type_definition(self, params: dict) -> list[dict]:
        return await self._handle_location_request(params, "textDocument/typeDefinition")

    async def _handle_find_references(self, params: dict) -> list[dict]:
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

        return self._format_locations(result, params.get("context", 0))

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
            files_modified = await self._apply_workspace_edit(action["edit"])
            return {"files_modified": files_modified}

        if action.get("command"):
            cmd = action["command"]
            await workspace.client.send_request(
                "workspace/executeCommand",
                {"command": cmd["command"], "arguments": cmd.get("arguments", [])},
            )
            return {"command_executed": cmd["command"]}

        return {"status": "ok"}

    async def _apply_workspace_edit(self, edit: dict) -> list[str]:
        files_modified = []

        if edit.get("changes"):
            for uri, text_edits in edit["changes"].items():
                file_path = uri_to_path(uri)
                await self._apply_text_edits(file_path, text_edits)
                files_modified.append(str(file_path))

        if edit.get("documentChanges"):
            for change in edit["documentChanges"]:
                kind = change.get("kind")
                if kind == "create":
                    file_path = uri_to_path(change["uri"])
                    file_path.touch()
                    files_modified.append(str(file_path))
                elif kind == "rename":
                    old_path = uri_to_path(change["oldUri"])
                    new_path = uri_to_path(change["newUri"])
                    old_path.rename(new_path)
                    files_modified.append(str(new_path))
                elif kind == "delete":
                    file_path = uri_to_path(change["uri"])
                    file_path.unlink(missing_ok=True)
                    files_modified.append(str(file_path))
                elif "textDocument" in change:
                    file_path = uri_to_path(change["textDocument"]["uri"])
                    await self._apply_text_edits(file_path, change["edits"])
                    files_modified.append(str(file_path))

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
            await self._apply_workspace_edit(action["edit"])
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

        files_modified = await self._apply_workspace_edit(result)
        return {"renamed": True, "files_modified": files_modified}

    async def _handle_list_symbols(self, params: dict) -> list[dict]:
        if params.get("path"):
            symbols = await self._handle_document_symbols(params)
        else:
            symbols = await self._handle_workspace_symbols(params)
        
        if params.get("include_docs"):
            workspace_root = Path(params.get("workspace_root", ".")).resolve()
            for sym in symbols:
                sym["documentation"] = await self._get_symbol_documentation(
                    workspace_root, sym["path"], sym["line"], sym.get("column", 0)
                )
        
        return symbols

    async def _handle_document_symbols(self, params: dict) -> list[dict]:
        workspace, doc, path = await self._get_workspace_and_document(params)

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
        import time
        from ..utils.text import get_language_id
        from ..servers.registry import get_server_for_language

        start_time = time.time()
        logger.info(f"Starting workspace symbol collection for {workspace_root}")

        skip_dirs = {"node_modules", "__pycache__", ".git", "venv", ".venv", "build", "dist", ".tox", ".eggs"}
        excluded_languages = set(self.session.config.get("workspaces", {}).get("excluded_languages", []))
        
        # Find all unique languages in the workspace
        scan_start = time.time()
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

        logger.info(f"File scan took {time.time() - scan_start:.2f}s, found languages: {list(languages_found.keys())} with {sum(len(f) for f in languages_found.values())} files")

        all_symbols = []
        
        for lang_id, files in languages_found.items():
            lang_start = time.time()
            logger.info(f"Processing {lang_id} ({len(files)} files)...")
            
            workspace = await self.session.get_or_create_workspace_for_language(lang_id, workspace_root)
            logger.info(f"  Server startup took {time.time() - lang_start:.2f}s")
            
            if not workspace or not workspace.client:
                continue

            # Try workspace/symbol first, fall back to document symbols if not supported
            result = None
            try:
                ws_start = time.time()
                result = await workspace.client.send_request(
                    "workspace/symbol",
                    {"query": query},
                )
                logger.info(f"  workspace/symbol took {time.time() - ws_start:.2f}s, got {len(result) if result else 0} results")
            except LSPResponseError as e:
                # Server doesn't support workspace/symbol, fall back to document symbols
                logger.info(f"  workspace/symbol not supported for {lang_id}: {e.message}")

            if result:
                for item in result:
                    all_symbols.append({
                        "name": item["name"],
                        "kind": SymbolKind(item["kind"]).name,
                        "path": self._relative_path(uri_to_path(item["location"]["uri"]), workspace_root),
                        "line": item["location"]["range"]["start"]["line"] + 1,
                        "container": item.get("containerName"),
                    })
            else:
                # Fall back to document symbols for each file
                ds_start = time.time()
                symbols = await self._collect_symbols_from_files(workspace, workspace_root, files)
                logger.info(f"  document symbols fallback took {time.time() - ds_start:.2f}s, got {len(symbols)} symbols")
                all_symbols.extend(symbols)
            
            logger.info(f"  Total for {lang_id}: {time.time() - lang_start:.2f}s")

        logger.info(f"Total workspace symbol collection: {time.time() - start_time:.2f}s, {len(all_symbols)} symbols")
        return all_symbols

    async def _collect_symbols_from_files(self, workspace: Workspace, workspace_root: Path, files: list[Path]) -> list[dict]:
        symbols = []

        for file_path in files:
            try:
                doc = await workspace.ensure_document_open(file_path)
                result = await workspace.client.send_request(
                    "textDocument/documentSymbol",
                    {"textDocument": {"uri": doc.uri}},
                )
                if result:
                    rel_path = self._relative_path(file_path, workspace_root)
                    self._flatten_symbols(result, rel_path, symbols)
            except Exception as e:
                logger.warning(f"Failed to get symbols for {file_path}: {e}")

        return symbols

    async def _handle_search_symbol(self, params: dict) -> list[dict]:
        import re

        symbols = await self._handle_list_symbols(params)
        pattern = params.get("pattern", "")

        if not pattern:
            return symbols

        regex = re.compile(pattern, re.IGNORECASE)
        return [s for s in symbols if regex.search(s["name"])]

    async def _handle_list_signatures(self, params: dict) -> list[dict]:
        symbols = await self._handle_list_symbols(params)
        signatures = [
            s for s in symbols
            if s["kind"] in ("Function", "Method", "Constructor")
        ]
        
        if not params.get("include_docs"):
            return signatures
        
        # Fetch documentation via hover for each signature
        workspace_root = Path(params.get("workspace_root", ".")).resolve()
        for sig in signatures:
            sig["documentation"] = await self._get_symbol_documentation(
                workspace_root, sig["path"], sig["line"], sig.get("column", 0)
            )
        
        return signatures

    async def _get_symbol_documentation(self, workspace_root: Path, rel_path: str, line: int, column: int) -> str | None:
        file_path = workspace_root / rel_path
        
        workspace = self.session.get_workspace_for_file(file_path)
        if not workspace or not workspace.client:
            return None
        
        try:
            doc = await workspace.ensure_document_open(file_path)
            result = await workspace.client.send_request(
                "textDocument/hover",
                {
                    "textDocument": {"uri": doc.uri},
                    "position": {"line": line - 1, "character": column},
                },
            )
            
            if not result:
                return None
            
            contents = result.get("contents")
            if isinstance(contents, dict):
                return contents.get("value")
            elif isinstance(contents, list):
                return "\n".join(
                    c.get("value", str(c)) if isinstance(c, dict) else str(c)
                    for c in contents
                )
            else:
                return str(contents) if contents else None
        except Exception as e:
            logger.debug(f"Failed to get hover for {rel_path}:{line}: {e}")
            return None

    async def _handle_print_definition(self, params: dict) -> dict:
        locations = await self._handle_find_definition(params)

        if not locations:
            return {"error": "Definition not found"}

        loc = locations[0]
        file_path = Path(loc["path"])
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
                    "path": str(file_path),
                    "start_line": start + 1,
                    "end_line": end + 1,
                    "content": "\n".join(lines[start : end + 1]),
                }

        return {
            "path": str(file_path),
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
