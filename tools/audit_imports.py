#!/usr/bin/env python3
"""Lightweight import audit wrapper used by focused refactor PRs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# This script is meant to be runnable directly (``python tools/audit_imports.py``),
# not only via ``-m`` or from a shell already on the repo root -- a bare direct
# invocation puts this file's own directory (tools/), not the repo root, on
# sys.path[0], so core/ would not be importable below without this. Matches
# the same bootstrap pattern used by scripts/sync_postgres_password.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.utils.trusted_subprocess import run_trusted_command  # noqa: E402


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
    return run_trusted_command(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
