"""Handler for shutdown command."""

from ..rpc import ShutdownParams, ShutdownResult
from .base import HandlerContext


async def handle_shutdown(
    ctx: HandlerContext, params: ShutdownParams, shutdown_callback
) -> ShutdownResult:
    shutdown_callback()
    return ShutdownResult(status="shutting_down")
