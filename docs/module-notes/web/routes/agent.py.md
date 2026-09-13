# `web/routes/agent.py` — Agent Kayıt ve Plugin Marketplace Rotaları

- **Kaynak dosya:** `web/routes/agent.py`
- **Not dosyası:** `docs/module-notes/web/routes/agent.py.md`

**Amaç:** Yeni agent/plugin kaydı (metin veya dosya yükleme ile) ve plugin
marketplace katalog/kurulum/kaldırma uç noktalarını kaydeder;
`web/plugins/sandbox.py`'nin doğrulama katmanının HTTP giriş noktası.

**Özellikler:**
- `_parse_payload(model, payload)` — Pydantic `model_validate()` veya dict
  unpacking ile esnek payload ayrıştırma (bkz. `web/routes/auth_admin.py`'deki
  aynı desen).
- `build_agent_router(...)` — `POST /api/agents/register`,
  `POST /api/agents/register-file`, `GET /api/plugin-marketplace/catalog`,
  `POST /api/plugin-marketplace/install`,
  `POST /api/plugin-marketplace/reload`,
  `DELETE /api/plugin-marketplace/install/{plugin_id}` rotalarını kaydeder.
