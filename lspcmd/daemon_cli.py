import asyncio
import os
import sys


def main():
    if os.fork() > 0:
        sys.exit(0)

    os.setsid()

    if os.fork() > 0:
        sys.exit(0)

    sys.stdin.close()

    from .daemon.server import run_daemon
    asyncio.run(run_daemon())


if __name__ == "__main__":
    main()
