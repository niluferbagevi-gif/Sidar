"""Validation and lightweight lint/post-processing helpers for CodeManager."""

from __future__ import annotations

import ast
import json
import logging
import shutil

# Commands are fixed tool invocations, not shell input.
import subprocess  # nosec B404
from pathlib import Path

logger = logging.getLogger(__name__)


def post_process_written_file(target: Path) -> None:
    """Run best-effort formatting for generated Python files."""
    if target.suffix != ".py":
        return
    ruff_bin = shutil.which("ruff")
    if not ruff_bin:
        return
    try:
        subprocess.run(  # nosec B603
            [ruff_bin, "format", str(target)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:  # pragma: no cover - best effort only
        logger.debug("Post-process ruff format atlandı (%s): %s", target, exc)


def validate_python_syntax(code: str) -> tuple[bool, str]:
    """Validate Python code syntax without executing it."""
    try:
        ast.parse(code)
        return True, "Sözdizimi geçerli."
    except SyntaxError as exc:
        return False, f"Sözdizimi hatası — Satır {exc.lineno}: {exc.msg}"


def validate_json(content: str) -> tuple[bool, str]:
    """Validate JSON content."""
    try:
        json.loads(content)
        return True, "Geçerli JSON."
    except json.JSONDecodeError as exc:
        return False, f"JSON hatası — Satır {exc.lineno}: {exc.msg}"


__all__ = ["post_process_written_file", "validate_json", "validate_python_syntax"]
