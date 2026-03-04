"""PyWebView launcher için Python-JS köprü katmanı."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from config import Config


class LauncherAPI:
    """Frontend'in çağırdığı API metotları."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.cfg = Config()
        self._last_process: subprocess.Popen[str] | None = None

    def _safe_text(self, value: Any, fallback: str) -> str:
        text = str(value).strip()
        return text or fallback

    def get_defaults(self) -> dict[str, Any]:
        return {
            "provider": self.cfg.AI_PROVIDER,
            "level": self.cfg.ACCESS_LEVEL,
            "mode": "web",
            "log": os.getenv("LOG_LEVEL", "INFO").upper(),
            "model": self.cfg.CODING_MODEL,
            "host": self.cfg.WEB_HOST,
            "port": self.cfg.WEB_PORT,
            "launcherHint": "Vite/React için --launcher-url veya SIDAR_LAUNCHER_URL kullanabilirsiniz.",
        }

    def preview_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        cmd = self._build_command(payload)
        return {"command": shlex.join(cmd)}

    def health(self) -> dict[str, Any]:
        return {
            "python": sys.executable,
            "cwd": str(self.base_dir),
            "pywebview": self._module_exists("webview"),
        }

    def start_system(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._last_process and self._last_process.poll() is None:
            return {
                "ok": False,
                "message": "Zaten çalışan bir süreç var. Önce mevcut süreci kapatın.",
            }

        cmd = self._build_command(payload)
        self._last_process = subprocess.Popen(  # noqa: S603
            cmd,
            cwd=self.base_dir,
            text=True,
        )
        return {
            "ok": True,
            "pid": self._last_process.pid,
            "message": "Sistem başlatıldı.",
            "command": shlex.join(cmd),
        }

    def _build_command(self, payload: dict[str, Any]) -> list[str]:
        data = payload or {}
        provider = self._safe_text(data.get("provider"), self.cfg.AI_PROVIDER)
        level = self._safe_text(data.get("level"), self.cfg.ACCESS_LEVEL)
        mode = self._safe_text(data.get("mode"), "web")
        log = self._safe_text(data.get("log"), "INFO").upper()

        args = ["--provider", provider, "--level", level, "--log", log]

        if mode == "cli":
            model = self._safe_text(data.get("model"), self.cfg.CODING_MODEL)
            cmd = [sys.executable, str(self.base_dir / "cli.py"), *args, "--model", model]
            return cmd

        host = self._safe_text(data.get("host"), self.cfg.WEB_HOST)
        port = int(data.get("port", self.cfg.WEB_PORT) or self.cfg.WEB_PORT)
        cmd = [
            sys.executable,
            str(self.base_dir / "web_server.py"),
            *args,
            "--host",
            host,
            "--port",
            str(port),
        ]
        return cmd

    @staticmethod
    def _module_exists(module_name: str) -> bool:
        try:
            __import__(module_name)
            return True
        except Exception:
            return False
