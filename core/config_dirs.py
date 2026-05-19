from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any


def resolve_base_dir(config_file: str) -> Path:
    """Resolve repository base directory from config module path."""
    return Path(config_file).resolve().parent


def repair_log_file_permissions(log_file: Path) -> None:
    """Repair write permissions for log file when possible."""
    if not log_file.exists():
        return
    if os.access(log_file, os.W_OK):
        return

    uid = os.getuid() if hasattr(os, "getuid") else None
    gid = os.getgid() if hasattr(os, "getgid") else None
    if uid is not None and gid is not None and hasattr(os, "chown"):
        with contextlib.suppress(PermissionError, OSError):
            os.chown(log_file, uid, gid)

    current_mode = log_file.stat().st_mode & 0o777
    with contextlib.suppress(PermissionError, OSError):
        log_file.chmod(current_mode | 0o200)


def initialize_directories(required_dirs: list[Path], logger: Any) -> bool:
    """Create required directories and return overall success."""
    success = True
    for folder in required_dirs:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            logger.debug("✅ Dizin hazır: %s", folder.name)
        except Exception as exc:
            logger.error("❌ Dizin oluşturulamadı (%s): %s", folder.name, exc)
            success = False
    return success
