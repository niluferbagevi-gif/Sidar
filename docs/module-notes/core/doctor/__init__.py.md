# `core/doctor/__init__.py` — Kurulum/Hazırlık Doktoru (Ana Modül)

- **Kaynak dosya:** `core/doctor/__init__.py`
- **Not dosyası:** `docs/module-notes/core/doctor/__init__.py.md`

**Amaç:** `sidar doctor` komutu ve installer alt komutlarının kullandığı,
bilinçli olarak hafif/sınırlı kapsamlı sağlık kontrollerinin canonical
implementasyonu. `core/doctor/checks/*.py` (security/database/gpu/rag/redis)
domain dosyaları artık kendi kontrollerinin gerçek gövdesini barındırıyor;
`__init__.py`'deki karşılıkları (`check_environment_profile`,
`check_database_env` vb.) bunlara delege eden ince pass-through'lardır.
Aynı şekilde `run_doctor_report()`, `_apply_database_env_fix()` ve `main()`
artık `core/doctor/facade.py`'ye delege eden pass-through'lardır (bkz. o
dosyanın notu) — `__init__.py` bu üçü için de dinamik monkeypatch
seam'lerini (`_run_command`, `_resolved_database_urls`, `_rag_readiness_state`,
`BASE_DIR` vb.) ve doğrudan kendi gerçek implementasyonu olan
`check_uv()`/`check_prometheus_runtime()`/`check_migrations()`/
`check_agent_catalog()`/`check_supervisor_routing()`/`check_websocket_routes()`/
`check_model()` fonksiyonlarını barındırmaya devam ediyor.

**Özellikler (öne çıkan kontroller):**
- `check_uv()`, `check_prometheus_runtime()` — araç/servis erişilebilirliği.
- `check_database_env()`, `check_database_connectivity()`, `check_pgvector_ready()`
  — gerçek gövdeleri `core/doctor/checks/database.py`'de; Postgres DSN
  normalizasyonu ve URL/exception metinlerindeki şifrelerin maskelenmesi de
  orada (`_normalize_postgres_dsn`, `_redact_url`, `_redact_exception_text`).
- `check_rag_index_ready()`, `check_graphrag_entity_memory_ready()`,
  `check_rag_readiness()` — gerçek gövdeleri `core/doctor/checks/rag.py`'de.
- `check_environment_profile()` — gerçek gövdesi `core/doctor/checks/security.py`'de.
- `check_gpu()`, `check_gpu_memory_config()`, `check_docker_test_image()` —
  gerçek gövdeleri `core/doctor/checks/gpu.py`'de.
- `check_migrations()`, `check_agent_catalog()`, `check_supervisor_routing()`,
  `check_websocket_routes()`, `check_model()` — bu modülün kendi gerçek
  implementasyonları (taşınmadılar; bkz. `core/doctor/facade.py.md`).
- `run_doctor_report()` — gerçek gövdesi `core/doctor/facade.py`'de; tüm
  kontrolleri toplayıp `core/doctor/reporting.py` formatına uygun rapor
  üretir. `main(argv)` — gerçek gövdesi de `core/doctor/facade.py`'de;
  `python -m core.doctor` CLI giriş noktası.
- Güvenlik: auto-fix komutları `core/doctor/models.py`'deki regex
  allowlist'lerle doğrulanır; URL/exception metinlerindeki şifreler ilgili
  `checks/*.py` ve `facade.py` modüllerindeki `_redact_*` fonksiyonlarıyla
  loglama öncesi maskelenir.
