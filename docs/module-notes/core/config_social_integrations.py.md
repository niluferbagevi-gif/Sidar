# `core/config_social_integrations.py` — Pazarlama/Sosyal Entegrasyon Ayarları

- **Kaynak dosya:** `core/config_social_integrations.py`
- **Not dosyası:** `docs/module-notes/core/config_social_integrations.py.md`

**Amaç:** Meta Graph/Instagram/Facebook/WhatsApp, Slack, Jira ve Microsoft
Teams entegrasyonlarının kimlik bilgisi/uç nokta ayarlarını
`SocialIntegrationSettings` frozen dataclass'ı olarak yükler; `config.Config`
bunu `social_integration_settings` olarak expose eder ve aynı 15 alanı geriye
dönük uyumlu `Config.FOO` class attribute'larına delege eder
(`docs/REFACTOR_PLAN.md`'nin `config.py` maddesinde işaretlenen ilk düşük
riskli dilim). `managers/slack_manager.py`, `managers/jira_manager.py`,
`managers/teams_manager.py`, `managers/social_media_manager.py`,
`agent/roles/poyraz_agent.py` ve `plugins/slack_notification_agent.py` bu
ayarları `cfg.SLACK_TOKEN` gibi mevcut alan adlarıyla tüketmeye devam eder.

**Özellikler:**
- `SocialIntegrationSettings` — `meta_graph_api_token`/`meta_graph_api_version`,
  `instagram_business_account_id`, `facebook_page_id`,
  `whatsapp_phone_number_id`, `slack_token`/`slack_webhook_url`/
  `slack_default_channel`, `jira_url`/`jira_token`/`jira_email`/
  `jira_default_project`/`jira_base_url`/`jira_api_token`,
  `teams_webhook_url`.
- `load_social_integration_settings()` — her alanı kendi `os.getenv(...)`
  değişkeninden okur; `JIRA_BASE_URL`/`JIRA_API_TOKEN` açıkça verilmemişse
  sırasıyla `JIRA_URL`/`JIRA_TOKEN` değerine düşen geriye dönük/alternatif
  adlandırma uyumluluğunu korur.
- `enable_experimental_social_publishing` — `ENABLE_EXPERIMENTAL_SOCIAL_PUBLISHING`
  (varsayılan `false`); Meta Graph/WhatsApp yayınını açan deneysel opt-in bayrağı.
  `Config.ENABLE_EXPERIMENTAL_SOCIAL_PUBLISHING` olarak expose edilir.
- `EXPERIMENTAL_SOCIAL_PUBLISHING_ENV`, `EXPERIMENTAL_SOCIAL_PUBLISHING_DISABLED_REASON`
  — bayrak adı ve kapalıyken döndürülen gerekçe metni için tek kaynak
  (`SocialMediaManager` ve `PoyrazAgent` buradan okur).
