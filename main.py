"""
Sidar Project - Akıllı Başlatıcı

Bu dosya, kullanıcıdan etkileşimli seçimler alarak Sidar'ı CLI veya Web modunda başlatır.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence


def _print_header() -> None:
    print("\n" + "═" * 64)
    print("  SİDAR Başlatıcı")
    print("  Hoş geldiniz ✨")
    print("═" * 64)


def _choose(prompt: str, options: Sequence[str], default_index: int = 0) -> str:
    while True:
        print(f"\n{prompt}")
        for i, opt in enumerate(options, start=1):
            mark = " (varsayılan)" if i - 1 == default_index else ""
            print(f"  {i}) {opt}{mark}")

        raw = input("Seçiminiz: ").strip()
        if not raw:
            return options[default_index]
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]

        print("⚠ Geçersiz seçim, tekrar deneyin.")


def _ask_text(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw or default


def _confirm(prompt: str, default_yes: bool = True) -> bool:
    hint = "[Y/n]" if default_yes else "[y/N]"
    raw = input(f"{prompt} {hint}: ").strip().lower()
    if not raw:
        return default_yes
    return raw in {"y", "yes", "e", "evet"}


def _preflight(cfg, provider: str) -> None:
    print("\n🔎 Ön kontroller yapılıyor...")

    if sys.version_info < (3, 10):
        print("⚠ Python 3.10+ önerilir.")

    env_path = Path(cfg.BASE_DIR) / ".env"
    if env_path.exists():
        print(f"✅ .env bulundu: {env_path}")
    else:
        print("⚠ .env bulunamadı, varsayılan ayarlarla devam edilecek.")

    if provider == "gemini" and not cfg.GEMINI_API_KEY:
        print("⚠ GEMINI_API_KEY boş görünüyor.")

    if provider == "ollama":
        try:
            import httpx

            base = cfg.OLLAMA_URL.rstrip("/")
            tags_url = base + "/tags" if base.endswith("/api") else base + "/api/tags"
            with httpx.Client(timeout=2) as client:
                code = client.get(tags_url).status_code
            if code == 200:
                print("✅ Ollama erişimi başarılı.")
            else:
                print(f"⚠ Ollama yanıt kodu: {code}")
        except Exception:
            print("⚠ Ollama erişimi doğrulanamadı (servis kapalı olabilir).")


def _build_cli_command(provider: str, access_level: str, model: str | None, log: str) -> List[str]:
    cmd = [sys.executable, "cli.py", "--provider", provider, "--level", access_level, "--log", log]
    if model and provider == "ollama":
        cmd.extend(["--model", model])
    return cmd


def _build_web_command(provider: str, access_level: str, host: str, port: str, log: str) -> List[str]:
    return [
        sys.executable,
        "web_server.py",
        "--provider",
        provider,
        "--level",
        access_level,
        "--host",
        host,
        "--port",
        port,
        "--log",
        log.lower(),
    ]


def run_wizard() -> int:
    from config import Config

    cfg = Config()
    _print_header()

    provider = _choose("AI sağlayıcısı seçin:", ["ollama", "gemini"], 0)
    access_level = _choose("Erişim seviyesini seçin:", ["restricted", "sandbox", "full"], 2)
    mode = _choose("Başlatma modu seçin:", ["cli", "web"], 0)
    log_level = _choose("Log seviyesini seçin:", ["DEBUG", "INFO", "WARNING"], 1)

    ollama_model = None
    if provider == "ollama":
        ollama_model = _ask_text("Ollama modeli", cfg.CODING_MODEL)

    _preflight(cfg, provider)

    if mode == "cli":
        cmd = _build_cli_command(provider, access_level, ollama_model, log_level)
    else:
        host = _ask_text("Web host", cfg.WEB_HOST)
        port = _ask_text("Web port", str(cfg.WEB_PORT))
        cmd = _build_web_command(provider, access_level, host, port, log_level)

    print("\n🚀 Başlatılacak komut:")
    print("   " + " ".join(cmd))

    if not _confirm("Devam edilsin mi?", True):
        print("İşlem iptal edildi.")
        return 0

    return subprocess.call(cmd, cwd=os.path.dirname(__file__) or ".")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sidar akıllı başlatıcı")
    parser.add_argument("--quick", choices=["cli", "web"], help="Sihirbazı atla ve hızlı başlat")
    parser.add_argument("--provider", choices=["ollama", "gemini"], help="Hızlı başlat için sağlayıcı")
    parser.add_argument("--level", choices=["restricted", "sandbox", "full"], help="Hızlı başlat için erişim")
    parser.add_argument("--model", help="Hızlı CLI başlat için Ollama modeli")
    parser.add_argument("--host", help="Hızlı web başlat için host")
    parser.add_argument("--port", help="Hızlı web başlat için port")
    parser.add_argument("--log", default="INFO", help="Log seviyesi")
    args = parser.parse_args()

    if not args.quick:
        raise SystemExit(run_wizard())

    provider = args.provider or "ollama"
    level = args.level or "full"

    if args.quick == "cli":
        cmd = _build_cli_command(provider, level, args.model, args.log)
    else:
        from config import Config

        cfg = Config()
        cmd = _build_web_command(provider, level, args.host or cfg.WEB_HOST, args.port or str(cfg.WEB_PORT), args.log)

    raise SystemExit(subprocess.call(cmd, cwd=os.path.dirname(__file__) or "."))


if __name__ == "__main__":
    main()
