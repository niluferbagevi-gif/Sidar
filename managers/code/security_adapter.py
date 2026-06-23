"""Thin security-policy adapter for CodeManager filesystem operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class CodeSecurityAdapter:
    """Small wrapper that keeps CodeManager IO code independent from policy details."""

    def __init__(self, security: Any) -> None:
        self._security = security

    def can_read(self, path: str) -> bool:
        return bool(self._security.can_read(path))

    def can_write(self, path: str) -> bool:
        return bool(self._security.can_write(path))

    def safe_write_denial(self, path: str) -> str:
        safe = str(self._security.get_safe_write_path(Path(path).name))
        return f"[OpenClaw] Yazma yetkisi yok: {path}\n  Güvenli alternatif: {safe}"

    def is_path_under(self, path: str, base_dir: Path) -> bool:
        return bool(self._security.is_path_under(path, base_dir))
