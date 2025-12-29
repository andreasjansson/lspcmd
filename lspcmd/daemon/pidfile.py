import os
import signal
from pathlib import Path


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
