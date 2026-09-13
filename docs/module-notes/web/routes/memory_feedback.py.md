# `web/routes/memory_feedback.py` — Varlık Belleği ve Geri Bildirim Rotaları

- **Kaynak dosya:** `web/routes/memory_feedback.py`
- **Not dosyası:** `docs/module-notes/web/routes/memory_feedback.py.md`

**Amaç:** `core/entity_memory.py`'nin (kullanıcı bazlı varlık belleği) ve
active-learning geri bildirim kaydının HTTP yüzeyi.

**Özellikler:**
- `EntityUpsertRequest`, `FeedbackRecordRequest` (BaseModel) — varlık
  yazma (`ttl_days` ile opsiyonel geçicilik) ve geri bildirim payload'ları.
- `build_memory_feedback_router(...)` — `POST /api/memory/entity/upsert`,
  `GET`/`DELETE` varlık uç noktaları, `POST /api/feedback/record` ve
  ilgili `GET` rotalarını kaydeder.
