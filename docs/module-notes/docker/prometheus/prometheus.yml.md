# 3.23 `docker/` ve `runbooks/` — Telemetri ve Production Altyapı Dosyaları

## Rapor İçeriği (Taşınan Bölüm)

**Amaç:** Üretim ortamında gözlemlenebilirlik (observability), telemetri görselleştirme ve canlıya geçiş (cutover) operasyonlarını tekrarlanabilir SOP'larla yönetmek.

**Özellikler (Kurumsal V3.0 DevOps):**
- **Tek komutla observability orkestrasyonu (`docker-compose.yml`):** Uygulama servisleriyle birlikte `prometheus` ve `grafana` konteynerlerini tek bir `docker compose up -d` akışında ayağa kaldırır; servis bağımlılıkları (`depends_on`) ile başlangıç sırası yönetilir.
- **Prometheus scrape topolojisi (`docker/prometheus/prometheus.yml`):** `metrics_path: /metrics/llm/prometheus` üzerinden `sidar-web:7860` hedefini container ağında kazır; `global.scrape_interval: 15s` ile uygulama içi iş yükünü artırmadan dıştan metrik toplama modeli uygular.
- **Grafana auto-provisioning (`docker/grafana/provisioning/*`):** Datasource (`datasources/prometheus.yml`) ve dashboard provider (`dashboards/dashboards.yml`) tanımları kod olarak tutulur; konteyner her açıldığında manuel adım olmadan hazır dashboard'lar yüklenir.
- **JSON-as-Code dashboard (`docker/grafana/dashboards/sidar-llm-overview.json`):** LLM token, maliyet ve latency metriklerini standart panel setiyle sunar; dashboard değişiklikleri sürüm kontrolüne girerek denetlenebilir hale gelir.
- **Kurumsal cutover/rollback playbook (`runbooks/production-cutover-playbook.md`):** SQLite → PostgreSQL geçişinde pre-flight, Alembic migration zinciri, `--dry-run` veri taşıma provası ve kritik hata durumunda rollback adımlarını SOP düzeyinde tanımlar.
- **Host sandbox rollout notları (`runbooks/production-cutover-playbook.md` + `scripts/install_host_sandbox.sh`):** gVisor/Kata runtime kurulumu, doğrulama checklist'i ve kontrollü restart adımlarıyla production güvenlik sertleşmesini operasyonel sürece bağlar.

---
