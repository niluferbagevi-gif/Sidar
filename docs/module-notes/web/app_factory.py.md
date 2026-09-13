# `web/app_factory.py` — FastAPI Uygulama Fabrikası

- **Kaynak dosya:** `web/app_factory.py`
- **Not dosyası:** `docs/module-notes/web/app_factory.py.md`

**Amaç:** `web_server.py`'nin kullandığı FastAPI uygulamasını ve paylaşılan
exception handler'ları kuran fabrika; router kayıtlarını ve runtime state'i
(`SimpleNamespace` üzerinde) merkezi olarak yönetir.

**Özellikler:**
- `_runtime_environment(settings=None)`, `_expose_exception_details(settings=None)`,
  `_expose_api_docs(settings=None)` — production/dev ortam ayrımına göre hata
  detayı/`/docs` görünürlüğünü belirler (production'da hassas detay sızıntısını
  önler).
- `register_exception_handlers(...)` — global `HTTPException`/beklenmeyen
  hata handler'larını kaydeder.
- `register_routers(application, routers)` — `APIRouter` listesini uygulamaya
  bağlar, kayıt özetini döndürür.
- `initialize_runtime_state(application, **overrides)`,
  `get_runtime_state(application)` — uygulama genelinde paylaşılan runtime
  state'i (`app.state` üzerinde) kurar/okur.
- `create_app(...)` — tüm parçaları birleştirip yapılandırılmış `FastAPI`
  örneğini döndürür.
