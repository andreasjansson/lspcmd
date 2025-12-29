import asyncio
import logging
import os
from typing import Any, Callable

from .protocol import encode_message, read_message, LSPProtocolError, LSPResponseError
from .capabilities import get_client_capabilities

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = float(os.environ.get("LSPCMD_REQUEST_TIMEOUT", "30"))


class LSPClient:
    def __init__(self, process: asyncio.subprocess.Process, workspace_root: str):
        self.process = process
        self.workspace_root = workspace_root
        self._request_id = 0
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task | None = None
        self._initialized = False
        self._server_capabilities: dict[str, Any] = {}
        self._notification_handlers: dict[str, Callable] = {}

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
        await self._initialize()

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
        import os
        result = await self.send_request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self.workspace_root,
                "rootPath": self.workspace_root.replace("file://", ""),
                "capabilities": get_client_capabilities(),
                "workspaceFolders": [
                    {"uri": self.workspace_root, "name": self.workspace_root.split("/")[-1]}
                ],
            },
        )
        self._server_capabilities = result.get("capabilities", {})
        await self.send_notification("initialized", {})
        self._initialized = True

    async def send_request(self, method: str, params: dict | list | None, timeout: float | None = None) -> Any:
        self._request_id += 1
        request_id = self._request_id

        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending_requests[request_id] = future

        encoded = encode_message(message)
        logger.debug(f"Sending request {request_id}: {method} ({len(encoded)} bytes)")
        self.stdin.write(encoded)
        await self.stdin.drain()
        logger.debug(f"Sent request {request_id}: {method}, waiting for response")

        try:
            return await asyncio.wait_for(future, timeout=timeout or REQUEST_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise LSPResponseError(-1, f"Request {method} timed out after {timeout or REQUEST_TIMEOUT}s")

    async def send_notification(self, method: str, params: dict | list | None) -> None:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params

        self.stdin.write(encode_message(message))
        await self.stdin.drain()

        logger.debug(f"Sent notification: {method}")

    async def _read_loop(self) -> None:
        try:
            while True:
                logger.debug("Waiting to read message from server")
                message = await read_message(self.stdout)
                logger.debug(f"Received message: id={message.get('id')}, method={message.get('method')}")
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
            future.set_exception(
                LSPResponseError(error.get("code", -1), error.get("message", "Unknown error"), error.get("data"))
            )
        else:
            future.set_result(message.get("result"))

    async def _handle_server_request(self, message: dict[str, Any]) -> None:
        method = message["method"]
        request_id = message["id"]

        logger.debug(f"Received server request: {method} (id={request_id})")

        result: Any = None
        error: dict | None = None

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

        response = {"jsonrpc": "2.0", "id": request_id}
        if error:
            response["error"] = error
        else:
            response["result"] = result

        self.stdin.write(encode_message(response))
        await self.stdin.drain()

    async def _handle_notification(self, message: dict[str, Any]) -> None:
        method = message["method"]
        params = message.get("params")

        logger.debug(f"Received notification: {method}")

        handler = self._notification_handlers.get(method)
        if handler:
            await handler(params)

    def on_notification(self, method: str, handler: Callable) -> None:
        self._notification_handlers[method] = handler

    @property
    def capabilities(self) -> dict[str, Any]:
        return self._server_capabilities
