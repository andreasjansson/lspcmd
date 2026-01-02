"""Handler for raw-lsp-request command."""

from pathlib import Path
from typing import Any

from ..rpc import RawLspRequestParams
from .base import HandlerContext


async def handle_raw_lsp_request(
    ctx: HandlerContext, params: RawLspRequestParams
) -> Any:
    workspace_root = Path(params.workspace_root).resolve()
    lsp_method = params.method
    lsp_params = params.params
    language = params.language

    workspace = await ctx.session.get_or_create_workspace_for_language(
        language, workspace_root
    )
    if not workspace or not workspace.client:
        raise ValueError(f"No LSP server for language: {language}")

    await workspace.client.wait_for_service_ready()

    return await workspace.client.send_request(lsp_method, lsp_params)
