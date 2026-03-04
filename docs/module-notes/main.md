# main.py Teknik Notu (Akıllı Başlatıcı)

`main.py`, Sidar için başlangıç katmanıdır. Kullanıcıdan seçim alır ve uygun çalışma modunu (`cli.py` veya `web_server.py`) başlatır.

## 1) Sorumluluklar

- Karşılama/başlatma akışını yönetmek.
- Sağlayıcı (`ollama/gemini`), erişim seviyesi (`restricted/sandbox/full`) ve çalışma modu (`cli/web`) seçimini almak.
- Başlatma öncesi temel kontroller yapmak (`.env`, Ollama erişimi, Gemini key uyarısı).
- Seçimlere göre alt komutu üretip süreci başlatmak.

## 2) Arayüz Modları

- **WebView modu:** `pywebview` tabanlı masaüstü başlatıcı (HTML/CSS/JS). Daha modern, animasyon eklemeye açık bir yapı sağlar.
- **Konsol modu:** Klasik soru-cevap sihirbazı.
- **Auto modu (varsayılan):** WebView mümkünse WebView, değilse konsol sihirbazı.

## 3) Çalışma Modları

- **Wizard modu (varsayılan):** Etkileşimli başlatıcı (`--ui auto|webview|console`).
- **Quick modu:** `--quick cli` veya `--quick web` ile sihirbazı atlayıp doğrudan başlatma.

## 4) Bağlantılı Dosyalar

- `cli.py`: terminal/CLI agent arayüzü
- `web_server.py`: web arayüzü sunucusu
- `config.py`: varsayılan değerler ve preflight kontrol verisi

## 5) Operasyon Notu

- WebView için işletim sisteminde görüntü ortamı (`DISPLAY`/`WAYLAND_DISPLAY`) ve `pywebview` gerekir.
- WebView uygun değilse otomatik fallback ile konsol sihirbazı açılır.
- `Config` importu çalışma anına taşındığı için `python main.py --help` daha güvenli çalışır.
