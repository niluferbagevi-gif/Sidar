"""Reusable helpers for source-oriented contract tests.

These helpers keep golden-string shell contract tests aligned with runtime-visible
source after large scripts are split into sourced modules. Prefer behavioral tests
when practical; use these helpers when a contract must assert source structure.
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_BASH_SOURCE_RE = re.compile(r'^source "\$\{SCRIPT_DIR\}/([^" ]+\.sh)"$')
SHELL_FUNCTION_RE = re.compile(r"\n[a-zA-Z_][a-zA-Z0-9_]*\(\) \{")


def expanded_bash_source(
    source_path: Path,
    *,
    source_re: re.Pattern[str] = DEFAULT_BASH_SOURCE_RE,
    root: Path = Path("."),
) -> str:
    """Return a shell source file with matching sourced modules expanded in-place."""
    expanded_lines: list[str] = []
    for line in source_path.read_text(encoding="utf-8").splitlines():
        expanded_lines.append(line)
        match = source_re.match(line.strip())
        if match:
            module_path = root / match.group(1)
            expanded_lines.append(f"# --- expanded from {module_path} for contract tests ---")
            expanded_lines.extend(module_path.read_text(encoding="utf-8").splitlines())
            expanded_lines.append(f"# --- end expanded from {module_path} ---")
    return "\n".join(expanded_lines) + "\n"


def shell_function_body(script: str, name: str) -> str:
    """Return a shell function body from arbitrary shell source text."""
    start_marker = f"{name}() {{"
    start = script.index(start_marker)
    next_function = SHELL_FUNCTION_RE.search(script[start + 1 :])
    if next_function is None:
        return script[start:]
    return script[start : start + 1 + next_function.start()]
