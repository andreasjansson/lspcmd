import fcntl
import os
import signal
from pathlib import Path


_lock_fd: int | None = None


def read_pid(pid_path: Path) -> int | None:
    if not pid_path.exists():
        return None

    try:
        pid = int(pid_path.read_text().strip())
        return pid
    except (ValueError, OSError):
        return None


def write_pid(pid_path: Path, pid: int) -> None:
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(pid))


def remove_pid(pid_path: Path) -> None:
    try:
        pid_path.unlink()
    except FileNotFoundError:
        pass


def is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def is_daemon_running(pid_path: Path) -> bool:
    pid = read_pid(pid_path)
    if pid is None:
        return False
    return is_process_running(pid)


def stop_daemon(pid_path: Path) -> bool:
    pid = read_pid(pid_path)
    if pid is None:
        return False

    if not is_process_running(pid):
        remove_pid(pid_path)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        remove_pid(pid_path)
        return False


def acquire_daemon_lock(pid_path: Path) -> bool:
    """Try to acquire exclusive lock for daemon startup.

    Returns True if lock acquired (this process should be the daemon).
    Returns False if another daemon is already running.
    """
    global _lock_fd

    lock_path = pid_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        _lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (OSError, BlockingIOError):
        if _lock_fd is not None:
            os.close(_lock_fd)
            _lock_fd = None
        return False


def release_daemon_lock(pid_path: Path) -> None:
    """Release the daemon lock."""
    global _lock_fd

    if _lock_fd is not None:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            os.close(_lock_fd)
        except OSError:
            pass
        _lock_fd = None

    lock_path = pid_path.with_suffix(".lock")
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
