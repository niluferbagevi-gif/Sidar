# `runbooks/production-cutover-playbook.md`

- **Kaynak dosya:** `runbooks/production-cutover-playbook.md`
- **Not dosyası:** `docs/module-notes/runbooks/production-cutover-playbook.md.md`
- **Kategori:** Operasyon runbook / production cutover SOP
- **Çalışma tipi:** Markdown (manuel operasyon rehberi)

## 1) Bu dosya ne işe yarar?

Bu runbook, SİDAR’ın **SQLite → PostgreSQL** geçişini üretim ortamında güvenli ve tekrarlanabilir şekilde yürütmek için adım adım SOP (Standard Operating Procedure) sağlar.

Kapsadığı ana alanlar:

- Alembic migration zinciri (`upgrade/downgrade/upgrade`)
- Veri taşıma provası ve gerçek taşıma (`scripts/migrate_sqlite_to_pg.py`)
- Rollback adımları
- Zero-trust sandbox rollout (gVisor / Kata)
- QA/reviewer kalite kapıları
- CI doğrulama adımları ve migration disiplini

## 2) Bölümler ve operasyonel anlamı

### 2.1 Alembic migration zinciri

Runbook, production geçişten önce aşağıdaki doğrulamayı önerir:

1. `upgrade head`
2. `downgrade -1` (veya CI’de `downgrade base`)
3. tekrar `upgrade head`

Amaç: migration zincirinin hem ileri hem geri yönde tutarlı çalıştığını doğrulamak.

### 2.2 Veri taşıma (SQLite → PostgreSQL)

Önerilen akış:

- Bakım penceresi açılır (write trafiği kesilir)
- SQLite yedeği alınır (`sqlite3 ... .backup`)
- Hedef PostgreSQL şeması Alembic ile hazırlanır
- Önce `--dry-run`, sonra gerçek migration çalıştırılır
- `DATABASE_URL` PostgreSQL’e çevrilir ve trafik geri açılır

### 2.3 Rollback planı

- İlk 24 saat SQLite backup tutulur
- Kritik hata halinde:
  - bakım moduna dönülür,
  - `DATABASE_URL` SQLite’a geri alınır,
  - servis yeniden başlatılır.

### 2.4 Güvenlik ve kalite kapıları

Runbook, cutover’ı yalnızca DB geçişi olarak değil; aynı zamanda:

- sandbox runtime sertleştirmesi (gVisor/Kata),
- reviewer ve test kapsamı kalite kapıları,
- CI migration rehearsal adımları

ile birlikte ele alır.

## 3) Nerede kullanılıyor?

- Operasyon/canlıya geçiş süreçlerinde ana referans runbook olarak kullanılır.
- `README.md` içinde SQLite → PostgreSQL geçiş adımları için doğrudan bu dosyaya yönlendirme vardır.
- `PROJE_RAPORU.md` içinde runbook envanteri içinde listelenir.
- Test tarafında `tests/test_migration_assets.py`, bu dosyanın varlığını ve temel içerik beklentilerini doğrular.

## 4) İlişkili CI ve script bileşenleri

Bu runbook’un anlattığı adımların CI karşılığı `.github/workflows/migration-cutover-checks.yml` dosyasında bulunur:

- PostgreSQL üzerinde Alembic zincir doğrulaması
- `scripts/migrate_sqlite_to_pg.py --dry-run` provası
- `scripts/load_test_db_pool.py --concurrency 50 --requests 300` havuz smoke/load testi

Dolayısıyla runbook ile CI kapıları arasında bire bir operasyonel hizalama vardır.

## 5) Kullanım örnekleri (runbook içinden özet)

### Örnek A — Alembic doğrulama

```bash
alembic -x database_url="postgresql+psycopg://user:pass@host:5432/sidar" upgrade head
alembic -x database_url="postgresql+psycopg://user:pass@host:5432/sidar" downgrade -1
alembic -x database_url="postgresql+psycopg://user:pass@host:5432/sidar" upgrade head
```

### Örnek B — Migration dry-run ve gerçek taşıma

```bash
python scripts/migrate_sqlite_to_pg.py \
  --sqlite-path data/sidar.db \
  --postgres-dsn postgresql://user:pass@host:5432/sidar \
  --dry-run

python scripts/migrate_sqlite_to_pg.py \
  --sqlite-path data/sidar.db \
  --postgres-dsn postgresql://user:pass@host:5432/sidar
```

### Örnek C — Host sandbox kurulumu

```bash
sudo bash scripts/install_host_sandbox.sh --mode gvisor
sudo bash scripts/install_host_sandbox.sh --mode kata
sudo bash scripts/install_host_sandbox.sh --mode both --dry-run
```

## 6) Bağımlı dosyalar / önkoşullar

Runbook’u uygularken aşağıdaki dosya ve bileşenler kritik bağımlılıktır:

- `alembic.ini`
- `migrations/env.py`
- `migrations/versions/0001_baseline_schema.py`
- `scripts/migrate_sqlite_to_pg.py`
- `scripts/load_test_db_pool.py`
- `scripts/install_host_sandbox.sh`
- `.github/workflows/migration-cutover-checks.yml`

Ek olarak, hedef PostgreSQL erişimi, uygun kullanıcı yetkileri ve bakım penceresi yönetimi gerekir.

## 7) Çıktı / sonuç beklentileri

Başarılı cutover sonrası beklenen sonuçlar:

1. Alembic zinciri hatasız tamamlanır.
2. Dry-run satır sayıları beklenen tablo dağılımını verir.
3. Gerçek migration sonrası uygulama PostgreSQL backend ile ayağa kalkar.
4. Havuz smoke/load testi kabul edilebilir gecikme ile `POOL_LOAD_TEST_OK` üretir.
5. Sağlık kontrolleri ve kritik kullanıcı akışları sorunsuz döner.

## 8) Riskler ve dikkat edilmesi gerekenler

1. Runbook adımları sıradan bağımsız değildir; bakım penceresi ve rollback hazırlığı atlanmamalıdır.
2. `--dry-run` geçmek, gerçek taşıma öncesi zorunlu prova olarak ele alınmalıdır.
3. `TRUNCATE` temelli migration yaklaşımında hedef DB’de mevcut verinin silineceği unutulmamalıdır.
4. Sandbox runtime rollout adımları production host özelliklerine göre aşamalı uygulanmalıdır.
5. CI green olsa bile production veri hacmi/farklılığı nedeniyle kontrollü canary yaklaşımı önerilir.