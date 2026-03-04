"""
Sidar Project - PyWebView Launcher
==================================

Yeni başlatıcı mimarisi:
- Masaüstü kabuğu: PyWebView
- Arayüz: Ayrı frontend (Vite/React) veya yerel fallback HTML
- Köprü: JS <-> Python API (start/health/preview)

Kullanım:
    python main.py
    python main.py --launcher-url http://localhost:5173
    python main.py --no-window   # sadece sağlık kontrolü/komut önizleme
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from launcher_api import LauncherAPI


def _has_gui_backend() -> tuple[bool, str]:
    """PyWebView için en az bir GUI backend mevcut mu kontrol et."""
    # GTK backend
    if importlib.util.find_spec("gi") is not None:
        return True, "GTK (gi)"

    # Qt backend (pywebview qtpy üzerinden bu modülleri kullanır)
    qt_candidates = [
        "PyQt5.QtWebEngineCore",
        "PyQt6.QtWebEngineCore",
        "PySide6.QtWebEngineCore",
    ]
    for mod in qt_candidates:
        try:
            if importlib.util.find_spec(mod) is not None:
                return True, f"Qt ({mod})"
        except ModuleNotFoundError:
            continue

    return False, "GTK (python3-gi) veya QtWebEngine (PyQtWebEngine/PySide6) bulunamadı"




def _probe_gui_runtime() -> tuple[bool, str]:
    """GUI backend'in başlatma öncesi temel runtime uygunluğunu kontrol et."""
    display = os.getenv("DISPLAY", "").strip()
    wayland = os.getenv("WAYLAND_DISPLAY", "").strip()

    # Linux/WSL GUI oturumu yoksa pywebview başlatmak anlamsız ve çoğu durumda crash üretir.
    if not (display or wayland):
        return False, "GUI display bulunamadı (DISPLAY/WAYLAND_DISPLAY boş)"

    # GTK: gi + Gtk namespace doğrulaması
    gtk_cmd = [
        sys.executable,
        "-c",
        "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; print('GTK OK')",
    ]
    gtk = subprocess.run(gtk_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if gtk.returncode == 0:
        return True, "GTK runtime doğrulandı"

    # Qt: yalnızca import testi (QApplication açmak xcb/plugin sorunlarında hard abort üretebilir)
    qt_checks = [
        "import PyQt5.QtWebEngineCore as _; print('QT5 OK')",
        "import PyQt6.QtWebEngineCore as _; print('QT6 OK')",
        "import PySide6.QtWebEngineCore as _; print('PYSIDE6 OK')",
    ]
    for code in qt_checks:
        qt = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if qt.returncode == 0:
            return True, "Qt WebEngine import doğrulandı"

    return False, "GTK/Qt runtime doğrulanamadı (Gtk namespace veya Qt runtime/plugin eksiği)"


def _resolve_launcher_url(custom_url: str | None) -> str:
    """Öncelik: CLI flag > env > yerel fallback dosya."""
    if custom_url:
        return custom_url

    env_url = os.getenv("SIDAR_LAUNCHER_URL", "").strip()
    if env_url:
        return env_url

    local_html = Path(__file__).resolve().parent / "launcher_ui" / "index.html"
    return local_html.resolve().as_uri()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sidar PyWebView Launcher")
    parser.add_argument(
        "--launcher-url",
        help="Harici frontend URL (örn. Vite dev server: http://localhost:5173)",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="PyWebView penceresini açmadan launcher bilgisini yazdır.",
    )
    parser.add_argument("--width", type=int, default=1120, help="Pencere genişliği")
    parser.add_argument("--height", type=int, default=760, help="Pencere yüksekliği")
    parser.add_argument(
        "--fallback",
        choices=["legacy-cli", "open-browser", "none"],
        default="open-browser",
        help="PyWebView başlatılamazsa uygulanacak fallback davranışı (varsayılan: open-browser)",
    )
    return parser.parse_args()


def _ask_choice(prompt: str, options: list[str]) -> str:
    while True:
        print(f"\n{prompt}")
        for idx, opt in enumerate(options, 1):
            print(f"  {idx}) {opt}")
        val = input("Seçiminiz: ").strip().lower()
        if val.isdigit():
            i = int(val)
            if 1 <= i <= len(options):
                return options[i - 1]
        for opt in options:
            if val == opt.lower():
                return opt
        print("Geçersiz seçim, tekrar deneyin.")


def _run_legacy_cli_launcher(api: LauncherAPI) -> None:
    defaults = api.get_defaults()
    print("\n⚠️ PyWebView backend bulunamadığı için terminal launcher açıldı.")
    provider = _ask_choice("AI sağlayıcısı:", ["ollama", "gemini"])
    level = _ask_choice("Erişim seviyesi:", ["restricted", "sandbox", "full"])
    mode = _ask_choice("Arayüz modu:", ["cli", "web"])
    log = _ask_choice("Log seviyesi:", ["DEBUG", "INFO", "WARNING"])

    payload: dict[str, str | int] = {
        "provider": provider,
        "level": level,
        "mode": mode,
        "log": log,
    }
    if mode == "cli":
        model = input(f"Model [{defaults['model']}]: ").strip() or defaults["model"]
        payload["model"] = model
    else:
        host = input(f"Web host [{defaults['host']}]: ").strip() or defaults["host"]
        port = input(f"Web port [{defaults['port']}]: ").strip() or str(defaults["port"])
        payload["host"] = host
        payload["port"] = int(port)

    cmd = api.preview_command(payload)["command"]
    print(f"\nÇalıştırılıyor: {cmd}\n")
    subprocess.run(api.build_command(payload), check=False)


def _handle_fallback(reason: str, args: argparse.Namespace, api: LauncherAPI, launcher_url: str) -> None:
    print(f"\n⚠️ PyWebView başlatılamadı: {reason}")
    if args.fallback == "open-browser":
        print("Tarayıcı fallback açılıyor (not: JS-Python bridge dış tarayıcıda aktif olmayabilir).")
        webbrowser.open(launcher_url)
        return
    if args.fallback == "legacy-cli":
        _run_legacy_cli_launcher(api)
        return
    print("Fallback devre dışı (--fallback none).")


def main() -> None:
    args = _parse_args()
    api = LauncherAPI(base_dir=Path(__file__).resolve().parent)
    launcher_url = _resolve_launcher_url(args.launcher_url)

    if args.no_window:
        print("Sidar Launcher hazır")
        print(f"UI URL : {launcher_url}")
        print(f"Config : {api.get_defaults()}")
        return

    if importlib.util.find_spec("webview") is None:
        _handle_fallback("pywebview paketi kurulu değil", args, api, launcher_url)
        return

    backend_ok, backend_msg = _has_gui_backend()
    if not backend_ok:
        _handle_fallback(
            f"PyWebView GUI backend eksik: {backend_msg}",
            args,
            api,
            launcher_url,
        )
        return

    runtime_ok, runtime_msg = _probe_gui_runtime()
    if not runtime_ok:
        _handle_fallback(
            f"PyWebView runtime hazır değil: {runtime_msg}",
            args,
            api,
            launcher_url,
        )
        return

    print(f"✅ PyWebView backend hazır: {runtime_msg}")

    import webview

    try:
        webview.create_window(
            title="Sidar Launcher",
            url=launcher_url,
            js_api=api,
            width=max(900, args.width),
            height=max(640, args.height),
            min_size=(900, 640),
            resizable=True,
        )
        webview.start(debug=False)
    except Exception as exc:
        _handle_fallback(str(exc), args, api, launcher_url)


if __name__ == "__main__":
    main()