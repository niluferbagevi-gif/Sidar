# `web/middleware/cors.py` — Loopback CORS Yapılandırması

- **Kaynak dosya:** `web/middleware/cors.py`
- **Not dosyası:** `docs/module-notes/web/middleware/cors.py.md`

**Amaç:** `configure_loopback_cors()` tek fonksiyonuyla FastAPI uygulamasına
`localhost`/`127.0.0.1`/`0.0.0.0` origin'lerini (herhangi bir port ile,
`LOOPBACK_ORIGIN_REGEX`) tarayıcıdan erişime açan `CORSMiddleware`'i ekler —
geliştirme port'undan bağımsız çalışır. Yalnızca `GET`/`POST`/`DELETE`
metodlarına ve `Content-Type`/`Authorization` başlıklarına izin verir; dış
(loopback olmayan) origin'ler bu regex'e hiç uymaz.
