# `web/routes/orchestration.py` — Swarm/Todo Orkestrasyon Rotaları

- **Kaynak dosya:** `web/routes/orchestration.py`
- **Not dosyası:** `docs/module-notes/web/routes/orchestration.py.md`

**Amaç:** Swarm görev tetikleme ve todo/seviye yönetimi için temel
orkestrasyon HTTP rotalarını kaydeder; `agent/swarm.py`'nin doğrudan HTTP
tetikleme yüzeyi.

**Özellikler:**
- `_parse_payload(model, payload)` — esnek Pydantic ayrıştırma (diğer route
  fabrikalarındaki aynı desen).
- `build_orchestration_router(...)` — `POST /api/swarm/execute`,
  `GET /todo`, `POST /clear`, `POST /set-level` rotalarını kaydeder.
