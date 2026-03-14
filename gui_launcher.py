"""Sidar için bağımsız masaüstü GUI başlatıcı (Eel tabanlı)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

from main import build_command, execute_command, preflight

DEFAULT_LOG_LEVEL = "info"
DEFAULT_WEB_ARGS = {"host": "0.0.0.0", "port": "7860"}


def _normalize_selection(mode: str, provider: str, level: str, log_level: str) -> Dict[str, str]:
    """Arayüzden gelen seçimleri normalize eder ve doğrular."""
    clean = {
        "mode": (mode or "").strip().lower(),
        "provider": (provider or "").strip().lower(),
        "level": (level or "").strip().lower(),
        "log_level": (log_level or DEFAULT_LOG_LEVEL).strip().lower(),
    }

    valid_modes = {"web", "cli"}
    valid_providers = {"ollama", "gemini", "openai", "anthropic"}
    valid_levels = {"restricted", "sandbox", "full"}

    if clean["mode"] not in valid_modes:
        raise ValueError(f"Geçersiz mode: {clean['mode']}")
    if clean["provider"] not in valid_providers:
        raise ValueError(f"Geçersiz provider: {clean['provider']}")
    if clean["level"] not in valid_levels:
        raise ValueError(f"Geçersiz level: {clean['level']}")

    return clean


def _extra_args_for_mode(mode: str) -> Dict[str, str]:
    """Moda göre varsayılan ek parametreleri döndürür."""
    return dict(DEFAULT_WEB_ARGS) if mode == "web" else {}


def launch_from_gui(mode: str, provider: str, level: str, log_level: str = DEFAULT_LOG_LEVEL) -> Dict[str, Any]:
    """GUI seçimleriyle mevcut main.py launcher akışını çalıştırır."""
    try:
        selection = _normalize_selection(mode, provider, level, log_level)
        preflight(selection["provider"])

        cmd = build_command(
            selection["mode"],
            selection["provider"],
            selection["level"],
            selection["log_level"],
            _extra_args_for_mode(selection["mode"]),
        )
        return_code = execute_command(cmd)

        if return_code == 0:
            return {"status": "success", "message": "Sidar başarıyla başlatıldı.", "return_code": 0}

        return {
            "status": "error",
            "message": f"Sidar hata kodu ile sonlandı: {return_code}",
            "return_code": return_code,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc), "return_code": 1}


def start_sidar(mode: str, provider: str, level: str, log_level: str = DEFAULT_LOG_LEVEL) -> Dict[str, Any]:
    """Eel'in doğrudan expose edeceği sabit fonksiyon adı."""
    return launch_from_gui(mode, provider, level, log_level)


def start_gui() -> None:
    """Eel arayüzünü başlatır."""
    try:
        import eel
    except ImportError as exc:
        raise RuntimeError(
            "Eel kurulu değil. Kurmak için: pip install eel"
        ) from exc

    gui_dir = Path(__file__).resolve().parent / "launcher_gui"
    eel.init(str(gui_dir))
    eel.expose(start_sidar)

    eel.start(
        "index.html",
        size=(980, 680),
        position=(220, 120),
    )


if __name__ == "__main__":
    start_gui()