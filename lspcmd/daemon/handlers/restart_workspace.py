"""Handler for restart-workspace command."""

from pathlib import Path

from ..rpc import RestartWorkspaceParams, RestartWorkspaceResult
from .base import HandlerContext


async def handle_restart_workspace(
    ctx: HandlerContext, params: RestartWorkspaceParams
) -> RestartWorkspaceResult:
    workspace_root = Path(params.workspace_root).resolve()
    servers = ctx.session.workspaces.get(workspace_root, {})

    if servers:
        restarted: list[str] = []
        for server_name, workspace in list(servers.items()):
            if workspace.client is not None:
                await workspace.stop_server()
            await workspace.start_server()
            restarted.append(server_name)
        return RestartWorkspaceResult(restarted=restarted)

    languages = ctx.discover_languages(workspace_root)
    if not languages:
        raise ValueError(f"No supported source files found in {workspace_root}")

    started: list[str] = []
    for lang_id in languages:
        workspace = await ctx.session.get_or_create_workspace_for_language(
            lang_id, workspace_root
        )
        if workspace and workspace.client:
            started.append(workspace.server_config.name)

    return RestartWorkspaceResult(restarted=started)
