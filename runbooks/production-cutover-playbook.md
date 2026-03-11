# Production Cutover Playbook (SQLite -> PostgreSQL)

Bu rehber, SİDAR'ın üretim ortamında PostgreSQL'e güvenli geçişi için minimum adımları tanımlar.

## 1) Alembic migration zinciri

1. Bağımlılıkları kurun:
   ```bash
   pip install -r requirements-dev.txt
   ```
2. Mevcut bağlantıyı override ederek migration çalıştırın:
   ```bash
   alembic -x database_url="postgresql+psycopg://user:pass@host:5432/sidar" upgrade head
   ```
3. Geri alma doğrulaması için:
   ```bash
   alembic -x database_url="postgresql+psycopg://user:pass@host:5432/sidar" downgrade -1
   alembic -x database_url="postgresql+psycopg://user:pass@host:5432/sidar" upgrade head
   ```

## 2) Veri taşıma (SQLite -> PostgreSQL)

1. Bakım penceresi açın (yazma trafiğini durdurun).
2. SQLite veritabanını yedekleyin:
   ```bash
   sqlite3 data/sidar.db ".backup 'data/sidar.backup.db'"
   ```
3. PostgreSQL şemasını Alembic ile oluşturun (adım 1).
4. Dönüşüm/taşıma için `scripts/migrate_sqlite_to_pg.py` scriptini (veya kurumsal ETL aracınızı) kullanın.
5. Önce `--dry-run` ile satır sayılarını doğrulayın, ardından gerçek taşıma çalıştırın.


Örnek:
```bash
python scripts/migrate_sqlite_to_pg.py \
  --sqlite-path data/sidar.db \
  --postgres-dsn postgresql://user:pass@host:5432/sidar \
  --dry-run

python scripts/migrate_sqlite_to_pg.py \
  --sqlite-path data/sidar.db \
  --postgres-dsn postgresql://user:pass@host:5432/sidar
```

6. Uygulama `DATABASE_URL` ayarını PostgreSQL'e çevirin.
7. Trafiği yeniden açın ve sağlık kontrollerini izleyin.

## 3) Rollback planı

- İlk 24 saat `data/sidar.backup.db` saklanmalıdır.
- Kritik hata halinde:
  1. Trafiği tekrar bakım moduna alın.
  2. `DATABASE_URL` değerini SQLite'a döndürün.
  3. Servisi yeniden başlatın.

## 4) Zero-trust izolasyon ilerleme adımları

- Docker runtime için `runsc` (gVisor) veya Kata Containers staging ortamında doğrulanmalı.
- CI pipeline'da en az bir job, sandbox testlerini `runsc`/Kata ile çalıştırmalı.
- Production rollout öncesi kaçış (container breakout) senaryoları için güvenlik testi raporu zorunlu olmalı.

## 5) QA kapıları (ReviewerAgent)

- ReviewerAgent prompt'larına "geniş regresyon" zorunluluğu eklenmeli.
- `run_tests` adımı sadece değişen dosyaları değil, ilgili bağımlı test kümelerini de çalıştırmalı.
- PR başına minimum: birim test + entegrasyon testi + coverage raporu kontrolü (%95 barajı).

## CI Otomasyon Notu (yeni)

- `.github/workflows/migration-cutover-checks.yml` ile aşağıdaki kapılar otomatik doğrulanır:
  1. PostgreSQL üzerinde `alembic upgrade head -> downgrade base -> upgrade head`
  2. `scripts/migrate_sqlite_to_pg.py --dry-run` ile staging provaları
  3. `scripts/load_test_db_pool.py --concurrency 50` ile asyncpg havuz smoke/load testi

## 6) Migration sürekliliği (operasyon disiplini)

- Şema değişiklikleri **manuel SQL ile değil**, yalnızca Alembic revizyonları ile yapılmalıdır.
- Her DB değişikliği için standart akış:
  1. `alembic revision -m "<değişiklik adı>"`
  2. migration dosyasına `upgrade/downgrade` adımlarını yaz
  3. staging'de `alembic upgrade head` + `alembic downgrade base` + `alembic upgrade head` doğrula
  4. PR'a migration etkisi ve rollback notu ekle
- `schema_versions` uygulama telemetrisi için tutulur; gerçek migration kaynağı `alembic_version` tablosudur.

## 7) gVisor/Kata rollout doğrulama checklist'i

- Staging host üzerinde runtime kurulumu doğrula (`docker info | grep -i runtime`).
- `DOCKER_MICROVM_MODE=gvisor` için `runsc`, `DOCKER_MICROVM_MODE=kata` için `kata-runtime` çözümlemesini CI testleriyle doğrula.
- Production rollout öncesi en az bir smoke test: sandbox kod çalıştırma akışı micro-VM runtime ile geçmelidir.