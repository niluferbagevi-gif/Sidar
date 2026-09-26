"""Thin security-policy adapter for CodeManager filesystem operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class CodeSecurityAdapter:
    """Small wrapper that keeps CodeManager IO code independent from policy details."""

    def __init__(self, security: Any) -> None:
        """Wrap the security manager used for path permission checks."""
        self._security = security

    def can_read(self, path: str) -> bool:
        """Return whether the security policy allows reading ``path``."""
        return bool(self._security.can_read(path))

    def can_write(self, path: str) -> bool:
        """Return whether the security policy allows writing ``path``."""
        return bool(self._security.can_write(path))

    def safe_write_denial(self, path: str) -> str:
        """Build a write-denied message that suggests a safe alternative path."""
        safe = str(self._security.get_safe_write_path(Path(path).name))
        return f"[OpenClaw] Yazma yetkisi yok: {path}\n  Güvenli alternatif: {safe}"

    def is_path_under(self, path: str, base_dir: Path) -> bool:
        """Return whether ``path`` resolves inside ``base_dir``."""
        return bool(self._security.is_path_under(path, base_dir))
