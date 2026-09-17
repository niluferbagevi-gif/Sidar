# `web/routes/autonomy.py` — Otonomi Webhook/Wake/Aktivite Rotaları

- **Kaynak dosya:** `web/routes/autonomy.py`
- **Not dosyası:** `docs/module-notes/web/routes/autonomy.py.md`

**Amaç:** Dış sistemlerden otonomi tetikleme webhook'unu (HMAC imza
doğrulamalı), manuel/proaktif "wake" isteğini ve otonomi aktivite geçmişini
sunan rotalar; `web/autonomy_bridge.py`'nin HTTP yüzeyi.

**Özellikler:**
- `AutonomyWakeRequest` (BaseModel) — `event_name`/`prompt`/`source`/
  `payload`/`meta`.
- `_autonomy_webhook_secret(cfg)`, `_autonomy_webhook_signature_required(cfg)`,
  `_validate_autonomy_webhook_signature(...)` — webhook HMAC doğrulaması
  (`web/routes/webhooks.py`'deki GitHub deseniyle paralel).
- `_require_autonomy_admin(request)` — admin-only endpoint koruması.
- `build_autonomy_router(deps_factory)` — `POST /api/autonomy/webhook`,
  `POST /api/autonomy/wake`, `GET /api/autonomy/activity` rotalarını
  kaydeder.
