#!/usr/bin/env python3
"""Preflight doctor for Sidar production-readiness environment prerequisites."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "web_ui_react"


@dataclass(frozen=True)
class DoctorCheck:
    """Single production-readiness prerequisite result."""

    name: str
    ok: bool
    detail: str
    action: str = ""


def run_command(command: Sequence[str], *, cwd: Path = REPO_ROOT, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run a command and capture text output without raising."""

    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def short_output(result: subprocess.CompletedProcess[str]) -> str:
    """Return a compact diagnostic string for a subprocess result."""

    combined = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return combined.splitlines()[-1] if combined else f"exit={result.returncode}"


def check_uv_available() -> DoctorCheck:
    """Check whether uv is available on PATH."""

    uv_path = shutil.which("uv")
    if uv_path:
        version = run_command([uv_path, "--version"], timeout=15)
        detail = version.stdout.strip() or uv_path
        return DoctorCheck("uv", True, detail)
    return DoctorCheck("uv", False, "uv bulunamadı", "uv kurun: https://docs.astral.sh/uv/")


def check_python_version() -> DoctorCheck:
    """Check that the active Python matches the repository support window."""

    version = sys.version_info
    ok = version.major == 3 and version.minor == 11
    detail = f"{sys.executable} -> {version.major}.{version.minor}.{version.micro}"
    return DoctorCheck("python", ok, detail, "Python 3.11 sanal ortamı/uv ortamı kullanın.")


def candidate_portaudio_headers() -> list[Path]:
    """Return likely PortAudio header locations."""

    paths = [
        Path("/usr/include/portaudio.h"),
        Path("/usr/local/include/portaudio.h"),
        Path("/opt/homebrew/include/portaudio.h"),
        Path("/usr/local/opt/portaudio/include/portaudio.h"),
    ]
    include_env = os.environ.get("C_INCLUDE_PATH", "")
    for item in include_env.split(os.pathsep):
        if item:
            paths.append(Path(item) / "portaudio.h")
    return paths


def check_portaudio_header() -> DoctorCheck:
    """Check whether portaudio.h is visible before PyAudio builds."""

    for header in candidate_portaudio_headers():
        if header.exists():
            return DoctorCheck("portaudio.h", True, str(header))
    pkg_config = shutil.which("pkg-config")
    if pkg_config:
        result = run_command([pkg_config, "--exists", "portaudio-2.0"], timeout=15)
        if result.returncode == 0:
            return DoctorCheck("portaudio.h", True, "pkg-config portaudio-2.0 hazır")
    return DoctorCheck(
        "portaudio.h",
        False,
        "PortAudio header bulunamadı",
        "bash scripts/install_ci_system_deps.sh çalıştırın (Debian/Ubuntu: portaudio19-dev).",
    )


def check_system_deps_script() -> DoctorCheck:
    """Run the project system-dependency checker in no-install mode."""

    result = run_command(["bash", "scripts/install_ci_system_deps.sh", "--check"], timeout=60)
    return DoctorCheck(
        "system-deps",
        result.returncode == 0,
        short_output(result),
        "Eksikleri kurmak için: bash scripts/install_ci_system_deps.sh",
    )


def check_uv_sync_dry_run() -> DoctorCheck:
    """Check whether uv can resolve the full locked extras without mutating the env."""

    uv_path = shutil.which("uv")
    if not uv_path:
        return DoctorCheck("uv-sync-dry-run", False, "uv yok", "Önce uv kurun.")
    help_result = run_command([uv_path, "sync", "--help"], timeout=30)
    if "--dry-run" not in help_result.stdout:
        return DoctorCheck(
            "uv-sync-dry-run",
            False,
            "uv sync --dry-run desteklenmiyor",
            "uv sürümünü güncelleyin veya manuel kontrol: uv sync --frozen --all-extras",
        )
    result = run_command([uv_path, "sync", "--frozen", "--all-extras", "--dry-run"], timeout=120)
    return DoctorCheck(
        "uv-sync-dry-run",
        result.returncode == 0,
        short_output(result),
        "Lockfile/full extras çözümü için: bash scripts/install_ci_system_deps.sh && uv sync --frozen --all-extras",
    )


