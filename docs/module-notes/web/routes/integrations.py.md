# `web/routes/integrations.py` — Slack/Jira/Teams Entegrasyon Rotaları

- **Kaynak dosya:** `web/routes/integrations.py`
- **Not dosyası:** `docs/module-notes/web/routes/integrations.py.md`

**Amaç:** `managers/slack_manager.py`, `managers/jira_manager.py`,
`managers/teams_manager.py`'nin HTTP yüzeyi; mesaj gönderme, kanal/issue
listeleme uç noktaları.

**Özellikler:**
- `SlackSendRequest`, `JiraCreateRequest`, `TeamsSendRequest` (BaseModel).
- `build_integrations_router(...)` — `POST /api/integrations/slack/send`,
  `GET /api/integrations/slack/channels`,
  `POST /api/integrations/jira/issue`, `GET /api/integrations/jira/issues`,
  `POST /api/integrations/teams/send` rotalarını kaydeder.
