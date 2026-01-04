import asyncio
import logging
import os
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, Callable, Literal, TextIO, overload

from .protocol import encode_message, read_message, LSPProtocolError, LSPResponseError
from .capabilities import get_client_capabilities
from .types import (
    InitializeParams,
    InitializeResult,
    TextDocumentPositionParams,
    DefinitionResponse,
    DeclarationResponse,
    ReferenceParams,
    ReferencesResponse,
    ImplementationResponse,
    TypeDefinitionResponse,
    HoverResponse,
    DocumentSymbolParams,
    DocumentSymbolResponse,
    RenameParams,
    RenameResponseType,
    PrepareCallHierarchyResponse,
    CallHierarchyItemParams,
    CallHierarchyIncomingCallsResponse,
    CallHierarchyOutgoingCallsResponse,
    PrepareTypeHierarchyResponse,
    TypeHierarchyItemParams,
    TypeHierarchySubtypesResponse,
    TypeHierarchySupertypesResponse,
    RenameFilesParams,
    WillRenameFilesResponse,
    ServerCapabilities,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = float(os.environ.get("LETA_REQUEST_TIMEOUT", "30"))


class LSPClient:
    process: asyncio.subprocess.Process
    workspace_root: str
    init_options: dict[str, object]
    server_name: str | None
    log_file: Path | None
    _request_id: int
    _pending_requests: dict[int, asyncio.Future[object]]
    _reader_task: asyncio.Task[None] | None
    _initialized: bool
    _server_capabilities: ServerCapabilities
    _notification_handlers: dict[
        str, Callable[[dict[str, object] | None], Awaitable[None]]
    ]
    _log_handle: TextIO | None
    _service_ready: asyncio.Event
    _needs_service_ready: bool
    _active_progress_tokens: set[str | int]
    _indexing_done: asyncio.Event
    _stderr_task: asyncio.Task[None] | None

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        workspace_root: str,
        init_options: dict[str, object] | None = None,
        server_name: str | None = None,
        log_file: Path | None = None,
    ):
        self.process = process
        self.workspace_root = workspace_root
        self.init_options = init_options or {}
        self.server_name = server_name
        self.log_file = log_file
        self._request_id = 0
        self._pending_requests = {}
        self._reader_task = None
        self._initialized = False
        self._server_capabilities = ServerCapabilities()
        self._notification_handlers = {}
        self._log_handle = None
        self._service_ready = asyncio.Event()
        self._needs_service_ready = server_name == "jdtls"
        self._active_progress_tokens = set()
        self._indexing_done = asyncio.Event()
        # rust-analyzer uses experimental/serverStatus to signal quiescence
        # other servers may not send progress notifications, so assume ready
        if server_name != "rust-analyzer":
            self._indexing_done.set()
        self._stderr_task = None

    @property
    def stdin(self) -> asyncio.StreamWriter:
        assert self.process.stdin is not None
        return self.process.stdin

    @property
    def stdout(self) -> asyncio.StreamReader:
        assert self.process.stdout is not None
        return self.process.stdout

    async def start(self) -> None:
        self._reader_task = asyncio.create_task(self._read_loop())
        if self.process.stderr:
            if self.log_file:
                self.log_file.parent.mkdir(parents=True, exist_ok=True)
                self._log_handle = open(self.log_file, "a")
            self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self._initialize()

    async def _drain_stderr(self) -> None:
        try:
            while True:
                assert self.process.stderr is not None
                data = await self.process.stderr.read(4096)
                if not data:
                    break
                text = data.decode(errors="replace")
                if self._log_handle:
                    self._log_handle.write(text)
                    self._log_handle.flush()
                logger.debug(f"Server stderr: {text[:200]}")
        except Exception:
            pass
        finally:
            if self._log_handle:
                self._log_handle.close()
                self._log_handle = None

    async def stop(self) -> None:
        if self._initialized:
            try:
                await asyncio.wait_for(self.send_request("shutdown", None), timeout=5.0)
                await self.send_notification("exit", None)
            except Exception as e:
                logger.warning(f"Error during shutdown: {e}")

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()

    async def _initialize(self) -> None:
        from .types import InitializeParams, WorkspaceFolder, ClientCapabilities

        init_params = InitializeParams(
            processId=os.getpid(),
            rootUri=self.workspace_root,
            rootPath=self.workspace_root.replace("file://", ""),
            capabilities=ClientCapabilities.model_validate(get_client_capabilities()),
            workspaceFolders=[
                WorkspaceFolder(
                    uri=self.workspace_root, name=self.workspace_root.split("/")[-1]
                )
            ],
            initializationOptions=self.init_options if self.init_options else None,
        )

        result = await self.send_request("initialize", init_params)
        self._server_capabilities = result.capabilities
        await self.send_notification("initialized", {})
        self._initialized = True

    @overload
    async def send_request(
        self,
        method: Literal["initialize"],
        params: InitializeParams,
        timeout: float | None = None,
    ) -> InitializeResult: ...

    @overload
    async def send_request(
        self,
        method: Literal["shutdown"],
        params: None,
        timeout: float | None = None,
    ) -> None: ...

    @overload
    async def send_request(
        self,
        method: Literal["textDocument/definition"],
        params: TextDocumentPositionParams,
        timeout: float | None = None,
    ) -> DefinitionResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["textDocument/declaration"],
        params: TextDocumentPositionParams,
        timeout: float | None = None,
    ) -> DeclarationResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["textDocument/references"],
        params: ReferenceParams,
        timeout: float | None = None,
    ) -> ReferencesResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["textDocument/implementation"],
        params: TextDocumentPositionParams,
        timeout: float | None = None,
    ) -> ImplementationResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["textDocument/typeDefinition"],
        params: TextDocumentPositionParams,
        timeout: float | None = None,
    ) -> TypeDefinitionResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["textDocument/hover"],
        params: TextDocumentPositionParams,
        timeout: float | None = None,
    ) -> HoverResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["textDocument/documentSymbol"],
        params: DocumentSymbolParams,
        timeout: float | None = None,
    ) -> DocumentSymbolResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["textDocument/rename"],
        params: RenameParams,
        timeout: float | None = None,
    ) -> RenameResponseType: ...

    @overload
    async def send_request(
        self,
        method: Literal["textDocument/prepareCallHierarchy"],
        params: TextDocumentPositionParams,
        timeout: float | None = None,
    ) -> PrepareCallHierarchyResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["callHierarchy/incomingCalls"],
        params: CallHierarchyItemParams,
        timeout: float | None = None,
    ) -> CallHierarchyIncomingCallsResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["callHierarchy/outgoingCalls"],
        params: CallHierarchyItemParams,
        timeout: float | None = None,
    ) -> CallHierarchyOutgoingCallsResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["textDocument/prepareTypeHierarchy"],
        params: TextDocumentPositionParams,
        timeout: float | None = None,
    ) -> PrepareTypeHierarchyResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["typeHierarchy/subtypes"],
        params: TypeHierarchyItemParams,
        timeout: float | None = None,
    ) -> TypeHierarchySubtypesResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["typeHierarchy/supertypes"],
        params: TypeHierarchyItemParams,
        timeout: float | None = None,
    ) -> TypeHierarchySupertypesResponse: ...

    @overload
    async def send_request(
        self,
        method: Literal["workspace/willRenameFiles"],
        params: RenameFilesParams,
        timeout: float | None = None,
    ) -> WillRenameFilesResponse: ...

    @overload
    async def send_request(
        self,
        method: str,
        params: Any,
        timeout: float | None = None,
    ) -> Any: ...

    async def send_request(
        self,
        method: str,
        params: Any,
        timeout: float | None = None,
    ) -> Any:
        from pydantic import BaseModel

        self._request_id += 1
        request_id = self._request_id

        params_dict: dict[str, Any] | list[Any] | None
        if params is None:
            params_dict = None
        elif isinstance(params, BaseModel):
            params_dict = params.model_dump(exclude_none=True)
        else:
            params_dict = params

        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params_dict is not None:
            message["params"] = params_dict

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending_requests[request_id] = future

        encoded = encode_message(message)
        logger.debug(f"LSP REQUEST [{request_id}] {method}: {params_dict}")
        self.stdin.write(encoded)
        await self.stdin.drain()

        try:
            raw_result = await asyncio.wait_for(
                future, timeout=timeout or REQUEST_TIMEOUT
            )
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise LSPResponseError(
                -1, f"Request {method} timed out after {timeout or REQUEST_TIMEOUT}s"
            )

        return _parse_response(method, raw_result)

    async def send_notification(
        self, method: str, params: dict[str, Any] | list[Any] | None
    ) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params

        self.stdin.write(encode_message(message))
        await self.stdin.drain()

        logger.info(f"LSP NOTIFICATION {method}: {params}")

    async def _read_loop(self) -> None:
        try:
            while True:
                logger.debug("Waiting to read message from server")
                message = await read_message(self.stdout)
                logger.debug(
                    f"Received message: id={message.get('id')}, method={message.get('method')}"
                )
                await self._handle_message(message)
        except LSPProtocolError as e:
            logger.error(f"Protocol error: {e}")
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"Error in read loop: {e}")
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(e)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        if "id" in message:
            if "method" in message:
                await self._handle_server_request(message)
            else:
                self._handle_response(message)
        else:
            await self._handle_notification(message)

    def _handle_response(self, message: dict[str, Any]) -> None:
        request_id = message["id"]
        future = self._pending_requests.pop(request_id, None)

        if future is None:
            logger.warning(f"Received response for unknown request: {request_id}")
            return

        if "error" in message:
            error = message["error"]
            logger.debug(f"LSP RESPONSE [{request_id}] ERROR: {error}")
            future.set_exception(
                LSPResponseError(
                    error.get("code", -1),
                    error.get("message", "Unknown error"),
                    error.get("data"),
                )
            )
        else:
            result = message.get("result")
            logger.debug(f"LSP RESPONSE [{request_id}]: {type(result).__name__}")
            future.set_result(result)

    async def _handle_server_request(self, message: dict[str, Any]) -> None:
        method = message["method"]
        request_id = message["id"]

        logger.debug(f"Received server request: {method} (id={request_id})")

        result: Any = None
        error: dict[str, Any] | None = None

        if method == "workspace/configuration":
            result = [{}] * len(message.get("params", {}).get("items", []))
        elif method == "window/workDoneProgress/create":
            result = None
        elif method == "client/registerCapability":
            result = None
        elif method == "workspace/applyEdit":
            result = {"applied": True}
        else:
            error = {"code": -32601, "message": f"Method not found: {method}"}

        response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error:
            response["error"] = error
        else:
            response["result"] = result

        encoded_response = encode_message(response)
        logger.debug(
            f"Sending response for server request {request_id}: {len(encoded_response)} bytes"
        )
        self.stdin.write(encoded_response)
        await self.stdin.drain()
        logger.debug(f"Sent response for server request {request_id}")

    async def _handle_notification(self, message: dict[str, Any]) -> None:
        method = message["method"]
        params = message.get("params")

        logger.debug(f"Received notification: {method}")

        if method == "language/status" and params:
            if params.get("type") == "ServiceReady":
                logger.info(f"Server {self.server_name} is now ServiceReady")
                self._service_ready.set()

        if method == "experimental/serverStatus" and params:
            self._handle_server_status(params)

        if method == "$/progress" and params:
            self._handle_progress(params)

        handler = self._notification_handlers.get(method)
        if handler:
            await handler(params)

    def _handle_progress(self, params: dict[str, Any]) -> None:
        token: str | int | None = params.get("token")
        value = params.get("value", {})
        kind = value.get("kind")

        if token is None:
            return

        if kind == "begin":
            self._active_progress_tokens.add(token)
            self._indexing_done.clear()
            logger.debug(f"Progress begin: {token} - {value.get('title', '')}")
        elif kind == "end":
            self._active_progress_tokens.discard(token)
            if not self._active_progress_tokens:
                self._indexing_done.set()
                logger.debug("All progress complete, server ready")
            else:
                logger.debug(
                    f"Progress end: {token}, {len(self._active_progress_tokens)} remaining"
                )

    def _handle_server_status(self, params: dict[str, Any]) -> None:
        """Handle experimental/serverStatus notification from rust-analyzer.
        
        This notification indicates when rust-analyzer has finished all background
        work (quiescent=true) and its health status.
        """
        health = params.get("health", "ok")
        quiescent = params.get("quiescent", False)
        
        logger.debug(f"Server status: health={health}, quiescent={quiescent}")
        
        if quiescent and health != "error":
            self._indexing_done.set()
            logger.info(f"Server {self.server_name} is quiescent (ready)")
        else:
            self._indexing_done.clear()
            logger.debug(f"Server {self.server_name} is busy (not quiescent)")

    def on_notification(
        self,
        method: str,
        handler: Callable[[dict[str, object] | None], Awaitable[None]],
    ) -> None:
        self._notification_handlers[method] = handler

    async def wait_for_service_ready(self, timeout: float = 30.0) -> bool:
        if not self._needs_service_ready:
            return True
        if self._service_ready.is_set():
            return True
        try:
            await asyncio.wait_for(self._service_ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout waiting for {self.server_name} to become ServiceReady"
            )
            return False

    async def wait_for_indexing(self, timeout: float = 30.0) -> bool:
        if self._indexing_done.is_set():
            return True
        try:
            await asyncio.wait_for(self._indexing_done.wait(), timeout=timeout)
            logger.debug(f"Server {self.server_name} finished indexing")
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for {self.server_name} to finish indexing")
            return False

    @property
    def capabilities(self) -> ServerCapabilities:
        return self._server_capabilities


