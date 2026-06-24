"""Docker sandbox helpers extracted from the CodeManager facade."""

from __future__ import annotations

import logging
import re
import subprocess  # nosec B404
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

logger = logging.getLogger(__name__)

DOCKER_MEMORY_RE = re.compile(r"^\d+(\.\d+)?[bkmgBKMG]?$")
DOCKER_CPUS_RE = re.compile(r"^\d+(\.\d+)?$")
DOCKER_NETWORK_ALLOWED = frozenset({"none", "bridge", "host", "container:default"})
DOCKER_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@\-]*$")
PROJECT_TEST_IMAGE_CANDIDATES = (
    "sidar:latest",
    "sidar-gpu:latest",
    "sidar-ai:latest",
    "sidar-ai-gpu:latest",
)
LEGACY_PROJECT_IMAGE_PREFIXES = {"sidar-ai": "sidar", "sidar-ai-gpu": "sidar-gpu"}


class DockerSandboxOwner(Protocol):
    cfg: Any
    docker_mem_limit: str
    docker_exec_timeout: int
    docker_nano_cpus: int
    docker_image: str
    max_output_chars: int
    base_dir: Path


def to_int(value: object, default: int) -> int:
    """Safely coerce an arbitrary object into an int."""
    try:
        return int(cast("int | float | str | bytes | bytearray", value))
    except (TypeError, ValueError):
        return default


def sanitize_docker_token(
    value: object, *, pattern: re.Pattern[str], default: str, kind: str
) -> str:
    """Validate a token before appending it to a Docker CLI argument."""
    candidate = str(value if value is not None else "").strip()
    if not candidate or candidate.startswith("-") or not pattern.fullmatch(candidate):
        logger.warning(
            "Güvensiz docker %s değeri reddedildi (%r) → varsayılan %r kullanılacak.",
            kind,
            candidate,
            default,
        )
        return default
    return candidate


def sanitize_docker_network(value: object) -> str:
    candidate = str(value if value is not None else "").strip().lower()
    if candidate not in DOCKER_NETWORK_ALLOWED:
        logger.warning(
            "Güvensiz docker network değeri reddedildi (%r) → 'none' kullanılacak.",
            candidate,
        )
        return "none"
    return candidate


def sanitize_docker_image(value: object) -> str:
    candidate = str(value if value is not None else "").strip()
    if not candidate or candidate.startswith("-") or not DOCKER_IMAGE_RE.fullmatch(candidate):
        logger.warning(
            "Güvensiz docker image değeri reddedildi (%r) → 'python:3.11-slim' kullanılacak.",
            candidate,
        )
        return "python:3.11-slim"
    return candidate


def resolve_sandbox_limits(
    owner: DockerSandboxOwner, default_limits: dict[str, object]
) -> dict[str, object]:
    """Normalize Docker cgroup limits from config and manager defaults."""
    limits = dict(default_limits)
    cfg = getattr(owner, "cfg", None)
    cfg_limits = getattr(cfg, "SANDBOX_LIMITS", {}) or {}
    limits.update(cfg_limits)

    memory = str(
        cfg_limits.get("memory") or owner.docker_mem_limit or limits.get("memory") or "256m"
    ).strip()
    cpus = str(limits.get("cpus") or "0.5").strip()
    pids_limit = to_int(limits.get("pids_limit", 64), 64)
    timeout = to_int(limits.get("timeout", owner.docker_exec_timeout or 10), 10)
    network_mode = str(limits.get("network") or "none").strip().lower()

    nano_cpus = owner.docker_nano_cpus
    if cpus:  # pragma: no cover
        try:
            cpu_val = float(cpus)
            if cpu_val > 0:
                nano_cpus = int(cpu_val * 1_000_000_000)
        except (TypeError, ValueError):
            logger.warning(
                "Geçersiz SANDBOX_LIMITS['cpus'] değeri: %s. DOCKER_NANO_CPUS kullanılacak.",
                cpus,
            )

    if pids_limit < 1:
        pids_limit = 64
    if timeout < 1:
        timeout = 10

    return {
        "memory": memory,
        "cpus": cpus,
        "nano_cpus": nano_cpus,
        "pids_limit": pids_limit,
        "timeout": timeout,
        "network_mode": network_mode,
    }


def build_docker_cli_command(code: str, limits: dict[str, object], *, image: str) -> list[str]:
    """Build the safe ``docker run`` argv used by the CLI sandbox fallback."""
    safe_memory = sanitize_docker_token(
        limits.get("memory"), pattern=DOCKER_MEMORY_RE, default="256m", kind="memory"
    )
    safe_cpus = sanitize_docker_token(
        limits.get("cpus"), pattern=DOCKER_CPUS_RE, default="0.5", kind="cpus"
    )
    safe_pids = to_int(limits.get("pids_limit"), 64)
    if safe_pids < 1:
        safe_pids = 64
    safe_network = sanitize_docker_network(limits.get("network_mode"))
    safe_image = sanitize_docker_image(image)
    return [
        "docker",
        "run",
        "--rm",
        f"--memory={safe_memory}",
        f"--cpus={safe_cpus}",
        f"--pids-limit={safe_pids}",
        f"--network={safe_network}",
        "--entrypoint",
        "python",
        safe_image,
        "-c",
        code,
    ]


def execute_code_with_docker_cli(
    owner: DockerSandboxOwner,
    code: str,
    limits: dict[str, object],
    *,
    run_command: Callable[..., Any] = subprocess.run,
) -> tuple[bool, str]:
    """Execute Python code through the Docker CLI fallback."""
    docker_cmd = build_docker_cli_command(code, limits, image=owner.docker_image)
    result = run_command(
        docker_cmd,
        capture_output=True,
        text=True,
        timeout=to_int(limits["timeout"], 10),
        cwd=str(owner.base_dir),
    )
    output = (result.stdout + result.stderr).strip()
    if len(output) > owner.max_output_chars:
        output = output[: owner.max_output_chars] + (
            f"\n\n... [ÇIKTI KIRPILDI: Maksimum {owner.max_output_chars} karakter sınırı aşıldı] ..."
        )
    if result.returncode != 0:
        return False, f"REPL Hatası (Docker CLI Sandbox):\n{output or '(çıktı yok)'}"
    return True, f"REPL Çıktısı (Docker CLI Sandbox):\n{output or '(kod çalıştı, çıktı yok)'}"
