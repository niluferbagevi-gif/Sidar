
# Production Cutover Playbook (SQLite -> PostgreSQL)

Bu rehber, SİDAR'ın üretim ortamında PostgreSQL'e güvenli geçişi için minimum adımları tanımlar.

## 0) Güncel dağıtım yüzeyi özeti

### Docker Compose servisleri

| Servis | Amaç | Varsayılan Port |
|---|---|---:|
| `redis` | rate limiting / cache | 6379 |
| `postgres` | uygulama veritabanı | 5432 |
| `sidar-web` | CPU web/API | 7860 |
| `sidar-web-gpu` | GPU web/API | 7861→7860 |
| `sidar-ai` | CPU CLI/worker | - |
| `sidar-gpu` | GPU CLI/worker | - |
| `jaeger` | trace UI + OTLP gRPC | 16686 / 4317 |
| `prometheus` | metrics scrape | 9090 |
| `grafana` | dashboard | 3000 |

> Not: Compose dosyası Zipkin veya OTel Collector servisini başlatmaz; bu bileşenler Helm chart tarafında üretim/staging overlay'leriyle devreye alınır.

### Helm / production overlay yüzeyi

| Bileşen | Durum | Not |
|---|---|---|
| `web` | aktif | servis portu `7860`, production overlay'de 3 replika |
| `ai-worker` | aktif | production overlay'de 2 replika |
| `redis` | aktif | varsayılan persistent volume |
| `postgresql` | aktif | pgvector/kurumsal DB omurgası için temel katman |
| `otel-collector` | aktif | OTLP gRPC `4317`, HTTP `4318` |
| `jaeger` | aktif | query UI `16686` |
| `zipkin` | opsiyonel aktif | UI `9411` |
| Grafana SLO dashboard | aktif | `monitoring.sloDashboard.enabled=true` |

## 1) Alembic migration zinciri

1. Bağımlılıkları kurun:
   ```bash
   uv pip install -e ".[dev]"
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

> ⚠️ **Veri kaybı güvenlik notu (kritik):**
> Production/staging ortamlarında kurulum betiğinin parola hardening tetiklediği otomatik PostgreSQL volume reset akışı **varsayılan olarak devre dışıdır**.
> Cutover sırasında kalıcı volume'leri (`*_postgres_data` / `sidar_postgres_data`) otomatik veya manuel olarak silmeyin.
> Sadece felaket kurtarma / bilinçli reset senaryosunda ve güncel yedek doğrulandıktan sonra operatör onayıyla hareket edin.

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

## 8) Host seviyesinde sandbox runtime otomasyonu

`gVisor` / `Kata` kurulumu için otomasyon scripti eklendi:

```bash
sudo bash scripts/install_host_sandbox.sh --mode gvisor
# veya
sudo bash scripts/install_host_sandbox.sh --mode kata
# veya
sudo bash scripts/install_host_sandbox.sh --mode both
```

Dry-run ve kontrollü rollout:

```bash
sudo bash scripts/install_host_sandbox.sh --mode gvisor --dry-run
sudo bash scripts/install_host_sandbox.sh --mode gvisor --no-restart
```

Script; runtime binary kurulumunu yapar, `/etc/docker/daemon.json` içinde `runtimes` alanını günceller, opsiyonel olarak Docker'ı restart eder ve `hello-world` ile runtime smoke testlerini çalıştırır.
## 9) APM (Jaeger/Zipkin) production devreye alma

Helm chart artık OTLP trafiğini `otel-collector` üzerinden Jaeger veya Zipkin backend'ine yönlendirebilir.

### 9.1 Dağıtım

Jaeger backend ile:

```bash
helm upgrade --install sidar ./helm/sidar \
  -f helm/sidar/values.yaml \
  -f helm/sidar/values-prod.yaml \
  --set apm.enabled=true \
  --set apm.backend=jaeger
```

Zipkin backend ile:

```bash
helm upgrade --install sidar ./helm/sidar \
  -f helm/sidar/values.yaml \
  -f helm/sidar/values-prod.yaml \
  --set apm.enabled=true \
  --set apm.backend=zipkin
```

### 9.2 Doğrulama

- `web` ve `ai-worker` pod'larında `OTEL_EXPORTER_ENDPOINT` değeri cluster içi collector servisine (`*-otel-collector:4317`) işaret etmelidir.
- Jaeger kullanılıyorsa query UI servisi: `*-jaeger:16686`
- Zipkin kullanılıyorsa UI servisi: `*-zipkin:9411`

### 9.3 SLO Dashboard

Chart, Grafana sidecar taraması için `grafana_dashboard=1` etiketli `sidar-slo-overview` dashboard ConfigMap'i üretir.
Önerilen başlangıç SLO metrikleri:

- Availability (`up`) ≥ 99.9%
- P95 latency (`http_server_requests_seconds_bucket`) ≤ hedef eşik
- 5xx error rate (`http_server_requests_seconds_count{status=~"5.."}`) ≤ hedef eşik

## 10) PostgreSQL ve Redis pool doğrulaması

Cutover öncesi aşağıdaki env ayarları gözden geçirilmelidir:

- `DB_POOL_SIZE`: PostgreSQL `asyncpg` havuz üst sınırı. Staging için başlangıç `8`, production için `30` önerilir.
- `REDIS_MAX_CONNECTIONS`: Redis istemcileri (`web_server`, semantic cache, event bus) için bağlantı üst sınırı. Staging için `60`, production için `200` önerilir.
- Uygulama pod/container loglarında bağlantı timeout veya pool exhaustion sinyali görülürse önce bu iki değer ve veritabanı/Redis CPU-RAM grafikleri birlikte incelenmelidir.

Doğrulama komutları:

```bash
python scripts/load_test_db_pool.py --concurrency 50
python - <<'PY'
from config import Config
cfg = Config()
print({"db_pool_size": cfg.DB_POOL_SIZE, "redis_max_connections": cfg.REDIS_MAX_CONNECTIONS})
PY
```

## 11) Deployment komutları

### 11.1 Helm ile Kubernetes deploy

```bash
helm upgrade --install sidar ./helm/sidar \
  -f helm/sidar/values.yaml \
  -f helm/sidar/values-prod.yaml

kubectl rollout status deploy/sidar-web
kubectl rollout status deploy/sidar-ai-worker
```

### 11.2 Docker Compose ile VPS deploy

```bash
docker compose pull
docker compose up -d postgres redis jaeger prometheus grafana sidar-web
docker compose ps
```

## 12) Grafana dashboard doğrulaması

Grafana ayağa kalktıktan sonra aşağıdaki dashboard dosyalarının yüklendiğini doğrulayın:

- `docker/grafana/dashboards/sidar-llm-overview.json`
- `grafana/dashboards/sidar_overview.json`

Operasyon başlangıcında şu sinyalleri izleyin:

- LLM token / maliyet panelleri
- ajan delegasyon gecikmeleri / tepki süreleri
- Redis ve PostgreSQL sağlık sinyalleri
- tracing hattı (Jaeger/OTel) ile yavaş istekler
