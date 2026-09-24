"""Command-line argument parsing for the Sidar launcher (``main.py``)."""

from __future__ import annotations

import argparse
import os


def build_arg_parser(*, session_filename: str) -> argparse.ArgumentParser:
    """Build the launcher's ``argparse`` parser."""
    parser = argparse.ArgumentParser(description="Sidar Akıllı Başlatıcı")
    parser.add_argument(
        "--quick", choices=["cli", "web"], help="Sihirbazı atla ve belirtilen modda hızlı başlat"
    )
    parser.add_argument(
        "--skip-wizard",
        action="store_true",
        help="Sihirbaz sorularını atla ve config/default seçimlerle başlat",
    )
    parser.add_argument(
        "--last",
        action="store_true",
        help=f"Son {session_filename} sihirbaz seçimleriyle başlat",
    )
    parser.add_argument(
        "--use-last",
        action="store_true",
        help=f"--last ile aynı: son {session_filename} seçimlerini kullan",
    )
    parser.add_argument(
        "--provider",
        choices=["ollama", "gemini", "openai", "anthropic"],
        help="Hızlı başlat için AI sağlayıcı",
    )
    parser.add_argument(
        "--level",
        choices=["restricted", "sandbox", "full"],
        help="Hızlı başlat için erişim seviyesi",
    )
    parser.add_argument("--model", help="Hızlı CLI başlat için Ollama modeli")
    parser.add_argument("--host", help="Hızlı web başlat için host adresi")
    parser.add_argument("--port", help="Hızlı web başlat için port numarası")
    parser.add_argument("--log", default="info", help="Log seviyesi (info, debug, warning)")
    parser.add_argument(
        "--capture-output",
        action="store_true",
        help="Alt süreç stdout/stderr çıktısını launcherdan yakala ve yazdır",
    )
    parser.add_argument(
        "--child-log",
        help="Alt süreç stdout/stderr çıktısını dosyaya kaydet (ör. logs/child.log)",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Doctor preflight için tüm auto-fix önerilerini tek onayla uygula",
    )
    return parser


def use_last_from_env() -> bool:
    """Return whether ``SIDAR_LAUNCHER_USE_LAST`` asks for the last wizard selection."""
    return os.getenv("SIDAR_LAUNCHER_USE_LAST", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def validate_port_argument(parser: argparse.ArgumentParser, port: str | None) -> None:
    """Exit through ``parser.error`` unless ``port`` is an integer in 1-65535."""
    if port is None:
        return
    try:
        port_value = int(port)
        if not (1 <= port_value <= 65535):
            raise ValueError
    except ValueError:
        parser.error(f"--port değeri 1-65535 arasında tam sayı olmalıdır (verilen: {port!r})")
