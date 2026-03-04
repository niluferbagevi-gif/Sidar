"""
Sidar Project - PyWebView + React 3D Başlatıcı
Kullanım: python main.py
(Çalıştırmak için 'pip install pywebview' gereklidir)
"""

import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.error import URLError
from urllib.request import Request, urlopen


class Api:
    """JavaScript (React) tarafından çağrılabilen Python fonksiyonları"""

    def __init__(self):
        self.provider = "ollama"
        self.level = "full"
        self._webview = None
        self._load_defaults()

    def set_webview(self, webview_module):
        self._webview = webview_module

    def _load_defaults(self):
        # Varsayılan ayarları config'den çek
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from config import Config

            cfg = Config()
            self.provider = cfg.AI_PROVIDER.lower()
            self.level = cfg.ACCESS_LEVEL.lower()
        except ImportError:
            pass

    def get_defaults(self):
        """Frontend ilk yüklendiğinde varsayılan ayarları almak için çağırır"""
        return {"provider": self.provider, "level": self.level}

    def launch_system(self, mode, provider, level):
        """Kullanıcı BAŞLAT butonuna bastığında çalışır"""
        target_script = "web_server.py" if mode == "web" else "cli.py"

        cmd_args = [
            sys.executable,
            target_script,
            "--provider",
            provider,
            "--level",
            level,
        ]

        def run_subprocess():
            kwargs = {"cwd": os.path.dirname(__file__) or "."}
            # Windows'ta CLI seçildiyse yeni terminal penceresi açar
            if sys.platform == "win32" and mode == "cli":
                kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            subprocess.Popen(cmd_args, **kwargs)

        # Sistemi arka planda başlat
        threading.Thread(target=run_subprocess, daemon=True).start()

        # Başlatıcı penceresini kapat ve yeri Sidar'a bırak
        if self._webview and self._webview.windows:
            self._webview.windows[0].destroy()
        return "Başlatıldı"

    def close_app(self):
        """Pencereyi kapatmak için (Frameless yaptığımız için gerekli)"""
        if self._webview and self._webview.windows:
            self._webview.windows[0].destroy()


def _is_url_reachable(url, timeout=1.0):
    try:
        req = Request(url, headers={"User-Agent": "sidar-launcher/1.0"})
        with urlopen(req, timeout=timeout):
            return True
    except (URLError, TimeoutError, ValueError):
        return False


def _wait_until_reachable(url, timeout=8):
    start = time.time()
    while time.time() - start < timeout:
        if _is_url_reachable(url):
            return True
        time.sleep(0.25)
    return False


def _detect_launcher_url():
    # Eğer frontend build edilmişse doğrudan o dosyayı oku, yoksa Vite dev sunucusuna bağlan
    dist_path = os.path.join(os.path.dirname(__file__), "launcher_ui", "dist", "index.html")
    dev_url = "http://localhost:5173"

    if os.path.exists(dist_path):
        return dist_path

    if _is_url_reachable(dev_url):
        return dev_url

    print("💡 Geliştirme Modu Aktif: launcher_ui için npm run dev bekleniyor.")
    if shutil.which("npm") is None:
        print("⚠ npm bulunamadı. Node.js + npm kurmadan launcher_ui dev server çalışmaz.")
    return dev_url


def _fallback_without_pywebview(api, launcher_url):
    """PyWebView açılamazsa güvenli fallback: web UI başlat + tarayıcı aç."""
    print("⚠ PyWebView GUI backend bulunamadı. Tarayıcı fallback moduna geçiliyor...")

    # launcher_ui dev/build yoksa doğrudan Sidar web UI açalım
    if not launcher_url.startswith("http://") and not launcher_url.startswith("https://"):
        # local dist dosyası ise dosya URL'siyle aç
        webbrowser.open(f"file://{launcher_url}")
        return

    if _is_url_reachable(launcher_url):
        webbrowser.open(launcher_url)
        return

    # Son fallback: web_server başlat ve kendi UI'ını aç
    cmd = [
        sys.executable,
        "web_server.py",
        "--provider",
        api.provider,
        "--level",
        api.level,
    ]
    subprocess.Popen(cmd, cwd=os.path.dirname(__file__) or ".")
    backend_url = "http://127.0.0.1:7860"
    if _wait_until_reachable(backend_url, timeout=10):
        webbrowser.open(backend_url)
        print(f"✅ Web arayüzü açıldı: {backend_url}")
    else:
        print("⚠ web_server.py başlatıldı ama URL doğrulanamadı. Manuel kontrol edin: http://127.0.0.1:7860")


def main():
    api = Api()
    launcher_url = _detect_launcher_url()

    try:
        import webview

        api.set_webview(webview)
        webview.create_window(
            title="SİDAR AI - Core System Launcher",
            url=launcher_url,
            js_api=api,
            width=1000,
            height=650,
            resizable=False,
            frameless=True,  # Standart Windows/Mac çerçevelerini gizler
            easy_drag=True,  # Çerçeve olmadığı için pencereyi her yerinden sürüklenebilir yapar
            background_color="#050505",
        )
        webview.start(debug=False)
    except Exception as exc:
        print(f"⚠ PyWebView başlatılamadı: {exc}")
        _fallback_without_pywebview(api, launcher_url)


if __name__ == "__main__":
    main()
