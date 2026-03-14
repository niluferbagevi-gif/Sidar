"""Sidar GUI Launcher (Eel bridge).

Bu modül, mevcut `main.py` mimarisini bozmadan Python backend fonksiyonlarını
(E.g. preflight/build_command/execute_command) Eel tabanlı bir web arayüze açar.
"""

from __future__ import annotations

from typing import Any, Dict

try:
    import eel
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise SystemExit(
        "Eel kurulu değil. GUI başlatmak için `pip install eel` çalıştırın."
    ) from exc

from main import build_command, execute_command, preflight


eel.init("web_gui")


@eel.expose
def run_preflight(provider: str) -> Dict[str, Any]:
    """GUI'den çağrılan ön kontrol adımı.

    Not: mevcut `preflight` terminal çıktısı üretir; bu köprü fonksiyonu,
    GUI tarafının akış yönetebilmesi için sade bir durum nesnesi döndürür.
    """
    preflight(provider)
    return {"ok": True, "provider": provider}


@eel.expose
def start_sidar_from_gui(
    mode: str,
    provider: str,
    level: str,
    log_level: str,
    extra_args: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Arayüzden gelen seçimlerle Sidar alt sürecini başlat."""
    extra = extra_args or {}
    cmd = build_command(mode, provider, level, log_level, extra)
    code = execute_command(cmd)
    return {"ok": code == 0, "return_code": code, "command": cmd}


def main() -> None:
    """Eel GUI uygulamasını başlat."""
    eel.start(
        "index.html",
        size=(1100, 760),
        mode="chrome",
    )


if __name__ == "__main__":
    main()
