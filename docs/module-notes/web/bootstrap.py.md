# `web/bootstrap.py` — Frontend Bootstrap Yardımcıları

- **Kaynak dosya:** `web/bootstrap.py`
- **Not dosyası:** `docs/module-notes/web/bootstrap.py.md`

**Amaç:** FastAPI uygulamasına derlenmiş frontend (SPA) dosyalarını monte
eden ve `dist/` dizini eksik olsa bile başlamayı garanti eden yardımcılar.

**Özellikler:**
- `make_static_files_with_staticfiles(directory, static_files_cls)` —
  `check_dir=False` destekleyen/desteklemeyen `StaticFiles` sürümleri
  arasında uyumluluk sağlar (dizin yoksa uygulama çökmeden ayağa kalkar).
- `make_static_files(directory)`, `mount_frontend_static_routes(target_app, web_dir)`
  — statik dosya rotalarını uygulamaya bağlar.
- `await_if_needed(value)` — senkron/asenkron dönüş değerlerini tek tip
  ele alır.
- `build_spa_fallback_handler(...)` — bilinmeyen path'leri SPA'nın
  `index.html`'ine yönlendiren fallback handler kurar (client-side routing).
