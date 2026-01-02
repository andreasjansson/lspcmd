"""Handler for describe-session command."""

import os

from ..rpc import (
    DescribeSessionParams,
    DescribeSessionResult,
    CacheInfo,
    WorkspaceInfo,
)
from .base import HandlerContext


async def handle_describe_session(
    ctx: HandlerContext, params: DescribeSessionParams
) -> DescribeSessionResult:
    workspaces: list[WorkspaceInfo] = []
    for root, servers in ctx.session.workspaces.items():
        for server_name, workspace in servers.items():
            workspaces.append(WorkspaceInfo(
                root=str(root),
                language=server_name,
                server_pid=workspace.client.server_process.pid if workspace.client and workspace.client.server_process else None,
                open_documents=list(workspace.open_documents.keys()),
            ))

    return DescribeSessionResult(
        daemon_pid=os.getpid(),
        caches={
            "hover_cache": CacheInfo(
                current_bytes=ctx.hover_cache.current_bytes,
                max_bytes=ctx.hover_cache.max_bytes,
                entries=len(ctx.hover_cache),
            ),
            "symbol_cache": CacheInfo(
                current_bytes=ctx.symbol_cache.current_bytes,
                max_bytes=ctx.symbol_cache.max_bytes,
                entries=len(ctx.symbol_cache),
            ),
        },
        workspaces=workspaces,
    )
