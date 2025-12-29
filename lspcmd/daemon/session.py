import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..lsp.client import LSPClient
from ..utils.uri import path_to_uri
from ..utils.text import get_language_id, read_file_content
from ..servers.registry import ServerConfig, get_server_for_file

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

        process = await asyncio.create_subprocess_exec(
            *self.server_config.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.root),
        )

        self.client = LSPClient(process, path_to_uri(self.root))
        await self.client.start()

        logger.info(f"Server {self.server_config.name} initialized")

    async def stop_server(self) -> None:
        if self.client is None:
            return

        logger.info(f"Stopping {self.server_config.name}")
        await self.client.stop()
        self.client = None
        self.open_documents.clear()

    async def ensure_document_open(self, path: Path) -> OpenDocument:
        uri = path_to_uri(path)

        if uri in self.open_documents:
            doc = self.open_documents[uri]
            current_content = read_file_content(path)
            if current_content != doc.content:
                doc.version += 1
                doc.content = current_content
                assert self.client is not None
                await self.client.send_notification(
                    "textDocument/didChange",
                    {
                        "textDocument": {"uri": uri, "version": doc.version},
                        "contentChanges": [{"text": current_content}],
                    },
                )
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

        return doc


@dataclass
class Session:
    workspaces: dict[Path, Workspace] = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    async def get_or_create_workspace(self, file_path: Path, workspace_root: Path) -> Workspace:
        workspace_root = workspace_root.resolve()

        if workspace_root in self.workspaces:
            workspace = self.workspaces[workspace_root]
            if workspace.client is None:
                await workspace.start_server()
            return workspace

        server_config = get_server_for_file(file_path, self.config)
        if server_config is None:
            raise ValueError(f"No language server found for {file_path}")

        workspace = Workspace(root=workspace_root, server_config=server_config)
        self.workspaces[workspace_root] = workspace
        await workspace.start_server()

        return workspace

    async def close_workspace(self, root: Path) -> None:
        root = root.resolve()
        workspace = self.workspaces.pop(root, None)
        if workspace:
            await workspace.stop_server()

    async def close_all(self) -> None:
        for workspace in list(self.workspaces.values()):
            await workspace.stop_server()
        self.workspaces.clear()

    def get_workspace_for_file(self, file_path: Path) -> Workspace | None:
        file_path = file_path.resolve()
        for root, workspace in self.workspaces.items():
            try:
                file_path.relative_to(root)
                return workspace
            except ValueError:
                continue
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspaces": [
                {
                    "root": str(root),
                    "server": ws.server_config.name,
                    "open_documents": list(ws.open_documents.keys()),
                    "running": ws.client is not None,
                }
                for root, ws in self.workspaces.items()
            ]
        }
