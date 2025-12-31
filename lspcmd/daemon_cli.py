"""Entry point for the lspcmd daemon."""

import asyncio
import sys


def main():
    """Run the lspcmd daemon with MCP server."""
    from .daemon.mcp_server import run_mcp_daemon

    port = 0
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    asyncio.run(run_mcp_daemon(port=port))


if __name__ == "__main__":
    main()
