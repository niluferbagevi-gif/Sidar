#!/usr/bin/env python3
"""Lightweight import audit wrapper used by focused refactor PRs."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Python files for unused imports.")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    command = [
        "uv",
        "run",
        "ruff",
        "check",
        "--select",
        "F401,F821,I001",
        *[str(path) for path in args.paths],
    ]
    return subprocess.run(
        command, check=False
    ).returncode  # Hardcoded uv/ruff command; no shell.  # nosec B603


if __name__ == "__main__":
    raise SystemExit(main())
