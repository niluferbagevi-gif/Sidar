# `scripts/migrate_sqlite_to_pg.py`

- **Kaynak dosya:** `scripts/migrate_sqlite_to_pg.py`
- **Not dosyası:** `docs/module-notes/scripts/migrate_sqlite_to_pg.py.md`
- **Kategori:** Veri geçiş aracı (SQLite → PostgreSQL)
- **Çalışma tipi:** Python (sqlite3 + asyncpg)

## 1) Ne işe yarar?

Bu script, SQLite veritabanındaki verileri PostgreSQL’e taşır.

Özellikler:

- Sabit tablo sırası ile deterministic kopyalama (`TABLES_IN_ORDER`)
- Her tablo için satır sayısı raporu
- `--dry-run` ile yalnızca okunacak satır sayısını gösterme
- Gerçek modda hedef tabloda `TRUNCATE ... RESTART IDENTITY CASCADE` sonrası yeniden yükleme

## 2) Parametreler

- `--sqlite-path` (**zorunlu**): kaynak SQLite dosya yolu
- `--postgres-dsn` (**zorunlu**): hedef PostgreSQL DSN
- `--dry-run` (opsiyonel): yazmadan sadece raporla

Örnek:

```bash
python scripts/migrate_sqlite_to_pg.py \
  --sqlite-path data/sidar.db \
  --postgres-dsn postgresql://user:pass@localhost:5432/sidar \
  --dry-run
```

## 3) Çalışma mantığı

1. `asyncpg` import edilir; yoksa anlamlı hata fırlatılır.
2. SQLite dosyasının varlığı doğrulanır.
3. PostgreSQL bağlantısı açılır.
4. `TABLES_IN_ORDER` sırasıyla her tablo için:
   - SQLite’tan tüm satırlar okunur,
   - kolon listesi çıkarılır,
   - PostgreSQL INSERT sorgusu hazırlanır,
   - dry-run değilse hedef tablo truncate edilip satırlar yazılır.
5. Her tablo için `[DRY-RUN]` veya `[MIGRATED]` satırı basılır.

## 4) Nerede kullanılır?

- `.github/workflows/migration-cutover-checks.yml` içinde migration dry-run adımında çalıştırılır.
- `tests/test_migration_ci_guards.py` CI dosyasında script çağrısını kontrol eder.
- Cutover sırasında SQLite’tan PostgreSQL’e veri taşıma sürecinin otomasyonu için kullanılır.

## 5) Örnek çıktı

Dry-run örneği:

```text
[DRY-RUN] users: 12 row
[DRY-RUN] auth_tokens: 3 row
...
```

Gerçek migration örneği:

```text
[MIGRATED] users: 12 row
[MIGRATED] auth_tokens: 3 row
...
```

## 6) Bağımlılıklar

- Python 3
- Standart kütüphane: `sqlite3`, `argparse`, `asyncio`, `pathlib`
- Harici: `asyncpg`
- Hedef PostgreSQL erişimi ve uygun tablo şeması

## 7) Sınırlamalar / dikkat

1. Tablo isimleri ve sırası `TABLES_IN_ORDER` ile sabittir.
2. Hedef tabloların şeması migration ile önceden hazır olmalıdır.
3. Gerçek modda `TRUNCATE ... CASCADE` kullanıldığı için mevcut veriler silinir.
4. Çok büyük veri setlerinde satır-satır insert performans maliyeti oluşabilir.