# `web/routes/operations.py` — Operations/Poyraz Köprü Rotaları

- **Kaynak dosya:** `web/routes/operations.py`
- **Not dosyası:** `docs/module-notes/web/routes/operations.py.md`

**Amaç:** Kampanya, içerik varlığı, operasyon checklist'i ve Poyraz köprüsü
(pazarlama/içerik otomasyonu) için HTTP rotalarını barındırır;
`web/routes/coverage_ops.py`'yi alt-router olarak dahil eder.

**Özellikler:**
- `configure_operations_dependencies(deps_factory)` — DB/Poyraz bağımlılık
  fabrikasını enjekte eder.
- `serialize_campaign(record)`, `serialize_content_asset(record)`,
  `serialize_operation_checklist(record)` — DB kayıtlarını JSON'a çevirir.
- `_database_unavailable_response(...)`, `_poyraz_unavailable_response(...)`
  — servis erişilemezse tutarlı hata yanıtı.
- `build_operations_router(deps_factory)` — kampanya/varlık/checklist CRUD
  ve Poyraz araç rotalarını kaydeder (`GET`/`POST /api/operations/campaigns`,
  `/assets`, vb.).
