"""Process lifecycle helpers for Sidar web runtime shutdown."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

SAFE_PS_PATHS = ("/bin/ps", "/usr/bin/ps")


def resolve_safe_ps_binary(*, safe_paths: tuple[str, ...] = SAFE_PS_PATHS) -> str | None:
    """Resolve `ps` only from trusted absolute system paths."""
    for candidate in safe_paths:
        try:
            path = Path(candidate)
            if path.is_file() and os.access(candidate, os.X_OK):
                return candidate
        except Exception:  # nosec B112  # invalid candidates are skipped deliberately.
            continue
    try:
        which_path = shutil.which("ps")
    except Exception:
        which_path = None
    if which_path and which_path in safe_paths:
        return which_path
    return None


def list_child_ollama_pids(
    *,
    resolve_psutil_module: Callable[[], Any],
    current_pid: int | None = None,
    os_name: str | None = None,
    safe_ps_binary: str | None = None,
) -> list[int]:
    """Return child process IDs that look like local `ollama serve` processes."""
    parent_pid = int(current_pid if current_pid is not None else os.getpid())
    pids: list[int] = []
    try:
        psutil_module = resolve_psutil_module()
        current = psutil_module.Process(parent_pid)
        for child in current.children(recursive=False):
            with contextlib.suppress(Exception):
                comm = str(child.name() or "").strip().lower()
                args = " ".join(child.cmdline() or []).strip().lower()
                if comm == "ollama" or "ollama serve" in args:
                    pids.append(int(child.pid))
        return sorted(set(pids))
    except Exception:
        if (os_name or os.name) == "nt":
            return []

    ps_binary = safe_ps_binary if safe_ps_binary is not None else resolve_safe_ps_binary()
    if ps_binary is None:
        return []

    try:
        raw = subprocess.check_output(  # nosec B603  # safe absolute ps path.
            [ps_binary, "-eo", "pid=,ppid=,comm=,args="],
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []

    for line in raw.decode("utf-8", errors="ignore").splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid_str, ppid_str, comm, args = parts
        if not pid_str.isdigit() or not ppid_str.isdigit():
            continue
        if int(ppid_str) != parent_pid:
            continue
        normalized_comm = comm.strip().lower()
        normalized_args = args.strip().lower()
        if normalized_comm == "ollama" or "ollama serve" in normalized_args:
            pids.append(int(pid_str))
    return sorted(set(pids))


def reap_child_processes_nonblocking() -> int:
    """Reap zombie child processes with waitpid(WNOHANG)."""
    reaped = 0
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        except Exception:
            break
        if pid <= 0:
            break
        reaped += 1
    return reaped


def terminate_process_pids(
    pids: list[int],
    *,
    sigterm: int,
    sigkill: int,
    kill_func: Callable[[int, int], object] = os.kill,
    sleep_func: Callable[[float], object] = time.sleep,
    grace_seconds: float = 0.15,
) -> None:
    """Terminate process IDs with TERM followed by KILL after a grace period."""
    for pid in pids:
        with contextlib.suppress(Exception):
            kill_func(pid, sigterm)

    if pids and grace_seconds > 0:
        sleep_func(grace_seconds)
        for pid in pids:
            with contextlib.suppress(Exception):
                kill_func(pid, sigkill)
