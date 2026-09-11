# `web/routes/request_models.py` — Doğrulanmış İstek Payload Modelleri

- **Kaynak dosya:** `web/routes/request_models.py`
- **Not dosyası:** `docs/module-notes/web/routes/request_models.py.md`

**Amaç:** Sidar'ın HTTP route fabrikalarının paylaştığı Pydantic istek
modellerini tek yerde toplar (auth, prompt registry, policy, plugin, swarm).

**Özellikler:**
- `RegisterRequest`, `LoginRequest` — auth payload'ları (`web/routes/auth_admin.py`
  tarafından tüketilir).
- `PromptUpsertRequest`, `PromptActivateRequest` — prompt registry yönetimi.
- `PolicyUpsertRequest` — erişim politikası güncellemesi.
- `AgentPluginRegisterRequest`, `PluginMarketplaceInstallRequest` — plugin
  kayıt/kurulum istekleri.
- `SwarmTaskRequest`, `SwarmExecuteRequest` — swarm görev tetikleme
  payload'ları.
