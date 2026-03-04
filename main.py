"""
Sidar Project - Akıllı Başlatıcı

Bu dosya, kullanıcıdan etkileşimli seçimler alarak Sidar'ı CLI veya Web modunda
başlatır. Başlatıcı hem konsol sihirbazı hem de (uygunsa) WebView arayüzü sunar.
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


def _collect_preflight_messages(cfg, provider: str) -> List[str]:
    messages: List[str] = ["🔎 Ön kontroller yapılıyor..."]

    if sys.version_info < (3, 10):
        messages.append("⚠ Python 3.10+ önerilir.")

    env_path = Path(cfg.BASE_DIR) / ".env"
    if env_path.exists():
        messages.append(f"✅ .env bulundu: {env_path}")
    else:
        messages.append("⚠ .env bulunamadı, varsayılan ayarlarla devam edilecek.")

    if provider == "gemini" and not cfg.GEMINI_API_KEY:
        messages.append("⚠ GEMINI_API_KEY boş görünüyor.")

    if provider == "ollama":
        try:
            import httpx

            base = cfg.OLLAMA_URL.rstrip("/")
            tags_url = base + "/tags" if base.endswith("/api") else base + "/api/tags"
            with httpx.Client(timeout=2) as client:
                code = client.get(tags_url).status_code
            if code == 200:
                messages.append("✅ Ollama erişimi başarılı.")
            else:
                messages.append(f"⚠ Ollama yanıt kodu: {code}")
        except Exception:
            messages.append("⚠ Ollama erişimi doğrulanamadı (servis kapalı olabilir).")

    return messages


def _preflight(cfg, provider: str) -> None:
    for line in _collect_preflight_messages(cfg, provider):
        print(line)


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


def _webview_support_status() -> tuple[bool, str]:
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False, "DISPLAY/WAYLAND_DISPLAY bulunamadı (headless oturum)."

    try:
        import webview  # noqa: F401
    except Exception as exc:  # pywebview bağımlılığı yoksa
        return False, f"pywebview import edilemedi: {exc}"

    return True, "ok"


def _resolve_launcher_target(explicit_url: str | None) -> str:
    if explicit_url:
        return explicit_url

    env_url = os.environ.get("SIDAR_LAUNCHER_URL", "").strip()
    if env_url:
        return env_url

    launcher_html = Path(__file__).resolve().parent / "web_ui" / "launcher" / "index.html"
    if launcher_html.exists():
        return launcher_html.as_uri()

    raise FileNotFoundError("web_ui/launcher/index.html bulunamadı. --launcher-url ile frontend URL verin.")


def run_webview_ui(launcher_url: str | None = None) -> int:
    from config import Config
    import webview

    cfg = Config()
    result = {"code": 0}

    class Api:
        def get_defaults(self) -> dict:
            return {
                "provider": "ollama",
                "access_level": "full",
                "mode": "cli",
                "log": "INFO",
                "model": cfg.CODING_MODEL,
                "host": cfg.WEB_HOST,
                "port": str(cfg.WEB_PORT),
            }

        def preflight(self, provider: str) -> str:
            return "\n".join(_collect_preflight_messages(cfg, provider))

        def launch(
            self,
            provider: str,
            access_level: str,
            mode: str,
            log: str,
            model: str,
            host: str,
            port: str,
        ) -> str:
            provider = provider or "ollama"
            access_level = access_level or "full"
            log = log or "INFO"

            if mode == "web":
                cmd = _build_web_command(provider, access_level, host or cfg.WEB_HOST, port or str(cfg.WEB_PORT), log)
            else:
                cmd = _build_cli_command(provider, access_level, model or cfg.CODING_MODEL, log)

            result["code"] = subprocess.call(cmd, cwd=os.path.dirname(__file__) or ".")
            for win in webview.windows:
                win.destroy()
            return "OK"

    target = _resolve_launcher_target(launcher_url)
    webview.create_window("Sidar Launcher", url=target, width=1000, height=720, js_api=Api())
    webview.start(debug=False)
    return result["code"]


def _run_auto_or_webview(ui_mode: str, launcher_url: str | None) -> int:
    ok, reason = _webview_support_status()

    if ok:
        try:
            return run_webview_ui(launcher_url)
        except Exception as exc:
            print(f"⚠ WebView UI başlatılamadı: {exc}")
            print("ℹ Linux ortamı için ek bağımlılıklar gerekebilir: `pip install qtpy pyqt5 pyqtwebengine` veya `pip install pygobject`.")
            print("ℹ Geçici fallback: konsol sihirbazı açılıyor.")
            return run_wizard()

    print(f"⚠ WebView UI açılamadı: {reason}")
    print("ℹ Çözüm: `pip install pywebview` ve masaüstü oturumunda çalıştırın.")
    print("ℹ Geçici fallback: konsol sihirbazı açılıyor. (webview zorlamak için: --ui webview)")
    return run_wizard()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sidar akıllı başlatıcı")
    parser.add_argument("--quick", choices=["cli", "web"], help="Sihirbazı atla ve hızlı başlat")
    parser.add_argument("--ui", choices=["auto", "console", "webview"], default="auto", help="Sihirbaz arayüzü (auto/console/webview)")
    parser.add_argument("--launcher-url", help="WebView için dış frontend URL (örn. Vite: http://127.0.0.1:5173)")
    parser.add_argument("--provider", choices=["ollama", "gemini"], help="Hızlı başlat için sağlayıcı")
    parser.add_argument("--level", choices=["restricted", "sandbox", "full"], help="Hızlı başlat için erişim")
    parser.add_argument("--model", help="Hızlı CLI başlat için Ollama modeli")
    parser.add_argument("--host", help="Hızlı web başlat için host")
    parser.add_argument("--port", help="Hızlı web başlat için port")
    parser.add_argument("--log", default="INFO", help="Log seviyesi")
    args = parser.parse_args()

    if not args.quick:
        if args.ui == "console":
            raise SystemExit(run_wizard())
        raise SystemExit(_run_auto_or_webview(args.ui, args.launcher_url))

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
