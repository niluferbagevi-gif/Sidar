# `web/routes/health_runtime.py` — Sağlık/Durum Yanıt Üretimi

- **Kaynak dosya:** `web/routes/health_runtime.py`
- **Not dosyası:** `docs/module-notes/web/routes/health_runtime.py.md`

**Amaç:** `web/routes/health.py`'deki rota tanımlarından operasyonel payload
kurulumunu ayırır; `web_server._health_response` geriye dönük uyumluluk
sarmalayıcılarını korur.

**Özellikler:**
- `LoggerLike` (Protocol) — yalnızca `exception(msg, *args)` gerektiren küçük
  logger sözleşmesi.
- `expose_operational_error_details(app_factory)` — production'da hata
  detayı sızıntısını engeller.
- `health_error_payload(error, exc, *, expose_details)` — hata yanıtını
  `expose_details` bayrağına göre kırpılmış/tam üretir.
- `build_health_response(...)` (async), `build_status_response(...)` (async)
  — sistem sağlığı/detaylı durum JSON'unu üretir.
