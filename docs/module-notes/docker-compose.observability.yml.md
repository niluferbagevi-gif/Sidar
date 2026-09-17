# docker-compose.observability.yml

- **Kaynak dosya:** `docker-compose.observability.yml`
- **Not dosyası:** `docs/module-notes/docker-compose.observability.yml.md`
- **Amaç:** Observability profili servisleri — `jaeger` (tracing),
  `redis-exporter`, `postgres-exporter`, `cadvisor`, `prometheus-token-init`,
  `prometheus`, `grafana`. `docker-compose.yml` (core) ile `-f`
  birleştirilir; tek başına yeterli değildir (redis/postgres gibi izlenen
  servisler core dosyada kalır). Bkz.
  `docker compose -f docker-compose.yml -f docker-compose.observability.yml --profile cpu --profile observability up`.
- **Bölünme (P3):** `docker-compose.yml`'in 690+ satırlık tek dosya
  yapısından okunabilirlik için ayrıldı (bkz. `docker-compose.yml.md`).
  `sidar-web`/`sidar-web-gpu`'nun jaeger'a olan soft (`required: false`)
  `depends_on` bağımlılığı bu bölünmede kasıtlı olarak kaldırıldı (cross-file
  bir servise referans vermek, bu dosya `-f` ile eklenmediğinde "depends on
  undefined service" hatası verirdi) — bu yalnızca başlangıç sırası için bir
  optimizasyondu, `ENABLE_TRACING` zaten varsayılan `false`'tur ve jaeger
  ulaşılamazsa bağlantı hatası gracefully ele alınır.
- **Durum:** İncelendi ve `docs/module-notes` altında dokümante edildi.
