# `web/routes/static.py` — Frontend Statik Rotaları

- **Kaynak dosya:** `web/routes/static.py`
- **Not dosyası:** `docs/module-notes/web/routes/static.py.md`

**Amaç:** React SPA kabuğu ve vendor asset'leri için statik frontend
rotalarını kaydeden router fabrikası.

**Özellikler:**
- `build_frontend_router(*, web_dir, grafana_url)` — `web_dir()`/`grafana_url()`
  callback'lerinden statik dosya sunumu ve Grafana bağlantı bilgisini
  enjekte eder; `LegacyExportRouter` döndürür.
