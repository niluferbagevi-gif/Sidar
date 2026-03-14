# 3.22 `migrations/` ve `scripts/` — Geçiş ve Operasyon Araçları

**Amaç:** Projenin tekil kullanıcıdan kurumsal veritabanına pürüzsüz geçişini sağlayan veri tabanı, migrasyon ve operasyonel otomasyon araçlarını standartlaştırmak.

**Özellikler (Kurumsal V3.0):**
- **Alembic ile otomatik şema sürümleme (`migrations/`):** `alembic.ini` + `migrations/env.py` altyapısı ile ortam-bağımsız veritabanı revizyon yönetimi yapılır; `DATABASE_URL` veya `-x database_url` üzerinden dinamik bağlantı çözümleme desteklenir.
- **Baseline kurulum garantisi (`migrations/versions/0001_baseline_schema.py`):** `users`, `auth_tokens`, `user_quotas`, `provider_usage_daily`, `sessions`, `messages`, `schema_versions` tablolarını ve kritik indeksleri tek revizyonda kurar; yeni ortamların sıfırdan güvenli bootstrap'ini sağlar.
- **SQLite → PostgreSQL veri taşıma (`scripts/migrate_sqlite_to_pg.py`):** Yerel SQLite verilerini tablo sırasına bağlı ve tutarlı biçimde PostgreSQL'e aktarır; `asyncio`/`asyncpg` tabanlı çalışır ve `--dry-run` ile kayıpsız geçiş öncesi doğrulama yapılabilir.
- **Docker sandbox güvenli host kurulumu (`scripts/install_host_sandbox.sh`):** gVisor/Kata runtime kurulumunu, Docker daemon runtime kaydını ve opsiyonel servis restart akışını otomatikleştirir (`--mode gvisor|kata|both`, `--dry-run`).
- **Veritabanı yük/stres testi (`scripts/load_test_db_pool.py`):** Asenkron connection pool davranışını eşzamanlı yükte ölçerek çoklu ajan senaryolarında havuz limitlerinin doğrulanmasını destekler.
- **Kalite ve CI/CD metrik denetimi (`scripts/audit_metrics.sh`, `scripts/collect_repo_metrics.sh`):** Satır sayısı/audit metriklerini ve repo özet metriklerini otomatik üretir; CI pipeline'larına doğrudan entegre edilebilir.

---
