# `core/doctor/checks/database.py` — Veritabanı/pgvector Doktor Kontrolleri

- **Kaynak dosya:** `core/doctor/checks/database.py`
- **Not dosyası:** `docs/module-notes/core/doctor/checks/database.py.md`

**Amaç:** `check_database_env()`, `check_database_connectivity()`,
`check_pgvector_ready()`'nin gerçek gövdelerini ve yalnızca bu üç
fonksiyonun call graph'ına özel 8 private helper'ı (`_is_postgres_url`,
`_redact_url`, `_redact_exception_text`, `_postgres_connectivity_failure_guidance`,
`_source_message`, `_database_name`, `_validate_postgres_env_sync`,
`_validate_database_url_pair_sync`) barındırır — `redis.py::check_redis`
ile aynı desende, kendi kendine yeten bir implementasyon
(`docs/REFACTOR_PLAN.md`'nin `core/doctor/__init__.py` maddesinde
`security.py::check_environment_profile`'dan sonra taşınan ikinci dilim).
`core/doctor/__init__.py`'deki üç fonksiyon artık bu modüle deferred-import
ile delege eden ince pass-through'lardır.

**Kritik detay — hangi helper'lar `__init__.py`'de kaldı:**
`_resolved_database_urls`, `_parse_url`, `_run_coro_sync`,
`_probe_postgres_connectivity` ve `_dotenv_source_report` bilinçli olarak
`__init__.py`'de bırakıldı ve `checks/database.py` bunlara `_doctor.X(...)`
dinamik referansla erişir — asla bare/local isimle değil:

- `_run_coro_sync`, `_probe_postgres_connectivity`, `_resolved_database_urls`
  testlerde doğrudan `monkeypatch.setattr(doctor, "_run_coro_sync", ...)`
  gibi isimle hedeflenen monkeypatch seam'leridir; bunları taşımak bu
  testleri sessizce production davranışına düşürürdü.
- `_resolved_database_urls`/`_parse_url` ayrıca `core/doctor/__init__.py`'nin
  henüz taşınmamış RAG readiness fonksiyonlarıyla da paylaşılıyor.
- `_dotenv_source_report` ilk denemede yanlışlıkla taşınmıştı — çok satırlı
  `monkeypatch.setattr(\n    doctor,\n    "_dotenv_source_report",\n    ...\n)`
  çağrı biçimi tek satırlık grep taramasında gözden kaçmıştı. Testler
  (`test_database_env_flags_unattributed_database_url_as_parent_shell_drift`
  ve benzerleri) bunu hemen yakaladı; helper `__init__.py`'ye geri taşındı.

**Özellikler:**
- `check_database_env()` — `DATABASE_URL`/`SIDAR_CONTAINER_DATABASE_URL`/
  `POSTGRES_*` env senkronizasyonunu, zayıf parola ve parent-shell
  attribution durumunu doğrular.
- `check_database_connectivity()` — asyncpg ile canlı PostgreSQL bağlantı
  probe'u çalıştırır, hata sınıflandırması ve SSL query-param düzeltme
  önerisi üretir.
- `check_pgvector_ready(database_connectivity=None)` — `pgvector` uzantısının
  kurulu olup olmadığını, isteğe bağlı olarak `check_database_connectivity`
  sonucunu yeniden kullanarak doğrular.
