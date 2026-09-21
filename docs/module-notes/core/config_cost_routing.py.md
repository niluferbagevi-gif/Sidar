# `core/config_cost_routing.py` — Cost-Aware Model Routing Ayarları

- **Kaynak dosya:** `core/config_cost_routing.py`
- **Not dosyası:** `docs/module-notes/core/config_cost_routing.py.md`

**Amaç:** Karmaşıklık eşiği/günlük bütçe tabanlı lokal-vs-bulut model routing
ayarlarını `CostRoutingSettings` frozen dataclass'ı olarak yükler;
`config.Config` bunu `cost_routing_settings` olarak expose eder ve aynı 11
alanı geriye dönük uyumlu `Config.FOO` class attribute'larına delege eder
(`docs/REFACTOR_PLAN.md`'nin `config.py` maddesinde web arama diliminden
sonra işaretlenen sıradaki düşük riskli dilim). `core/router.py` (`CostRouter`
sınıfı ve paylaşımlı bütçe sayaçları) ve `core/llm_client.py` bu ayarları
`getattr(config, "ENABLE_COST_ROUTING", ...)` gibi mevcut alan adlarıyla
tüketmeye devam eder.

**Özellikler:**
- `CostRoutingSettings` — `enable_cost_routing`,
  `cost_routing_complexity_threshold`, `cost_routing_local_provider`,
  `cost_routing_local_model`, `cost_routing_cloud_provider`,
  `cost_routing_cloud_model`, `cost_routing_daily_budget_usd`,
  `cost_routing_token_threshold`, `cost_routing_shared_budget_db_path`,
  `cost_routing_redis_budget_url`, `cost_routing_redis_budget_namespace`.
- `load_cost_routing_settings()` — her alanı kendi ortam değişkeninden okur;
  sayısal alanlar (`get_float_env()`/`get_int_env()`) malformed girdilerde
  uyarı loglayıp varsayılana düşer.
