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
import sys
from pathlib import Path

from launcher_api import LauncherAPI


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
    return parser.parse_args()


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
        print("❌ PyWebView kurulu değil.")
        print("Kurulum: pip install pywebview")
        print("Geçici çözüm: python main.py --no-window")
        sys.exit(1)

    import webview

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


if __name__ == "__main__":
    main()
