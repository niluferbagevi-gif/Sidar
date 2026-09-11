# `web/cli.py` — Web Sunucu Komut Satırı Giriş Noktası

- **Kaynak dosya:** `web/cli.py`
- **Not dosyası:** `docs/module-notes/web/cli.py.md`

**Amaç:** `web_server.py`'nin doğrudan çalıştırılması için CLI bayraklarını
ayrıştırıp `SidarAgent`'ı başlatan ve `uvicorn` ASGI sunucusunu çalıştıran
giriş noktası; bind host'unu `core/utils/network_validation.py` ile doğrular.

**Özellikler:**
- `main()` — argparse ile host/port bayraklarını okur,
  `is_unspecified_bind`/`validate_bind_host` ile güvensiz genel bind'lere
  karşı uyarır, `web_server`'ı import edip `uvicorn.run` çağırır.
