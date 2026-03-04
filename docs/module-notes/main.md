# main.py Teknik Notu (Akıllı Başlatıcı)

`main.py`, Sidar için başlangıç katmanıdır. Kullanıcıdan seçim alır ve uygun çalışma modunu (`cli.py` veya `web_server.py`) başlatır.

## 1) Sorumluluklar

- Karşılama/başlatma akışını yönetmek.
- Sağlayıcı (`ollama/gemini`), erişim seviyesi (`restricted/sandbox/full`) ve çalışma modu (`cli/web`) seçimini almak.
- Başlatma öncesi temel kontroller yapmak (`.env`, Ollama erişimi, Gemini key uyarısı).
- Seçimlere göre alt komutu üretip süreci başlatmak.

## 2) Arayüz Modları

- **WebView modu:** `pywebview` tabanlı masaüstü başlatıcı. Arayüz dosyası `web_ui/launcher/index.html` üzerinden gelir.
- **Konsol modu:** Klasik soru-cevap sihirbazı.
- **Auto modu (varsayılan):** WebView mümkünse WebView, değilse konsol sihirbazı.

## 3) Ayrı Frontend Stratejisi (Vite/React + GSAP/Three.js)

- `main.py`, WebView penceresine harici frontend URL yükleyebilir: `--launcher-url http://127.0.0.1:5173`.
- URL verilmezse sırasıyla şu fallback kullanılır:
  1) `SIDAR_LAUNCHER_URL` ortam değişkeni,
  2) `web_ui/launcher/index.html` yerel dosyası.
- Frontend, PyWebView `js_api` köprüsü ile `get_defaults`, `preflight`, `launch` metodlarını çağırır.

## 4) Çalışma Modları

- **Wizard modu (varsayılan):** Etkileşimli başlatıcı (`--ui auto|webview|console`).
- **Quick modu:** `--quick cli` veya `--quick web` ile sihirbazı atlayıp doğrudan başlatma.

## 5) Bağlantılı Dosyalar

- `cli.py`: terminal/CLI agent arayüzü
- `web_server.py`: web arayüzü sunucusu
- `web_ui/launcher/index.html`: WebView fallback launcher frontend
- `config.py`: varsayılan değerler ve preflight kontrol verisi

## 6) Operasyon Notu

- WebView için işletim sisteminde görüntü ortamı (`DISPLAY`/`WAYLAND_DISPLAY`) ve `pywebview` gerekir.
- WebView açılamazsa nedenini kullanıcıya açıkça yazdırır ve konsol sihirbazına fallback yapılır.
- WebView'i zorlamak için `python main.py --ui webview` kullanılabilir.
- `Config` importu çalışma anına taşındığı için `python main.py --help` daha güvenli çalışır.
