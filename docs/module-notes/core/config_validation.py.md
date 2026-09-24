# `core/config_validation.py` — Kritik Ayar Doğrulaması

- **Kaynak dosya:** `core/config_validation.py`
- **Not dosyası:** `docs/module-notes/core/config_validation.py.md`

**Amaç:** `Config.validate_critical_settings()` ve `Config._validate_ai_provider_settings()`
gövdelerini `config.py` facade'ından ayırır. `Config` sınıfı parametre olarak geçer;
donanım yükleme, dizin oluşturma ve provider kontrolü gibi adımlar hâlâ `cls` üzerinden
çağrılır, böylece facade'ın classmethod yüzeyi tek override noktası olarak kalır.

**Özellikler:**
- `validate_ai_provider_settings(config_cls, *, logger, supported_providers,
  provider_required_settings)` — `AI_PROVIDER`'ı normalize edip sınıfa geri yazar,
  desteklenmeyen sağlayıcıyı reddeder; sağlayıcının gerektirdiği her ayar için gizli
  anahtar doluluğunu veya `*_GATEWAY_URL` için http(s) URL geçerliliğini kontrol eder.
- `validate_critical_settings(config_cls, *, logger, log_once_env, localized_log_message)`
  — production secret anahtar listesini (`config_secret_hardening.PRODUCTION_SECRET_KEYS`)
  ve PostgreSQL parola drift kontrolünü (`config_postgres.postgres_password_drift_messages`)
  çağrı anında kendi modüllerinden okur; böylece `config.config_postgres`'u yamalayan
  testler çalışmaya devam eder. Yalnız anahtar adları ve drift açıklamaları loglanır,
  secret değerleri asla loglanmaz. Sırasıyla:
  - donanım bilgisini yükler, GPU bellek bütçesini uygular, dizinleri oluşturur ve
    dotenv yükleme durumunu loglar;
  - `SIDAR_ENV=production` iken eksik/zayıf production secret'larında `SystemExit(1)`;
  - `REQUIRE_GPU` ile GPU yokluğunu ve açık onaysız `ACCESS_LEVEL=full`'u geçersiz sayar;
  - provider ayarlarını ve PostgreSQL parola drift mesajlarını kontrol eder;
  - `MEMORY_ENCRYPTION_KEY` (ve virgülle ayrılmış `MEMORY_ENCRYPTION_KEY_PREVIOUS`)
    için Fernet ön doğrulaması yapar; anahtar yoksa production'da `SystemExit(1)`;
  - `AI_PROVIDER=ollama` ise `/api/tags` probu yapar. Probun sonucu yalnız loglanır,
    doğrulamayı başarısız yapmaz.

**Bağımlılıklar:** `core.config_postgres`, `core.config_secret_hardening`,
`core.config_secrets.is_nonempty_secret`,
`core.config_validators.is_valid_http_url` / `normalize_ai_provider`; opsiyonel olarak
`cryptography.fernet` ve `httpx` (fonksiyon içinde import edilir).

**Testler:** `tests/unit/core/test_config_validation.py`; facade üzerinden
`tests/unit/root/test_config.py`.
