# `web/routes/hitl.py` — Human-in-the-Loop Rotaları

- **Kaynak dosya:** `web/routes/hitl.py`
- **Not dosyası:** `docs/module-notes/web/routes/hitl.py.md`

**Amaç:** `core/hitl.py`'deki onay kapısının HTTP/WebSocket yüzeyi; bekleyen
onay isteklerini listeler, yeni istek oluşturur, operatör kararını kaydeder
ve `/ws/hitl` üzerinden gerçek zamanlı bildirim sağlar
(`web/security.py`'deki `SIDAR_WS_HITL_PROTOCOL` ve `extract_ws_header_token`
ile WS token doğrulaması).

**Özellikler:**
- `HITLRespondRequest` (BaseModel) — `approved`/`decided_by`/`rejection_reason`.
- `build_hitl_router(...)` — `GET /api/hitl/pending`, `POST /api/hitl/request`,
  `POST /api/hitl/respond/{request_id}`, `WS /ws/hitl` rotalarını kaydeder.
