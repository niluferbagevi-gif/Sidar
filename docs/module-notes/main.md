# main.py Teknik Notu (Akıllı Başlatıcı)

`main.py`, Sidar için etkileşimli başlangıç sihirbazıdır. Kullanıcıdan adım adım seçim alır ve uygun çalışma modunu (`cli.py` veya `web_server.py`) başlatır.

## 1) Sorumluluklar

- Karşılama/başlatma menüsü sunmak.
- Sağlayıcı (`ollama/gemini`), erişim seviyesi (`restricted/sandbox/full`) ve çalışma modu (`cli/web`) seçimini almak.
- Başlatma öncesi temel kontroller yapmak (`.env`, Ollama erişimi, Gemini key uyarısı).
- Seçimlere göre alt komutu üretip süreci başlatmak.

## 2) Çalışma Modları

- **Wizard modu (varsayılan):** Etkileşimli soru-cevap akışı.
- **Quick modu:** `--quick cli` veya `--quick web` ile sihirbazı atlayıp doğrudan başlatma.

## 3) Bağlantılı Dosyalar

- `cli.py`: terminal/CLI agent arayüzü
- `web_server.py`: web arayüzü sunucusu
- `config.py`: varsayılan değerler ve preflight kontrol verisi

## 4) Operasyon Notu

- `Dockerfile` varsayılan entrypoint olarak `main.py` çalıştırdığında artık kullanıcıyı etkileşimli başlatıcı karşılar.
- Non-interactive otomasyon için `--quick` argümanları kullanılmalıdır.
- `Config` importu çalışma anına taşınmıştır; bu sayede `python main.py --help` çağrısı, konfigürasyon bağımlılıkları eksik olsa bile daha güvenli şekilde yanıt verebilir.