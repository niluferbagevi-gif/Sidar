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


def _can_use_webview_ui() -> bool:
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return True


def run_webview_ui() -> int:
    from config import Config
    import webview

    cfg = Config()
    result = {"code": 0}

    class Api:
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

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <title>Sidar Launcher</title>
  <style>
    body {{ margin: 0; font-family: Inter, Arial, sans-serif; background: radial-gradient(circle at 20% 20%, #1f2937, #0b1020 70%); color: #e5e7eb; }}
    .wrap {{ max-width: 860px; margin: 24px auto; padding: 20px; }}
    .card {{ background: rgba(17,24,39,.75); border: 1px solid rgba(255,255,255,.12); border-radius: 16px; padding: 18px; box-shadow: 0 10px 30px rgba(0,0,0,.3); }}
    h1 {{ margin: 0 0 14px; font-size: 26px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }}
    label {{ display: block; font-size: 13px; margin-bottom: 4px; opacity: .9; }}
    input, select {{ width: 100%; box-sizing: border-box; padding: 10px; border-radius: 10px; border: 1px solid #374151; background: #111827; color: #f3f4f6; }}
    .row {{ margin-top: 12px; display: flex; gap: 10px; }}
    button {{ border: 0; border-radius: 10px; padding: 10px 14px; cursor: pointer; font-weight: 600; }}
    .p {{ background: #3b82f6; color: white; }}
    .s {{ background: #374151; color: white; }}
    .hint {{ margin-top: 12px; font-size: 13px; color: #9ca3af; }}
  </style>
</head>
<body>
  <div class='wrap'>
    <div class='card'>
      <h1>Sidar Interaktif Başlatıcı</h1>
      <div class='grid'>
        <div><label>Sağlayıcı</label><select id='provider'><option>ollama</option><option>gemini</option></select></div>
        <div><label>Erişim Seviyesi</label><select id='level'><option>restricted</option><option>sandbox</option><option selected>full</option></select></div>
        <div><label>Mod</label><select id='mode'><option selected>cli</option><option>web</option></select></div>
        <div><label>Log</label><select id='log'><option>DEBUG</option><option selected>INFO</option><option>WARNING</option></select></div>
        <div><label>Ollama Model</label><input id='model' value='{cfg.CODING_MODEL}' /></div>
        <div><label>Web Host</label><input id='host' value='{cfg.WEB_HOST}' /></div>
        <div><label>Web Port</label><input id='port' value='{cfg.WEB_PORT}' /></div>
      </div>
      <div class='row'>
        <button class='s' onclick='runChecks()'>Ön Kontrol</button>
        <button class='p' onclick='launch()'>Başlat</button>
      </div>
      <div class='hint'>Not: Bu arayüz web teknolojileri tabanlıdır (PyWebView). Flash hissi için JS animasyon kütüphaneleri eklenebilir.</div>
    </div>
  </div>
  <script>
    const el = id => document.getElementById(id);
    async function runChecks() {{
      const txt = await window.pywebview.api.preflight(el('provider').value);
      alert(txt);
    }}
    async function launch() {{
      await window.pywebview.api.launch(
        el('provider').value,
        el('level').value,
        el('mode').value,
        el('log').value,
        el('model').value,
        el('host').value,
        el('port').value,
      );
    }}
  </script>
</body>
</html>
"""

    webview.create_window("Sidar Launcher", html=html, width=920, height=640, js_api=Api())
    webview.start()
    return result["code"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Sidar akıllı başlatıcı")
    parser.add_argument("--quick", choices=["cli", "web"], help="Sihirbazı atla ve hızlı başlat")
    parser.add_argument("--ui", choices=["auto", "console", "webview"], default="auto", help="Sihirbaz arayüzü (auto/console/webview)")
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
        if args.ui == "webview":
            if not _can_use_webview_ui():
                print("⚠ WebView UI kullanılamadı (display veya pywebview yok). Konsol sihirbazı açılıyor.")
                raise SystemExit(run_wizard())
            raise SystemExit(run_webview_ui())

        if _can_use_webview_ui():
            raise SystemExit(run_webview_ui())
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
