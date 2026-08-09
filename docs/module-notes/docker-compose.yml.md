# docker-compose.yml

- **Kaynak dosya:** `docker-compose.yml`
- **Not dosyası:** `docs/module-notes/docker-compose.yml.md`
- **Amaç:** Servis orkestrasyonu için docker-compose tanımı.
- **Durum:** İncelendi ve `docs/module-notes` altında dokümante edildi.

- **Observability güncellemesi:** Jaeger image'i manifesti yayınlanmış `jaegertracing/all-in-one:1.63.0` olarak pinlenir; Redis `redis:7.4-alpine`, PostgreSQL+pgvector `pgvector/pgvector:0.8.1-pg16`, Prometheus `prom/prometheus:v2.54.1` ve Grafana `grafana/grafana:11.2.0` sürümlerine sabitlenir; Redis/PostgreSQL/cAdvisor exporter servisleri Prometheus tarafından scrape edilecek şekilde compose topolojisine eklenir ve Grafana için `/api/health` healthcheck'i tanımlanır.
