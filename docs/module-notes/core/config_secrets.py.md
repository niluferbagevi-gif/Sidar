# `core/config_secrets.py` — Sır Gücü/Zayıflık Politikası

- **Kaynak dosya:** `core/config_secrets.py`
- **Not dosyası:** `docs/module-notes/core/config_secrets.py.md`

**Amaç:** Config değerlerinin (JWT secret, DB şifresi vb.) zayıf/varsayılan
olup olmadığını değerlendiren paylaşılan politika katmanı.

**Özellikler:**
- `DEFAULT_WEAK_SECRET_VALUES` — bilinen zayıf/varsayılan değerler kümesi
  (`"sidar"`, `"admin"`, `"password"`, `"changeme"`, `"postgres"`,
  `"123456"` vb.).
- `is_nonempty_secret()` — değerin boş olmadığını ve satır sonu/NUL byte
  gibi bozuk karakterler içermediğini doğrular.
- `is_weak_secret()` — önce bilinen zayıf değerler kümesine, sonra
  `scripts/secret_strength.py`'deki entropi tabanlı politikaya (varsayılan
  minimum uzunluk 24) karşı kontrol eder. `core/config_secret_hardening.py`
  production secret taramasının temel yapı taşıdır.
