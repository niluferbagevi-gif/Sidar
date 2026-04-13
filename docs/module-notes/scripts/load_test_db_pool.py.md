# `scripts/load_test_db_pool.py`

- **Kaynak dosya:** `scripts/load_test_db_pool.py`
- **Not dosyası:** `docs/module-notes/scripts/load_test_db_pool.py.md`
- **Kategori:** Veritabanı bağlantı havuzu yük/smoke testi
- **Çalışma tipi:** Python (asyncio)

## 1) Ne işe yarar?

Bu script, PostgreSQL backend üzerinde async connection pool davranışını ölçmek için hafif bir yük testi çalıştırır.

Ürettiği temel metrikler:

- toplam süre (`elapsed_s`)
- p50 latency (`p50_ms`)
- p95 latency (`p95_ms`)
- backend/pool_size/concurrency/requests bilgileri

Başarılı durumda tek satır özet log üretir: `POOL_LOAD_TEST_OK ...`

## 2) Parametreler

- `--database-url` (**zorunlu**): PostgreSQL DSN
- `--concurrency` (varsayılan: `50`)
- `--requests` (varsayılan: `300`)

Örnek:

```bash
python scripts/load_test_db_pool.py \
  --database-url postgresql://sidar:sidar@localhost:5432/sidar \
  --concurrency 50 \
  --requests 300
```

## 3) Çalışma mantığı

1. Script `DATABASE_URL` ve `DB_POOL_SIZE` env değişkenlerini set eder.
2. `Database(Config())` ile bağlantı açılır.
3. Backend `postgresql` değilse hata verilir.
4. `asyncio.Semaphore` ile eşzamanlı worker sayısı sınırlandırılır.
5. Her worker havuzdan bağlantı alıp `SELECT 1` çalıştırır.
6. Latency değerleri toplanır; p50/p95 hesaplanır.
7. Sonuç tek satırda raporlanır.

## 4) Nerede kullanılır?

- `.github/workflows/migration-cutover-checks.yml` içinde migration sonrası doğrulama adımlarında çağrılır.
- `tests/test_migration_ci_guards.py` bu çağrıların CI dosyasında bulunduğunu doğrular.
- Migration/cutover süreçlerinde DB havuz kapasitesi için hızlı smoke testi olarak kullanılır.

## 5) Kullanım çıktısı örneği

```text
POOL_LOAD_TEST_OK backend=postgresql pool_size=50 concurrency=50 requests=300 elapsed_s=1.23 p50_ms=4.20 p95_ms=9.87
```

## 6) Bağımlılıklar

- Python 3
- Proje modülleri: `config.Config`, `core.db.Database`
- PostgreSQL erişimi
- `asyncpg` (Database katmanı üzerinden)

## 7) Sınırlamalar

1. Sadece PostgreSQL backend için tasarlanmıştır.
2. Tek sorgu tipi `SELECT 1` olduğu için uygulama sorgu yükünü birebir temsil etmez.
3. Sonuçlar ortam koşullarına (ağ, disk, CPU, DB konfigürasyonu) duyarlıdır.