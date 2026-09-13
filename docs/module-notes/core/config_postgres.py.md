# `core/config_postgres.py` — PostgreSQL DSN/Pool Yardımcıları

- **Kaynak dosya:** `core/config_postgres.py`
- **Not dosyası:** `docs/module-notes/core/config_postgres.py.md`

**Amaç:** `DATABASE_URL` türetimi ve connection-pool varsayılanları için
canonical modül; `config.py` bu helper'ları doğrudan re-export eder
(`docs/module-notes/config.py.md`'de anlatılan split mimarisinin parçası).

**Özellikler:**
- `DatabaseSettings` (frozen, slotted dataclass) — `database_url` ve pool
  ayarlarını taşır.
- `GetEnv`/`GetIntEnv`/`GetBoolEnv`/`GetFloatEnv` type alias'ları — dependency-
  injected env okuma imzaları, test edilebilirlik için.
- URL bileşenlerini `urllib.parse.quote`/`unquote`/`urlsplit` ile güvenli
  biçimde encode/decode eder (şifre içinde özel karakter riskine karşı).
