"""
Sidar Project - PyWebView + React 3D Başlatıcı
Kullanım: python main.py
(Çalıştırmak için 'pip install pywebview' gereklidir)
"""

import os
import sys
import subprocess
import threading
import webview


class Api:
    """JavaScript (React) tarafından çağrılabilen Python fonksiyonları"""

    def __init__(self):
        self.provider = "ollama"
        self.level = "full"
        self._load_defaults()

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
            "--provider", provider,
            "--level", level
        ]

        def run_subprocess():
            kwargs = {}
            # Windows'ta CLI seçildiyse yeni terminal penceresi açar
            if sys.platform == "win32" and mode == "cli":
                kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            subprocess.Popen(cmd_args, **kwargs)

        # Sistemi arka planda başlat
        threading.Thread(target=run_subprocess, daemon=True).start()

        # Başlatıcı penceresini kapat ve yeri Sidar'a bırak
        webview.windows[0].destroy()
        return "Başlatıldı"

    def close_app(self):
        """Pencereyi kapatmak için (Frameless yaptığımız için gerekli)"""
        webview.windows[0].destroy()


def main():
    api = Api()

    # Eğer frontend build edilmişse doğrudan o dosyayı oku, yoksa Vite dev sunucusuna bağlan
    dist_path = os.path.join(os.path.dirname(__file__), "launcher_ui", "dist", "index.html")

    if os.path.exists(dist_path):
        url = dist_path
    else:
        url = "http://localhost:5173"
        print("💡 Geliştirme Modu Aktif: Lütfen 'launcher_ui' klasöründe 'npm run dev' çalıştırdığınızdan emin olun.")

    # Modern frameless (çerçevesiz) bir pencere yaratıyoruz
    window = webview.create_window(
        title="SİDAR AI - Core System Launcher",
        url=url,
        js_api=api,
        width=1000,
        height=650,
        resizable=False,
        frameless=True,       # Standart Windows/Mac çerçevelerini gizler
        easy_drag=True,       # Çerçeve olmadığı için pencereyi her yerinden sürüklenebilir yapar
        background_color='#050505'
    )

    webview.start(debug=False)


if __name__ == "__main__":
    main()
