"""Entry point for the lspcmd daemon."""

import asyncio


def main():
    """Run the lspcmd daemon with Unix socket server."""
    from .daemon.server import run_daemon

    asyncio.run(run_daemon())


if __name__ == "__main__":
    main()
