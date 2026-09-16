# `core/config_secret_hardening.py` — Production Sır Sağlamlaştırma Kontrolleri

- **Kaynak dosya:** `core/config_secret_hardening.py`
- **Not dosyası:** `docs/module-notes/core/config_secret_hardening.py.md`

**Amaç:** `Config` facade'inin dışında tutulan, production'a özgü sır
sağlamlaştırma kontrollerini toplar — `collect_unsafe_production_secret_keys()`
eksik, zayıf, bilinen-paylaşılan veya production'a özgü olmayan (dev/test
dotenv'lerinden sızmış) secret'ları tek bir listede döndürür.

**Özellikler:**
- `PRODUCTION_SECRET_KEYS` — denetlenen sabit sır anahtarları listesi
  (`API_KEY`, `JWT_SECRET_KEY`, `MEMORY_ENCRYPTION_KEY`,
  `AUTONOMY_WEBHOOK_SECRET`, `SWARM_FEDERATION_SHARED_SECRET`,
  `GITHUB_WEBHOOK_SECRET`, `GRAFANA_ADMIN_PASSWORD`, `METRICS_TOKEN`).
- `_read_dotenv_secret_values()` — bir dotenv dosyasından yalnızca bu
  anahtarları, ortamı hiç mutasyona uğratmadan okur (örn.
  `scripts/known_weak_secrets.txt` ile karşılaştırma için).
- `core/config_secrets.py`'deki `is_weak_secret()`/`is_nonempty_secret()`
  ve `core/config_validators.py`'deki doğrulayıcılar üzerine kurulu.
