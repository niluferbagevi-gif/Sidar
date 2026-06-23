"""Pytest sandbox orchestration helpers for CodeManager."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from managers.code.docker import sanitize_docker_image, to_int


def build_pytest_preflight_command(manager: Any, command: str) -> str:
    """Build sandbox preflight that finds pytest from image/project venv or uv."""
    pytest_args = " ".join(shlex.quote(arg) for arg in manager._extract_pytest_args(command))
    if not pytest_args:
        pytest_args = "-q"
    return "\n".join(
        [
            "set -eu",
            "for py in /workspace/.venv/bin/python /app/.venv/bin/python python; do",
            '  if [ "$py" = python ]; then',
            "    command -v python >/dev/null 2>&1 || continue",
            "  else",
            '    [ -x "$py" ] || continue',
            "  fi",
            "  if \"$py\" -c 'import pytest' >/dev/null 2>&1; then",
            f'    exec "$py" -m pytest {pytest_args}',
            "  fi",
            "done",
            "if command -v uv >/dev/null 2>&1 && [ -f pyproject.toml ]; then",
            "  uv sync --frozen --all-extras >/tmp/sidar-uv-sync.log 2>&1 && exec uv run pytest "
            f"{pytest_args}",
            "  cat /tmp/sidar-uv-sync.log >&2 || true",
            "fi",
            "echo 'pytest bulunamadı: sandbox imajında pytest yok ve proje/image venv veya uv bootstrap başarısız. '"
            "'DOCKER_TEST_IMAGE değerini proje Dockerfile ile build edilmiş Sidar imajına ayarlayın '"
            "'ya da uv sync --frozen --all-extras ile .venv hazırlayın.' >&2",
            "exit 127",
        ]
    )


def build_shell_preflight_command(manager: Any, command: str) -> str:
    """Wrap sandbox shell commands with PATH and uv/pytest preflight."""
    if manager._command_invokes_pytest(command):
        return manager._build_pytest_preflight_command(command)

    preflight = [
        "export PATH=/workspace/.venv/bin:/app/.venv/bin:/root/.local/bin:/home/sidaruser/.local/bin:/usr/local/bin:/bin:/usr/bin:$PATH",
    ]
    if manager._command_requires_uv_tooling(command):
        preflight.extend(
            [
                "if ! command -v uv >/dev/null 2>&1; then",
                "  for _uv_candidate in /workspace/.venv/bin/uv /app/.venv/bin/uv "
                "/root/.local/bin/uv /home/sidaruser/.local/bin/uv /usr/local/bin/uv /bin/uv; do",
                '    if [ -x "$_uv_candidate" ]; then',
                '      export PATH="$(dirname "$_uv_candidate"):$PATH"',
                "      break",
                "    fi",
                "  done",
                "fi",
                "if ! command -v uv >/dev/null 2>&1; then",
                "  if command -v python >/dev/null 2>&1; then",
                "    python -m pip install --no-cache-dir uv >/tmp/sidar-uv-bootstrap.log 2>&1 || true",
                "    if [ -x /usr/local/bin/uv ]; then export PATH=/usr/local/bin:$PATH; fi",
                "  fi",
                "fi",
                "if ! command -v uv >/dev/null 2>&1; then",
                "  echo 'uv bulunamadı: sandbox imajında uv bulunamadı ve otomatik bootstrap başarısız oldu. '"
                "'Proje Dockerfile imajını build edip DOCKER_TEST_IMAGE=sidar:latest olarak ayarlayın. '"
                "'Bootstrap logu: /tmp/sidar-uv-bootstrap.log' >&2",
                "  cat /tmp/sidar-uv-bootstrap.log >&2 || true",
                "  exit 127",
                "fi",
            ]
        )
    preflight.append(command)
    return "\n".join(preflight)


def run_shell_in_sandbox(
    manager: Any,
    command: str,
    cwd: str | None = None,
    image: str | None = None,
) -> tuple[bool, str]:
    """Run a shell command inside the Docker sandbox."""
    if not manager.security.can_execute():
        return False, "[OpenClaw] Sandbox komutu çalıştırma yetkisi yok."
    if not command or not command.strip():
        return False, "⚠ Çalıştırılacak komut belirtilmedi."

    work_dir = Path(cwd or manager.base_dir).resolve()
    if not work_dir.exists() or not work_dir.is_dir():
        return False, f"Geçersiz çalışma dizini: {work_dir}"
    if not manager.security_adapter.is_path_under(str(work_dir), manager.base_dir):
        return False, f"[OpenClaw] Sandbox çalışma dizini proje kökü dışında: {work_dir}"

    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False, "Docker CLI bulunamadı; sandbox komutu çalıştırılamadı."

    limits = manager._resolve_sandbox_limits()
    safe_image = sanitize_docker_image(manager._select_shell_sandbox_image(command, image))
    sandbox_command = manager._build_shell_preflight_command(command)
    docker_cmd = [
        docker_bin,
        "run",
        "--rm",
        f"--memory={limits['memory']}",
        f"--cpus={limits['cpus']}",
        f"--pids-limit={limits['pids_limit']}",
        f"--network={limits['network_mode']}",
        "-v",
        f"{work_dir}:/workspace",
        "-w",
        "/workspace",
        "--entrypoint",
        "sh",
    ]
    runtime = manager._resolve_runtime()
    if runtime:
        docker_cmd.extend(["--runtime", runtime])
    docker_cmd.extend([safe_image, "-lc", sandbox_command])

    try:
        result = subprocess.run(  # nosec B603
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=to_int(limits["timeout"], 10),
            cwd=str(manager.base_dir),
        )
    except FileNotFoundError:
        return False, "Docker CLI bulunamadı; sandbox komutu çalıştırılamadı."
    except subprocess.TimeoutExpired:
        return False, f"⚠ Zaman aşımı! Sandbox komutu {limits['timeout']} saniyeden uzun sürdü ve durduruldu."
    except Exception as exc:
        return False, f"Sandbox komutu hatası: {exc}"

    output_parts = []
    if result.stdout.strip():
        output_parts.append(result.stdout.strip())
    if result.stderr.strip():
        output_parts.append(f"[stderr]\n{result.stderr.strip()}")
    combined = "\n".join(output_parts) if output_parts else "(komut çıktı üretmedi)"
    if len(combined) > manager.max_output_chars:
        combined = combined[: manager.max_output_chars] + (
            f"\n\n... [ÇIKTI KIRPILDI: Maksimum {manager.max_output_chars} karakter sınırı aşıldı] ..."
        )
    if result.returncode != 0:
        return False, f"Sandbox komutu başarısız (çıkış kodu: {result.returncode}):\n{combined}"
    return True, combined


def analyze_pytest_output(output: str) -> dict[str, Any]:
    text = str(output or "")
    findings: list[dict[str, Any]] = []
    coverage_targets: list[dict[str, Any]] = []
    failure_targets: list[dict[str, Any]] = []

    summary_match = re.search(
        r"(?P<failed>\d+)\s+failed|(?P<passed>\d+)\s+passed|(?P<errors>\d+)\s+error",
        text.lower(),
    )
    summary = summary_match.group(0) if summary_match else ""

    coverage_pattern = re.compile(
        r"^(?P<path>[A-Za-z0-9_./\\-]+)\s+(?P<stmts>\d+)\s+(?P<miss>\d+)\s+(?P<cover>\d+)%\s+(?P<missing>.+)$",
        re.MULTILINE,
    )
    for match in coverage_pattern.finditer(text):
        path = match.group("path").strip()
        if path.upper() == "TOTAL" or path.startswith("tests/"):
            continue
        missing = match.group("missing").strip()
        missing_segments = [item.strip() for item in missing.split(",") if item.strip()]
        missing_branches = [item for item in missing_segments if "->" in item]
        missing_lines = [item for item in missing_segments if "->" not in item]
        finding = {
            "finding_type": "missing_coverage",
            "target_path": path,
            "summary": f"Eksik coverage satırları: {missing}",
            "missing_lines": missing,
            "coverage_percent": int(match.group("cover")),
            "missing_line_ranges": missing_lines,
            "missing_branch_arcs": missing_branches,
        }
        coverage_targets.append(finding)
        findings.append(finding)

    failure_pattern = re.compile(
        r"_{3,}\s+(?P<target>[^_\n]+?)\s+_{3,}\n(?P<body>.*?)(?=\n_{3,}|\n=+|\Z)",
        re.DOTALL,
    )
    for match in failure_pattern.finditer(text):
        target = match.group("target").strip()
        body = match.group("body").strip()
        path_match = re.search(r"([A-Za-z0-9_./\\-]+\.py):\d+", body)
        target_path = path_match.group(1) if path_match else ""
        finding = {
            "finding_type": "test_failure",
            "target_path": target_path,
            "summary": target,
            "details": body[:1000],
        }
        failure_targets.append(finding)
        findings.append(finding)

    if not failure_targets and re.search(r"\b\d+\s+failed\b", text.lower()):
        path_match = re.search(r"([A-Za-z0-9_./\\-]+\.py):\d+", text)
        failure_targets.append(
            {
                "finding_type": "test_failure",
                "target_path": path_match.group(1) if path_match else "",
                "summary": "pytest failure detected",
                "details": text[:1000],
            }
        )
        findings.append(failure_targets[-1])

    return {
        "summary": summary,
        "findings": findings,
        "coverage_targets": coverage_targets,
        "failure_targets": failure_targets,
        "has_failures": bool(failure_targets),
        "has_coverage_gaps": bool(coverage_targets),
    }


def normalize_pytest_command(command: str) -> str:
    raw_command = (command or "").strip() or "pytest -q"
    normalized = ""
    pytest_cmd_pattern = re.compile(
        r"(?:^|\s)((?:uv\s+run\s+pytest)|(?:python\s+-m\s+pytest)|pytest)(?:\s+.*)?$",
        re.IGNORECASE,
    )
    for line in raw_command.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.startswith(("-", "*")):
            candidate = candidate[1:].strip()
        match = pytest_cmd_pattern.search(candidate)
        if match:
            normalized = candidate[match.start(1) :].strip()
            break
    if not normalized:
        normalized = raw_command
    if " #" in normalized:
        normalized = normalized.split(" #", 1)[0].rstrip()
    return normalized


def run_pytest_and_collect(manager: Any, command: str = "pytest -q", cwd: str | None = None) -> dict[str, Any]:
    normalized = normalize_pytest_command(command)
    if not re.match(r"^(pytest|python\s+-m\s+pytest|uv\s+run\s+pytest)\b", normalized, re.IGNORECASE):
        return {
            "success": False,
            "command": normalized,
            "output": "Yalnızca pytest komutları desteklenir.",
            "analysis": analyze_pytest_output(""),
        }
    sandbox_command = manager._build_pytest_preflight_command(normalized)
    ok, output = manager.run_shell_in_sandbox(sandbox_command, cwd=cwd, image=manager.docker_test_image)
    return {
        "success": ok,
        "command": normalized,
        "output": output,
        "analysis": analyze_pytest_output(output),
    }


__all__ = [
    "analyze_pytest_output",
    "build_pytest_preflight_command",
    "build_shell_preflight_command",
    "normalize_pytest_command",
    "run_pytest_and_collect",
    "run_shell_in_sandbox",
]
