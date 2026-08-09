# 3.3 `cli.py` — CLI Arayüzü (465 satır)

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** Terminal tabanlı etkileşimli REPL döngüsü; ajanın gerçek giriş noktası.

**İsimlendirme notu:** `cli.py`, ismi tarihsel olarak `main.py`'den taşınmıştır
(kaynak dosyanın kendi docstring'i bunu belgeler). Kökteki *güncel* `main.py`
bu tarihsel taşımadan bağımsız, sonradan eklenen bir sihirbaz/launcher
modülüdür — ajan mantığı içermez, sonunda bu dosyayı (`cli.py`) veya
`web_server.py`'yi alt süreçte başlatır. `python cli.py` sihirbazı atlayıp
doğrudan bu REPL'e girer. Bkz. `docs/module-notes/main.py.md`.

**Mimari Düzeltme:**
Eski kodda `while` döngüsü içinde her turda `asyncio.run()` çağrılıyordu; bu `asyncio.Lock` ömrünü bozuyordu. Yeni yapıda tüm döngü tek bir `async` fonksiyona (`_interactive_loop_async`) alınmıştır — lock tüm oturum boyunca aynı event loop'ta yaşar.

**Desteklenen Nokta Komutları:**

| Komut | Eylem |
|-------|-------|
| `.status` | Sistem durumu |
| `.clear` / `/clear` / `/reset` | Konuşma belleğini temizle |
| `.audit` | Proje denetimi |
| `.health` | Sistem sağlık raporu |
| `.gpu` | GPU belleği optimize et |
| `.github` | GitHub bağlantı durumu |
| `.level` / `.level <seviye>` | Erişim seviyesini göster / değiştir |
| `.web` | Web arama durumu |
| `.docs` | Belge deposunu listele |
| `.help` | Yardım |
| `.exit` / `.q` | Çıkış |

**Doğrudan Komutlar (AutoHandle üzerinden):**
- `web'de ara: <sorgu>`, `pypi: <paket>`, `npm: <paket>`, `github releases: <owner/repo>`, `docs ara: <sorgu>`, `stackoverflow: <sorgu>`, `belge ekle <url>`

**CLI Argümanları:**
- `--level`, `--provider`, `--model`, `--log`, `-c/--command`, `--status`

---
