# `core/config_security.py` — Güvenlik Ayarları

- **Kaynak dosya:** `core/config_security.py`
- **Not dosyası:** `docs/module-notes/core/config_security.py.md`

**Amaç:** API anahtarı, JWT ve erişim seviyesi ayarlarını yükler; production için eksik veya
zayıf secret kontrollerini sağlar. `core/config_secret_hardening.py` ve `config.py`
bu modülü kullanır.

**Özellikler:**
- `SecuritySettings` / `load_security_settings(...)` — JWT secret boşsa runtime'da
  güvenli rastgele değer üretir; API key'e geri düşmez.
- `get_missing_security_runtime_keys(...)` — production'da eksik kritik secret'lar.
- `has_weak_postgres_runtime_secret(...)` — zayıf PostgreSQL parolası tespiti.
