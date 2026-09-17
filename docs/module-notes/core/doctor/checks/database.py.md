# `core/doctor/checks/database.py` — Veritabanı/pgvector Doktor Kontrolleri

- **Kaynak dosya:** `core/doctor/checks/database.py`
- **Not dosyası:** `docs/module-notes/core/doctor/checks/database.py.md`

**Amaç:** `core/doctor/__init__.py`'deki `check_database_env`,
`check_database_connectivity`, `check_pgvector_ready` implementasyonlarını
domain'e göre gruplanmış ince bir re-export katmanı olarak sunar
(`import core.doctor as _doctor` üzerinden delege eder).
