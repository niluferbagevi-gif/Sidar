"""Platform-specific executable discovery helpers for CodeManager."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def candidate_lsp_executable_paths(
    binary: str,
    *,
    base_dir: Path,
    python_virtual_env: str = "",
    python_conda_prefix: str = "",
    os_name: str = os.name,
    sys_prefix: str = sys.prefix,
    home_dir: Path | None = None,
) -> list[Path]:
    """Return deterministic LSP binary candidates outside PATH."""
    suffixes = [""]
    if os_name == "nt" and not binary.lower().endswith((".exe", ".cmd", ".bat")):
        suffixes = [".cmd", ".exe", ".bat", ""]

    bin_dir = "Scripts" if os_name == "nt" else "bin"
    candidate_dirs = [
        Path(path) / bin_dir for path in (python_virtual_env, python_conda_prefix) if path
    ]
    candidate_dirs.extend(
        [
            base_dir / ".venv" / bin_dir,
            Path(sys_prefix) / bin_dir,
            (home_dir or Path.home()) / ".local" / "bin",
        ]
    )

    candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate_dir in candidate_dirs:
        for suffix in suffixes:
            candidate = candidate_dir / f"{binary}{suffix}"
            if candidate not in seen:
                candidates.append(candidate)
                seen.add(candidate)
    return candidates


__all__ = ["candidate_lsp_executable_paths"]
