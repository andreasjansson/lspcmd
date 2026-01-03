"""Handler for shutdown command."""

from collections.abc import Callable

from ..rpc import ShutdownParams, ShutdownResult
from .base import HandlerContext


async def handle_shutdown(
    _ctx: HandlerContext, _params: ShutdownParams, shutdown_callback: Callable[[], None]
) -> ShutdownResult:
    shutdown_callback()
    return ShutdownResult(status="shutting_down")