def _parse_response(method: str, raw_result: Any) -> Any:
    from .types import (
        InitializeResult,
        Location,
        LocationLink,
        Hover,
        DocumentSymbol,
        SymbolInformation,
        WorkspaceEdit,
        CallHierarchyItem,
        CallHierarchyIncomingCall,
        CallHierarchyOutgoingCall,
        TypeHierarchyItem,
    )

    if raw_result is None:
        return None

    if method == "initialize":
        return InitializeResult.model_validate(raw_result)

    if method == "shutdown":
        return None

    if method in (
        "textDocument/definition",
        "textDocument/declaration",
        "textDocument/implementation",
        "textDocument/typeDefinition",
    ):
        if isinstance(raw_result, list):
            if not raw_result:
                return []
            if "targetUri" in raw_result[0]:
                return [LocationLink.model_validate(item) for item in raw_result]
            return [Location.model_validate(item) for item in raw_result]
        return Location.model_validate(raw_result)

    if method == "textDocument/references":
        if isinstance(raw_result, list):
            return [Location.model_validate(item) for item in raw_result]
        return None

    if method == "textDocument/hover":
        return Hover.model_validate(raw_result)

    if method == "textDocument/documentSymbol":
        if isinstance(raw_result, list):
            if not raw_result:
                return []
            if "location" in raw_result[0]:
                return [SymbolInformation.model_validate(item) for item in raw_result]
            return [DocumentSymbol.model_validate(item) for item in raw_result]
        return None

    if method == "textDocument/rename":
        return WorkspaceEdit.model_validate(raw_result)

    if method == "textDocument/prepareCallHierarchy":
        if isinstance(raw_result, list):
            return [CallHierarchyItem.model_validate(item) for item in raw_result]
        return None

    if method == "callHierarchy/incomingCalls":
        if isinstance(raw_result, list):
            return [
                CallHierarchyIncomingCall.model_validate(item) for item in raw_result
            ]
        return None

    if method == "callHierarchy/outgoingCalls":
        if isinstance(raw_result, list):
            return [
                CallHierarchyOutgoingCall.model_validate(item) for item in raw_result
            ]
        return None

    if method == "textDocument/prepareTypeHierarchy":
        if isinstance(raw_result, list):
            return [TypeHierarchyItem.model_validate(item) for item in raw_result]
        return None

    if method in ("typeHierarchy/subtypes", "typeHierarchy/supertypes"):
        if isinstance(raw_result, list):
            return [TypeHierarchyItem.model_validate(item) for item in raw_result]
        return None

    if method == "workspace/willRenameFiles":
        return WorkspaceEdit.model_validate(raw_result)

    return raw_result
