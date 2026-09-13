# `core/doctor/__init__.py` — Kurulum/Hazırlık Doktoru (Ana Modül)

- **Kaynak dosya:** `core/doctor/__init__.py`
- **Not dosyası:** `docs/module-notes/core/doctor/__init__.py.md`

**Amaç:** `sidar doctor` komutu ve installer alt komutlarının kullandığı,
bilinçli olarak hafif/sınırlı kapsamlı sağlık kontrollerinin canonical
implementasyonu (1900+ satır). `core/doctor/checks/*.py` domain dosyaları bu
modüldeki fonksiyonları yalnızca re-export eder (bkz. o dosyaların notları).

**Özellikler (öne çıkan kontroller):**
- `check_uv()`, `check_prometheus_runtime()` — araç/servis erişilebilirliği.
- `check_database_env()`, `check_database_connectivity()`, `check_pgvector_ready()`
  — Postgres DSN normalizasyonu (`_normalize_postgres_dsn`), URL'deki şifreyi
  `_redact_url`/`_redact_exception_text` ile loglardan maskeleme, bağlantı
  hata mesajlarına yönlendirici rehberlik (`_postgres_connectivity_failure_guidance`).
- `check_rag_index_ready()`, `check_graphrag_entity_memory_ready()`,
  `check_rag_readiness()` — RAG/GraphRAG index durumu.
- `check_environment_profile()` — `.env` profil tutarlılığı.
- `check_gpu()`, `check_gpu_memory_config()`, `check_docker_test_image()`.
- `check_migrations()`, `check_agent_catalog()`, `check_supervisor_routing()`,
  `check_websocket_routes()`, `check_model()`.
- `run_doctor_report()` — tüm kontrolleri toplayıp `core/doctor/reporting.py`
  formatına uygun rapor üretir; `main(argv)` — `python -m core.doctor` CLI
  giriş noktası.
- Güvenlik: URL/exception metinlerindeki şifreler `_redact_*` fonksiyonlarıyla
  loglama öncesi maskelenir; auto-fix komutları `core/doctor/models.py`'deki
  regex allowlist'lerle doğrulanır.
