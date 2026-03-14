# `.github/workflows/migration-cutover-checks.yml`

- **Kaynak dosya:** `.github/workflows/migration-cutover-checks.yml`
- **Not dosyası:** `docs/module-notes/.github/workflows/migration-cutover-checks.yml.md`
- **Kategori:** Migration/cutover rehearsal CI workflow
- **Çalışma tipi:** Workflow YAML (push + pull_request)

## 1) Bu workflow ne işe yarar?

`migration-cutover-checks.yml`, SQLite → PostgreSQL geçişi için **rehearsal (prova) kalite kapısı** sağlar.

Ana hedefleri:

- PostgreSQL üzerinde Alembic zincir doğrulaması,
- örnek SQLite fixture ile migration dry-run provası,
- PostgreSQL connection pool smoke/load testi.

Böylece production cutover öncesi kritik veritabanı geçiş adımları CI içinde düzenli olarak doğrulanır.

## 2) Tetikleme ve runtime bileşenleri

- **Trigger:** `push`, `pull_request`
- **Runner:** `ubuntu-latest`
- **Service container:** `postgres:16`
  - `POSTGRES_USER=postgres`
  - `POSTGRES_PASSWORD=postgres`
  - `POSTGRES_DB=sidar`
  - healthcheck: `pg_isready -U postgres -d sidar`
- **Env:** `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/sidar`

## 3) Adım adım iş akışı

1. **Checkout + Python setup (3.11)**
2. **Dependency install** (`requirements.txt` + `requirements-dev.txt`)
3. **Alembic zinciri**
   - `upgrade head`
   - `downgrade base`
   - tekrar `upgrade head`
4. **SQLite fixture üretimi**
   - inline Python ile `temp/migration_dry_run.db` oluşturulur
   - migration scriptinin beklediği tablo seti ve örnek satırlar eklenir
5. **SQLite → PostgreSQL dry-run provası**
   - `python scripts/migrate_sqlite_to_pg.py --dry-run`
6. **PostgreSQL pool smoke/load testi**
   - `python scripts/load_test_db_pool.py --concurrency 50 --requests 300`

## 4) Nerede kullanılıyor?

- `runbooks/production-cutover-playbook.md` içindeki CI otomasyon notunun teknik karşılığıdır.
- `tests/test_migration_ci_guards.py`, workflow içinde zorunlu kapı komutlarının bulunduğunu doğrular.
- `tests/test_migration_assets.py`, cutover varlıklarının (runbook/migration dosyaları) varlığını ayrıca kontrol eder.

## 5) Kullanım ve sonuç örnekleri

### Örnek A — Alembic zinciri başarılı

Beklenti: upgrade/downgrade/upgrade adımları hata vermeden tamamlanır.

### Örnek B — Dry-run migration

```bash
python scripts/migrate_sqlite_to_pg.py \
  --sqlite-path temp/migration_dry_run.db \
  --postgres-dsn "$DATABASE_URL" \
  --dry-run
```

Beklenti: tablo bazında `[DRY-RUN] ...: <n> row` satırları üretilir.

### Örnek C — Pool smoke/load

```bash
python scripts/load_test_db_pool.py \
  --database-url "$DATABASE_URL" \
  --concurrency 50 \
  --requests 300
```

Beklenti: `POOL_LOAD_TEST_OK ...` formatında tek satır özet çıktısı.

## 6) Bağımlılıklar

- PostgreSQL servis container (GitHub Actions service)
- Alembic migration dosyaları (`alembic.ini`, `migrations/`)
- Scriptler:
  - `scripts/migrate_sqlite_to_pg.py`
  - `scripts/load_test_db_pool.py`
- Python bağımlılıkları (`asyncpg`, alembic, SQLAlchemy vb.)

## 7) Dikkat edilmesi gerekenler

1. Bu workflow DB migration geçerliliğini ölçer; uygulamanın tüm fonksiyonel test kapsamının yerine geçmez.
2. Fixture veri seti küçük ve sentetiktir; production veri büyüklüğü/perf davranışı farklı olabilir.
3. Service healthcheck başarısız olursa sonraki migration adımları anlamsız hale gelir; log analizi önemlidir.
4. `DATABASE_URL` workflow içinde sabitlenmiştir; özel ortamlarda secret/env yönetimi gerekebilir.