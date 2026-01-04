import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..lsp.client import LSPClient
from ..lsp.protocol import LanguageServerNotFound, LanguageServerStartupError
from ..lsp.types import FileChangeType, FileEvent, DidChangeWatchedFilesParams
from ..utils.config import get_log_dir, Config
from ..utils.uri import path_to_uri
from ..utils.text import get_language_id, read_file_content
from ..servers.registry import (
    ServerConfig,
    get_server_for_file,
    get_server_for_language,
)

logger = logging.getLogger(__name__)


@dataclass
class OpenDocument:
    uri: str
    version: int
    content: str
    language_id: str


@dataclass
class Workspace:
    root: Path
    server_config: ServerConfig
    client: LSPClient | None = None
    open_documents: dict[str, OpenDocument] = field(default_factory=dict)

    async def start_server(self) -> None:
        if self.client is not None:
            return

        logger.info(f"Starting {self.server_config.name} for {self.root}")

        env = self._get_server_env()

        try:
            process = await asyncio.create_subprocess_exec(
                *self.server_config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.root),
                env=env,
            )
        except FileNotFoundError:
            raise LanguageServerNotFound(
                self.server_config.name,
                ", ".join(self.server_config.languages),
                self.server_config.install_cmd,
            )

        init_options = self._get_init_options()
        server_log_file = get_log_dir() / f"{self.server_config.name}.log"
        self.client = LSPClient(
            process,
            path_to_uri(self.root),
            init_options,
            server_name=self.server_config.name,
            log_file=server_log_file,
        )

        try:
            await self.client.start()
        except Exception as e:
            self.client = None

            # Read recent lines from the server log file
            server_log_tail = None
            if server_log_file.exists():
                try:
                    content = server_log_file.read_text()
                    lines = content.strip().splitlines()
                    server_log_tail = "\n".join(lines[-30:])
                except Exception:
                    pass

            raise LanguageServerStartupError(
                self.server_config.name,
                ", ".join(self.server_config.languages),
                str(self.root),
                e,
                server_log=server_log_tail,
                log_path=str(server_log_file),
            )

        # Wait for initial indexing to complete
        await self.client.wait_for_indexing(timeout=60.0)

        # For servers that do lazy indexing, pre-index all files
        await self.ensure_workspace_indexed()

        logger.info(f"Server {self.server_config.name} initialized and ready")

    def _get_init_options(self) -> dict[str, Any]:
        if self.server_config.name == "gopls":
            return {
                "linksInHover": False,
            }
        return {}

    def _get_server_env(self) -> dict[str, str]:
        import os
        from ..servers.registry import _get_extended_path

        env = os.environ.copy()
        env["PATH"] = _get_extended_path()
        return env

    async def stop_server(self) -> None:
        if self.client is None:
            return

        logger.info(f"Stopping {self.server_config.name}")
        await self.client.stop()
        self.client = None
        self.open_documents.clear()

    async def close_document(self, path: Path) -> None:
        uri = path_to_uri(path)
        if uri not in self.open_documents:
            return

        del self.open_documents[uri]

        if self.client is not None:
            await self.client.send_notification(
                "textDocument/didClose",
                {"textDocument": {"uri": uri}},
            )

    async def close_all_documents(self) -> None:
        if self.client is None:
            return

        for uri in list(self.open_documents.keys()):
            await self.client.send_notification(
                "textDocument/didClose",
                {"textDocument": {"uri": uri}},
            )
        self.open_documents.clear()

    async def notify_files_changed(
        self, changes: list[tuple[Path, FileChangeType]]
    ) -> None:
        """Notify the LSP server about file changes via workspace/didChangeWatchedFiles.
        
        This is needed for servers like jdtls that rely on file watching.
        """
        if self.client is None:
            return

        file_events = [
            FileEvent(uri=path_to_uri(path), type=change_type.value)
            for path, change_type in changes
        ]
        
        await self.client.send_notification(
            "workspace/didChangeWatchedFiles",
            DidChangeWatchedFilesParams(changes=file_events).model_dump(),
        )

    async def ensure_workspace_indexed(self) -> None:
        """Open and close all source files to ensure clangd indexes them."""
        if self.client is None:
            return

        # Only needed for clangd which does lazy indexing
        if self.server_config.name != "clangd":
            return

        source_extensions = {".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hxx"}
        exclude_dirs = {"build", ".git", "node_modules"}

        files_to_index = []
        for file_path in self.root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in exclude_dirs for part in file_path.parts):
                continue
            if file_path.suffix in source_extensions:
                files_to_index.append(file_path)

        if not files_to_index:
            return

        logger.info(
            f"Pre-indexing {len(files_to_index)} files for clangd: {[f.name for f in files_to_index]}"
        )

        for file_path in files_to_index:
            await self.ensure_document_open(file_path)

        await self.client.wait_for_indexing(timeout=30.0)

        logger.info(
            f"Pre-indexing complete, closing {len(self.open_documents)} documents"
        )
        await self.close_all_documents()

    async def ensure_document_open(self, path: Path) -> OpenDocument:
        uri = path_to_uri(path)

        if uri in self.open_documents:
            doc = self.open_documents[uri]
            current_content = read_file_content(path)
            if current_content != doc.content:
                # Close and reopen the document to force a full refresh
                # This is more reliable than didChange for servers that use incremental sync
                # (like ruby-lsp) since we don't track the exact edits made
                await self.close_document(path)
                # Fall through to reopen below
            else:
                return doc

        content = read_file_content(path)
        language_id = get_language_id(path)
        doc = OpenDocument(uri=uri, version=1, content=content, language_id=language_id)
        self.open_documents[uri] = doc

        assert self.client is not None
        await self.client.send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": doc.version,
                    "text": content,
                }
            },
        )

        # ruby-lsp processes messages asynchronously in a queue, so we need to ensure
        # the didOpen is fully processed before subsequent operations can succeed.
        # We do this by sending a simple request and waiting for its response.
        if self.client.server_name == "ruby-lsp":
            from ..lsp.types import DocumentSymbolParams, TextDocumentIdentifier
            try:
                await self.client.send_request(
                    "textDocument/documentSymbol",
                    DocumentSymbolParams(textDocument=TextDocumentIdentifier(uri=uri)),
                    timeout=10.0,
                )
            except Exception:
                pass  # Ignore errors - we just want to ensure didOpen was processed

        return doc


