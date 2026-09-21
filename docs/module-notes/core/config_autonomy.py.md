# `core/config_autonomy.py` — Otonomi Servisi Webhook Ayarları

- **Kaynak dosya:** `core/config_autonomy.py`
- **Not dosyası:** `docs/module-notes/core/config_autonomy.py.md`

**Amaç:** `web/autonomy_bridge.py` ve `web/routes/autonomy.py`'nin otonomi
servis kimliği ve webhook imza doğrulaması için kullandığı 3 alanı
(`AUTONOMY_SERVICE_USER_ID`, `AUTONOMY_WEBHOOK_SECRET`,
`AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE`) `AutonomySettings` frozen
dataclass'ı olarak yükler; `config.Config` bunu `autonomy_settings` olarak
expose eder ve aynı 3 alanı geriye dönük uyumlu `Config.FOO` class
attribute'larına delege eder (`docs/REFACTOR_PLAN.md`'nin `config.py`
maddesinde LSP entegrasyonu diliminden sonra işaretlenen sıradaki düşük
riskli dilim). Legacy alias fallback davranışı birebir korundu:
`AUTONOMY_SERVICE_USER_ID` yoksa `SYSTEM_USER_ID`'ye,
`AUTONOMY_WEBHOOK_SECRET` yoksa `SIDAR_AUTONOMY_WEBHOOK_SECRET`'e,
`AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE` yoksa
`SIDAR_AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE`'a düşer. `web/autonomy_bridge.py`
ve `web/routes/autonomy.py`'nin `getattr(config, "AUTONOMY_SERVICE_USER_ID",
"")` gibi mevcut alan adlarıyla tüketmesi değişmeden korunur.

**Özellikler:**
- `AutonomySettings` — `autonomy_service_user_id`, `autonomy_webhook_secret`,
  `autonomy_webhook_require_signature`.
- `load_autonomy_settings()` — her alanı önce kendi birincil ortam
  değişkeninden, yoksa legacy alias'ından okur; boolean alan
  (`get_bool_env()`) katı "true"/"false" ayrıştırması kullanır.
