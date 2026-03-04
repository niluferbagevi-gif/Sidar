"""PyWebView masaüstü başlatıcı.

Bu modül, backend'i (FastAPI) ayrı bir süreçte ayağa kaldırır ve
PyWebView penceresinde ayrı bir frontend'i (Vite/React) yükler.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


def _wait_for_backend(url: str, timeout_s: int = 20) -> bool:
    """Backend sağlık kontrol URL'inin erişilebilir olmasını bekler."""
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            with urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.3)
    return False


def _resolve_frontend_entry(frontend_url: str, frontend_dist: str | None) -> str:
    """Ön yüz kaynağını belirler: dev URL veya derlenmiş dist/index.html."""
    if frontend_dist:
        index_file = Path(frontend_dist) / "index.html"
        if not index_file.exists():
            raise FileNotFoundError(f"Frontend dist bulunamadı: {index_file}")
        return index_file.resolve().as_uri()
    return frontend_url


def launch_desktop(
    provider: str,
    level: str,
    host: str,
    port: int,
    frontend_url: str,
    frontend_dist: str | None,
) -> None:
    """Backend + PyWebView masaüstü uygulamasını başlatır."""
    if importlib.util.find_spec("webview") is None:
        raise RuntimeError(
            "pywebview yüklü değil. Kurulum: pip install pywebview"
        )

    import webview

    base_dir = Path(__file__).resolve().parent
    backend_script = base_dir / "web_server.py"
    python_exe = sys.executable or "python"

    backend_cmd = [
        python_exe,
        str(backend_script),
        "--provider",
        provider,
        "--level",
        level,
        "--host",
        host,
        "--port",
        str(port),
    ]

    env = os.environ.copy()
    env.setdefault("SIDAR_DESKTOP_MODE", "1")

    backend_proc = subprocess.Popen(backend_cmd, env=env)

    health_url = f"http://{host}:{port}/status"
    if not _wait_for_backend(health_url):
        backend_proc.terminate()
        raise RuntimeError(
            f"Backend başlatılamadı veya {health_url} erişilemedi."
        )

    entry = _resolve_frontend_entry(frontend_url, frontend_dist)

    try:
        window = webview.create_window(
            "SİDAR Desktop",
            url=entry,
            min_size=(1000, 700),
        )
        webview.start()
    finally:
        if backend_proc.poll() is None:
            backend_proc.terminate()
            backend_proc.wait(timeout=5)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SİDAR PyWebView masaüstü başlatıcı")
    parser.add_argument("--provider", default="ollama", choices=["ollama", "gemini"])
    parser.add_argument(
        "--level",
        default="restricted",
        choices=["restricted", "sandbox", "full"],
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5173")
    parser.add_argument("--frontend-dist", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    launch_desktop(
        provider=args.provider,
        level=args.level,
        host=args.host,
        port=args.port,
        frontend_url=args.frontend_url,
        frontend_dist=args.frontend_dist,
    )


if __name__ == "__main__":
    main()
