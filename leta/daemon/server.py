"""Daemon server that manages LSP connections."""

import asyncio
import json
import logging
import os
import signal
from pathlib import Path
from typing import Any, Callable, Coroutine

from pydantic import BaseModel

from .handlers import (
    HandlerContext,
    handle_grep,
    handle_files,
    handle_show,
    handle_declaration,
    handle_implementations,
    handle_references,
    handle_subtypes,
    handle_supertypes,
    handle_calls,
    handle_rename,
    handle_move_file,
    handle_restart_workspace,
    handle_remove_workspace,
    handle_shutdown,
    handle_describe_session,
    handle_resolve_symbol,
    handle_raw_lsp_request,
)
from .pidfile import write_pid, remove_pid
from .rpc import (
    GrepParams,
    FilesParams,
    ShowParams,
    DeclarationParams,
    ImplementationsParams,
    ReferencesParams,
    SubtypesParams,
    SupertypesParams,
    CallsParams,
    RenameParams,
    MoveFileParams,
    RestartWorkspaceParams,
    RemoveWorkspaceParams,
    ShutdownParams,
    DescribeSessionParams,
    ResolveSymbolParams,
    RawLspRequestParams,
)
from .session import Session
from ..cache import LMDBCache
from ..lsp.protocol import LSPResponseError, LSPMethodNotSupported, LanguageServerNotFound
from ..utils.config import get_socket_path, get_pid_path, get_log_dir, get_cache_dir, load_config, cleanup_stale_workspace_roots, Config

logger = logging.getLogger(__name__)

DEFAULT_CACHE_SIZE_BYTES = 256 * 1024 * 1024  # 256MB


class DaemonServer:
    def __init__(
        self,
        hover_cache_bytes: int | None = None,
        symbol_cache_bytes: int | None = None,
    ):
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

        self._ctx = HandlerContext(
            session=self.session,
            hover_cache=self._hover_cache,
            symbol_cache=self._symbol_cache,
        )

    async def start(self) -> None:
        self.session.config = load_config()

        removed_roots = cleanup_stale_workspace_roots(self.session.config)
        for root in removed_roots:
            logger.info(f"Removed stale workspace root (no longer exists): {root}")

        socket_path = get_socket_path()
        socket_path.parent.mkdir(parents=True, exist_ok=True)

        if socket_path.exists():
            socket_path.unlink()

        self.server = await asyncio.start_unix_server(
            self._handle_client, path=str(socket_path)
        )

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

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        data: bytes = b""
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
            error_response = {
                "error": f"Internal error: malformed request (got {len(data)} bytes). This is a bug in leta."
            }
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

        handlers: dict[str, tuple[type[BaseModel], Callable]] = {
            "shutdown": (ShutdownParams, self._handle_shutdown_wrapper),
            "describe-session": (DescribeSessionParams, handle_describe_session),
            "show": (ShowParams, handle_show),
            "declaration": (DeclarationParams, handle_declaration),
            "implementations": (ImplementationsParams, handle_implementations),
            "references": (ReferencesParams, handle_references),
            "subtypes": (SubtypesParams, handle_subtypes),
            "supertypes": (SupertypesParams, handle_supertypes),
            "raw-lsp-request": (RawLspRequestParams, handle_raw_lsp_request),
            "rename": (RenameParams, handle_rename),
            "move-file": (MoveFileParams, handle_move_file),
            "grep": (GrepParams, handle_grep),
            "files": (FilesParams, handle_files),
            "calls": (CallsParams, handle_calls),
            "restart-workspace": (RestartWorkspaceParams, handle_restart_workspace),
            "remove-workspace": (RemoveWorkspaceParams, handle_remove_workspace),
            "resolve-symbol": (ResolveSymbolParams, handle_resolve_symbol),
        }

        handler_info = handlers.get(method)
        if not handler_info:
            return {"error": f"Unknown method: {method}"}

        params_class, handler = handler_info

        try:
            typed_params = params_class(**params)
            result = await handler(self._ctx, typed_params)

            if isinstance(result, BaseModel):
                return {"result": result.model_dump(exclude_none=True)}
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

    async def _handle_shutdown_wrapper(self, ctx: HandlerContext, params: ShutdownParams):
        return await handle_shutdown(
            ctx, params, lambda: asyncio.create_task(self._shutdown())
        )


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
