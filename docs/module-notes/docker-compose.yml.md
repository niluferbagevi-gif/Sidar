# docker-compose.yml

- **Kaynak dosya:** `docker-compose.yml`
- **Not dosyası:** `docs/module-notes/docker-compose.yml.md`
- **Amaç:** Servis orkestrasyonu için docker-compose tanımı.
- **Durum:** İncelendi ve `docs/module-notes` altında dokümante edildi.

- **Observability güncellemesi:** Jaeger image'i `latest` yerine `jaegertracing/all-in-one:1.65` olarak pinlenir; Redis/PostgreSQL/cAdvisor exporter servisleri Prometheus tarafından scrape edilecek şekilde compose topolojisine eklenir ve Grafana için `/api/health` healthcheck'i tanımlanır.
