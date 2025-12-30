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

    from .daemon.pidfile import acquire_daemon_lock, release_daemon_lock
    from .utils.config import get_pid_path
    
    pid_path = get_pid_path()
    if not acquire_daemon_lock(pid_path):
        sys.exit(0)
    
    try:
        from .daemon.server import run_daemon
        asyncio.run(run_daemon())
    finally:
        release_daemon_lock(pid_path)


if __name__ == "__main__":
    main()
