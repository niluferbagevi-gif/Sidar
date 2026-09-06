# core/db_components/

- **Kaynak dizini:** `core/db_components/` (`__init__.py`, `dialect.py`,
  `migrations.py`)
- **Not dosyası:** `docs/module-notes/core/db_components.md`

## Amaç

`core/db.py.md`'de anlatılan `core/db/` facade parçalanmasının bir adım
gerisinde duran, düşük seviyeli dialect/migration yardımcıları. `core/db/
dialect.py` ve `core/db/alembic_runner.py`, bu paketten re-export ederek
geriye dönük uyumluluğu korur.

- **`dialect.py`:** SQL enjeksiyonuna karşı denetlenmiş, tek doğruluk kaynağı
  yardımcılar. `is_safe_sql_identifier`/`assert_safe_sql_identifier`,
  bağlanamayan tablo/kolon adlarının (bind parametresi değer temsil edemediği
  için) tek regex kaynaklı doğrulamasıdır; `quote_sql_identifier` ve
  `join_sql_identifiers` bunun üzerine kurulu güvenli alıntılama/birleştirme
  sarmalayıcılarıdır. `render_sql_identifier_template` yalnızca doğrulanmış
  identifier/iterable/negatif-olmayan-int token'ları kabul eden, denetlenmiş
  bir `str.format_map` sink'idir — sorgu *değerleri* yine driver bind
  parametresi kullanmalıdır. `parse_asyncpg_affected_rows`, asyncpg'nin
  `"UPDATE 3"` gibi komut etiketinden etkilenen satır sayısını regex ile
  ayrıştırır (eşleşmezse/parse edilemezse `0`, asla exception fırlatmaz).
- **`migrations.py::run_alembic_upgrade_head(*, database_url, alembic_ini,
  migrations_dir)`:** Alembic'i verilen `database_url`'e karşı `head`
  revizyonuna kadar programatik olarak çalıştırır; `alembic` import'u
  fonksiyon içinde (lazy), yalnızca gerçekten çağrıldığında yükleniyor.

## Test kapısı

`tests/unit/core/test_db.py`, `tests/unit/core/test_modular_facades.py`
(facade re-export sözleşmesi), `tests/unit/core/db/test_alembic_runner.py` ve
`tests/unit/test_bandit_comments.py` (identifier doğrulama yardımcılarının
Bandit `# nosec` gerekçe yorumlarını doğrular).
