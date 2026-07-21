"""Launcher subprocess helpers: command building and live output streaming.

Extracted verbatim from ``main.py`` (previously ~130 lines of a single
1400+ line launcher module). ``main.py`` keeps thin wrappers around these
functions for backward compatibility with existing call sites and tests.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

# Terminal renkleri (ANSI). main.py'nin kendi CYAN/GREEN/RESET sabitleriyle
# birebir aynı, sabit/asla değişmeyen literal değerler olduğu için burada
# bağımsız olarak tutuluyor — main.py'ye geri import etmek gereksiz bir
# dairesel bağımlılık (launcher.process -> main -> launcher.process) yaratırdı.
_CYAN = "\033[96m"
_GREEN = "\033[92m"
_RESET = "\033[0m"


def build_command(
    mode: str, provider: str, level: str, log: str, extra_args: dict[str, str]
) -> list[str]:
    """Seçimlere göre çalıştırılacak terminal komutunu inşa eder."""
    valid_modes = {"web", "cli"}
    valid_providers = {"ollama", "gemini", "openai", "anthropic"}
    valid_levels = {"restricted", "sandbox", "full"}
    valid_logs = {"info", "debug", "warning", "error"}

    if mode not in valid_modes:
        raise ValueError(f"Geçersiz mode: {mode}")
    if provider not in valid_providers:
        raise ValueError(f"Geçersiz provider: {provider}")
    if level not in valid_levels:
        raise ValueError(f"Geçersiz level: {level}")
    if log not in valid_logs:
        raise ValueError(f"Geçersiz log seviyesi: {log}")

    target_script = "web_server.py" if mode == "web" else "cli.py"
    cmd = [sys.executable, target_script, "--provider", provider, "--level", level, "--log", log]

    if mode == "cli" and provider == "ollama" and extra_args.get("model"):
        cmd.extend(["--model", extra_args["model"]])
    elif mode == "web":
        cmd.extend(
            [
                "--host",
                extra_args.get("host", "127.0.0.1"),
                "--port",
                extra_args.get("port", "8000"),
            ]
        )

    return cmd


def launcher_child_env() -> dict[str, str]:
    """Environment for child processes launched by main.py without duplicate config banners.

    Does not force SIDAR_SKIP_BOOT_CHECKS: the launcher's own
    validate_critical_settings() call in main() only covers the code path that
    runs through main(), so the child must keep running its own boot check
    (web_server.py's lifespan) as a real, independent safety net rather than a
    permanently-disabled one. Whatever the user explicitly set for
    SIDAR_SKIP_BOOT_CHECKS in their own environment still passes through via
    os.environ.copy().
    """
    child_env = os.environ.copy()
    child_env["SIDAR_CONFIG_QUIET"] = "true"
    child_env["SIDAR_LAUNCHED_BY_MAIN"] = "true"
    child_env["SIDAR_BANNER_SHOWN"] = "1"
    return child_env


def format_cmd(cmd: list[str]) -> str:
    """Komutu terminalde güvenli/görsel şekilde yazdırmak için quote eder."""
    return " ".join(shlex.quote(part) for part in cmd)


def stream_pipe(
    pipe: Any, target: Any, prefix: str = "", color: str = "", mirror: bool = True
) -> None:
    """Backward-compatible helper to stream lines from a pipe."""
    for line in iter(pipe.readline, ""):
        payload = f"{prefix} {line}" if prefix else line
        target.write(payload)
        target.flush()
        if mirror:
            print(f"{color}{prefix}{_RESET} {line}", end="")
    with contextlib.suppress(OSError, ValueError):
        pipe.close()


def run_with_streaming(
    cmd: list[str], child_log_path: str | None, *, base_dir: Any, cwd: str
) -> int:
    """Child process çıktısını canlı ve sıralı biçimde (stdout+stderr) loglar.

    ``base_dir``/``cwd`` are threaded through explicitly (rather than derived
    from this module's own ``__file__`` or imported from main.py) so callers
    resolve their own current values at call time — including main.py's
    ``cfg`` global, which is reassigned on env reload and monkeypatched
    directly in tests, and main.py's own directory (not this module's, which
    now lives one level down in launcher/) as the child process cwd.
    """
    process = subprocess.Popen(  # nosec B603  # komut listesi launcher tarafından güvenli şekilde üretilir.
        cmd,
        cwd=cwd or ".",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=launcher_child_env(),
    )

    if process.stdout is None or process.stderr is None:
        raise RuntimeError("Child process stdout/stderr pipe oluşturulamadı.")

    f = None
    log_path = None
    if child_log_path:
        candidate = Path(child_log_path)
        resolved_base_dir = Path(str(base_dir or ".")).resolve()
        log_path = candidate if candidate.is_absolute() else (resolved_base_dir / candidate)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        f = open(log_path, "w", encoding="utf-8")
        f.write(f"$ {format_cmd(cmd)}\n\n")
        f.flush()

    return_code = 1
    try:
        stream_pipe(process.stdout, f or sys.stdout, "[stdout]", _CYAN, mirror=True)
        stream_pipe(process.stderr, f or sys.stdout, "[stderr]", _CYAN, mirror=True)
        return_code = process.wait()
    finally:
        with contextlib.suppress(Exception):
            process.stdout.close()
        with contextlib.suppress(Exception):
            process.stderr.close()
        poll = getattr(process, "poll", None)
        terminate = getattr(process, "terminate", None)
        kill = getattr(process, "kill", None)
        still_running = (callable(poll) and poll() is None) or (poll is None)
        if still_running and callable(terminate):
            terminate()
            try:
                process.wait(timeout=3)
            except (subprocess.TimeoutExpired, TimeoutError):
                if callable(kill):  # pragma: no cover
                    kill()  # pragma: no cover
        if f:
            f.write(f"\n[exit_code]\n{return_code}\n")
            f.close()
            print(f"{_GREEN}📝 Child process çıktısı kaydedildi: {log_path}{_RESET}")

    return return_code


__all__ = [
    "build_command",
    "format_cmd",
    "launcher_child_env",
    "run_with_streaming",
    "stream_pipe",
]