def check_python_tool_imports() -> DoctorCheck:
    """Check dev quality tool imports required by production-readiness."""

    modules = ["bandit", "pytest", "pytest_benchmark"]
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    if not missing:
        return DoctorCheck("python-dev-tools", True, ", ".join(modules))
    return DoctorCheck(
        "python-dev-tools",
        False,
        "eksik: " + ", ".join(missing),
        "uv sync --frozen --all-extras veya hızlı test araçları için uv sync --frozen --extra dev-light",
    )


def check_frontend_node_modules() -> DoctorCheck:
    """Check whether frontend npm dependencies are installed."""

    node_modules = FRONTEND_DIR / "node_modules"
    playwright_pkg = node_modules / "@playwright" / "test"
    if node_modules.is_dir() and playwright_pkg.exists():
        return DoctorCheck("frontend-node-modules", True, "web_ui_react/node_modules hazır")
    return DoctorCheck(
        "frontend-node-modules",
        False,
        "web_ui_react/node_modules veya @playwright/test eksik",
        "cd web_ui_react && npm ci",
    )


def check_playwright_chromium() -> DoctorCheck:
    """Check Playwright browser cache or externally managed Chromium executable."""

    external = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "")
    if external:
        path = Path(external)
        return DoctorCheck(
            "playwright-chromium",
            path.exists(),
            f"PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH={path}",
            "Geçerli Chromium executable path verin.",
        )
    if (FRONTEND_DIR / "node_modules" / "@playwright" / "test").exists():
        script = """
const fs = require('node:fs');
const { chromium } = require('@playwright/test');
const executablePath = chromium.executablePath();
if (!fs.existsSync(executablePath)) process.exit(1);
process.stdout.write(executablePath);
"""
        result = run_command(["node", "-e", script], cwd=FRONTEND_DIR, timeout=30)
        if result.returncode == 0:
            return DoctorCheck("playwright-chromium", True, result.stdout.strip())
    browsers_path = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "~/.cache/ms-playwright")).expanduser()
    cache_hint = browsers_path if browsers_path.exists() else Path("~/.cache/ms-playwright").expanduser()
    return DoctorCheck(
        "playwright-chromium",
        False,
        f"Chromium cache bulunamadı ({cache_hint})",
        "cd web_ui_react && npx playwright install chromium veya PLAYWRIGHT_BROWSERS_PATH/PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH kullanın.",
    )


def check_benchmark_baseline() -> DoctorCheck:
    """Check for a pytest-benchmark baseline file."""

    benchmark_dir = REPO_ROOT / ".benchmarks"
    baseline_name = os.environ.get("BENCHMARK_COMPARE_NAME", os.environ.get("BENCHMARK_BASELINE_NAME", "baseline"))
    patterns = [f"*_{baseline_name}.json", "*.json"]
    matches: list[Path] = []
    if benchmark_dir.is_dir():
        for pattern in patterns:
            matches = sorted(benchmark_dir.rglob(pattern))
            if matches:
                break
    if matches:
        return DoctorCheck("benchmark-baseline", True, str(matches[-1].relative_to(REPO_ROOT)))
    return DoctorCheck(
        "benchmark-baseline",
        False,
        f".benchmarks/*_{baseline_name}.json bulunamadı",
        "make benchmark-seed && make production-readiness",
    )


def collect_checks() -> list[DoctorCheck]:
    """Collect all production-readiness doctor checks."""

    return [
        check_uv_available(),
        check_python_version(),
        check_system_deps_script(),
        check_portaudio_header(),
        check_uv_sync_dry_run(),
        check_python_tool_imports(),
        check_frontend_node_modules(),
        check_playwright_chromium(),
        check_benchmark_baseline(),
    ]


def print_human(checks: Sequence[DoctorCheck]) -> None:
    """Print a human-readable doctor report."""

    print("Production-readiness doctor")
    print("===========================")
    for check in checks:
        icon = "✅" if check.ok else "❌"
        print(f"{icon} {check.name}: {check.detail}")
        if not check.ok and check.action:
            print(f"   action: {check.action}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the production-readiness doctor."""

    args = list(argv if argv is not None else sys.argv[1:])
    json_output = "--json" in args
    checks = collect_checks()
    if json_output:
        print(json.dumps([check.__dict__ for check in checks], ensure_ascii=False, indent=2))
    else:
        print_human(checks)
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
