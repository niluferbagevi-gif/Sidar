"""Validate Sidar's canonical Python, uv and Node toolchain pins."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLCHAIN_FILE = ROOT / "scripts/toolchain.env"


def read_toolchain(path: Path = TOOLCHAIN_FILE) -> dict[str, str]:
    """Parse the assignment-only canonical toolchain file."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not value:
            raise ValueError(f"Geçersiz toolchain satırı: {raw_line!r}")
        values[key] = value
    required = {
        "PYTHON_VERSION",
        "PYTHON_MINOR",
        "UV_VERSION",
        "UV_IMAGE_DIGEST",
        "NODE_VERSION",
        "PLAYWRIGHT_PYTHON_MIN",
        "PLAYWRIGHT_PYTHON_MAX",
        "PLAYWRIGHT_NODE_MIN",
        "PLAYWRIGHT_NODE_MAX",
    }
    if missing := required - values.keys():
        raise ValueError(f"Eksik toolchain anahtarları: {sorted(missing)}")
    return values


def contract_errors(root: Path, pins: dict[str, str]) -> list[str]:
    """Return drift findings across installer, containers and workflows."""
    errors: list[str] = []
    if (root / ".python-version").read_text(encoding="utf-8").strip() != pins["PYTHON_VERSION"]:
        errors.append(".python-version canonical PYTHON_VERSION ile eşleşmiyor")
    uv_image = f"ghcr.io/astral-sh/uv:{pins['UV_VERSION']}@{pins['UV_IMAGE_DIGEST']}"
    for name in ("Dockerfile", "Dockerfile.production"):
        text = (root / name).read_text(encoding="utf-8")
        if f"ARG PYTHON_VERSION={pins['PYTHON_VERSION']}" not in text:
            errors.append(f"{name}: Python pin drift")
        if uv_image not in text:
            errors.append(f"{name}: uv image pin drift")
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        normalized_lines = {line.strip() for line in text.splitlines()}
        python_pins = {
            f'python-version: "{pins["PYTHON_VERSION"]}"',
            f"python-version: '{pins['PYTHON_VERSION']}'",
        }
        if "actions/setup-python@" in text and not python_pins.intersection(normalized_lines):
            errors.append(f"{path.relative_to(root)}: Python pin drift")
        if "astral-sh/setup-uv@" in text and f'version: "{pins["UV_VERSION"]}"' not in text:
            errors.append(f"{path.relative_to(root)}: uv pin drift")
        node_pins = {
            f'node-version: "{pins["NODE_VERSION"]}"',
            f"node-version: '{pins['NODE_VERSION']}'",
        }
        if "actions/setup-node@" in text and not node_pins.intersection(normalized_lines):
            errors.append(f"{path.relative_to(root)}: Node pin drift")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    python_playwright = (
        f'playwright>={pins["PLAYWRIGHT_PYTHON_MIN"]},<{pins["PLAYWRIGHT_PYTHON_MAX"]}'
    )
    if f'"{python_playwright}"' not in pyproject:
        errors.append("pyproject.toml: Python Playwright range drift")
    package_json = (root / "web_ui_react/package.json").read_text(encoding="utf-8")
    node_playwright = (
        f'"@playwright/test": ">={pins["PLAYWRIGHT_NODE_MIN"]} '
        f'<{pins["PLAYWRIGHT_NODE_MAX"]}"'
    )
    if node_playwright not in package_json:
        errors.append("web_ui_react/package.json: Node Playwright range drift")
    return errors


def main() -> int:
    """Fail when a versioned execution surface diverges from toolchain.env."""
    try:
        pins = read_toolchain()
        errors = contract_errors(ROOT, pins)
    except (OSError, ValueError) as exc:
        print(f"Toolchain sözleşmesi okunamadı: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("Toolchain drift:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print(
        f"Toolchain contract OK: Python={pins['PYTHON_VERSION']} "
        f"uv={pins['UV_VERSION']} Node={pins['NODE_VERSION']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