@dataclass
class Session:
    # Nested dict: workspace_root -> server_name -> Workspace
    workspaces: dict[Path, dict[str, Workspace]] = field(default_factory=dict)
    config: Config = field(default_factory=lambda: Config())

    async def get_or_create_workspace(
        self, file_path: Path, workspace_root: Path
    ) -> Workspace:
        workspace_root = workspace_root.resolve()
        server_config = get_server_for_file(file_path, self.config)
        if server_config is None:
            raise ValueError(f"No language server found for {file_path}")

        return await self._get_or_create_workspace_for_server(
            workspace_root, server_config
        )

    async def get_or_create_workspace_for_language(
        self, language_id: str, workspace_root: Path
    ) -> Workspace | None:
        workspace_root = workspace_root.resolve()
        server_config = get_server_for_language(language_id, self.config)
        if server_config is None:
            return None

        return await self._get_or_create_workspace_for_server(
            workspace_root, server_config
        )

    async def _get_or_create_workspace_for_server(
        self, workspace_root: Path, server_config: ServerConfig
    ) -> Workspace:
        if workspace_root not in self.workspaces:
            self.workspaces[workspace_root] = {}

        servers = self.workspaces[workspace_root]
        if server_config.name in servers:
            workspace = servers[server_config.name]
            if workspace.client is None:
                await workspace.start_server()
            return workspace

        workspace = Workspace(root=workspace_root, server_config=server_config)
        await workspace.start_server()
        # Only add to session after successful start
        servers[server_config.name] = workspace

        return workspace

    def get_workspaces_for_root(self, workspace_root: Path) -> list[Workspace]:
        workspace_root = workspace_root.resolve()
        servers = self.workspaces.get(workspace_root, {})
        return list(servers.values())

    def get_any_workspace_for_root(self, workspace_root: Path) -> Workspace | None:
        workspace_root = workspace_root.resolve()
        servers = self.workspaces.get(workspace_root, {})
        if servers:
            return next(iter(servers.values()))
        return None

    async def close_workspace(self, root: Path) -> None:
        root = root.resolve()
        servers = self.workspaces.pop(root, {})
        for workspace in servers.values():
            await workspace.stop_server()

    async def close_all(self) -> None:
        for servers in self.workspaces.values():
            for workspace in servers.values():
                await workspace.stop_server()
        self.workspaces.clear()

    def get_workspace_for_file(self, file_path: Path) -> Workspace | None:
        file_path = file_path.resolve()
        language_id = get_language_id(file_path)
        server_config = get_server_for_language(language_id, self.config)

        for root, servers in self.workspaces.items():
            try:
                file_path.relative_to(root)
                if server_config and server_config.name in servers:
                    return servers[server_config.name]
                if servers:
                    return next(iter(servers.values()))
            except ValueError:
                continue
        return None

    def to_dict(self) -> dict[str, Any]:
        result = {"workspaces": []}
        for root, servers in self.workspaces.items():
            for server_name, ws in servers.items():
                server_pid = None
                if ws.client is not None and ws.client.process.pid is not None:
                    server_pid = ws.client.process.pid
                result["workspaces"].append(
                    {
                        "root": str(root),
                        "server": ws.server_config.name,
                        "server_pid": server_pid,
                        "open_documents": list(ws.open_documents.keys()),
                        "running": ws.client is not None,
                    }
                )
        return result
