import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..lsp.client import LSPClient
from ..lsp.protocol import LanguageServerNotFound, LanguageServerStartupError
from ..utils.config import get_log_dir
from ..utils.uri import path_to_uri
from ..utils.text import get_language_id, read_file_content
from ..servers.registry import ServerConfig, get_server_for_file, get_server_for_language

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

        logger.info(f"Server {self.server_config.name} initialized")

    def _get_init_options(self) -> dict[str, Any]:
        if self.server_config.name == "gopls":
            return {"linksInHover": False}
        return {}

    def _get_server_env(self) -> dict[str, str]:
        import os
        env = os.environ.copy()
        home = os.path.expanduser("~")
        extra_paths = [
            f"{home}/go/bin",
            f"{home}/.cargo/bin",
            f"{home}/.local/bin",
            "/usr/local/bin",
            "/opt/homebrew/bin",
        ]
        current_path = env.get("PATH", "")
        env["PATH"] = ":".join(extra_paths) + ":" + current_path
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
    # Nested dict: workspace_root -> server_name -> Workspace
    workspaces: dict[Path, dict[str, Workspace]] = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    async def get_or_create_workspace(self, file_path: Path, workspace_root: Path) -> Workspace:
        workspace_root = workspace_root.resolve()
        server_config = get_server_for_file(file_path, self.config)
        if server_config is None:
            raise ValueError(f"No language server found for {file_path}")

        return await self._get_or_create_workspace_for_server(workspace_root, server_config)

    async def get_or_create_workspace_for_language(self, language_id: str, workspace_root: Path) -> Workspace | None:
        workspace_root = workspace_root.resolve()
        server_config = get_server_for_language(language_id, self.config)
        if server_config is None:
            return None

        return await self._get_or_create_workspace_for_server(workspace_root, server_config)

    async def _get_or_create_workspace_for_server(self, workspace_root: Path, server_config: ServerConfig) -> Workspace:
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
                result["workspaces"].append({
                    "root": str(root),
                    "server": ws.server_config.name,
                    "open_documents": list(ws.open_documents.keys()),
                    "running": ws.client is not None,
                })
        return result
