# `web/routes/federation.py` — Dış Swarm Federasyon Rotaları

- **Kaynak dosya:** `web/routes/federation.py`
- **Not dosyası:** `docs/module-notes/web/routes/federation.py.md`

**Amaç:** CrewAI/AutoGen gibi dış swarm platformlarından gelen görev
teslimini ve geri bildirimini kabul eden HTTP rotaları;
`agent/core/contracts.py`'deki `FederationTaskEnvelope`/`FederationTaskResult`
sözleşmelerinin dış-sistem giriş noktası.

**Özellikler:**
- `FederationTaskRequest`, `FederationFeedbackRequest` (BaseModel) — dış
  platform kimliği, kaynak/hedef agent, görev/geri bildirim payload'ları.
- `_federation_env_name(cfg)`, `_resolve_federation_secret(cfg)` — paylaşımlı
  gizli anahtar çözümü (dış sistem kimlik doğrulaması).
- `build_federation_router(deps_factory)` — `POST /api/federation/execute`,
  `POST /api/federation/feedback` rotalarını kaydeder.
