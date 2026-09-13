# docker-compose.yml

- **Kaynak dosya:** `docker-compose.yml`
- **Not dosyası:** `docs/module-notes/docker-compose.yml.md`
- **Amaç:** Core stack servis orkestrasyonu — `redis`, `postgres`, `ollama`
  (cpu profili), `sidar-migrate`, `docker-socket-proxy`, `sidar-ai`
  (CLI, cpu), `sidar-web` (cpu). Ayrıca tüm named volume tanımlarını
  (`redis_data`, `postgres_data`, `ollama_data`, `sidar_data_prod`,
  `sidar_logs_prod`, `sidar_temp_prod`, `prometheus_secrets`) merkezi olarak
  taşır — `-f` ile birleştirilen `docker-compose.gpu.yml`/
  `docker-compose.observability.yml`'deki servisler bu volume'leri referans
  eder, ama tanımları burada kalır (compose çok-dosya `volumes:` birleşimi
  buna izin verir).
- **Bölünme (P3):** Eskiden 20 servisi tek dosyada taşıyordu (690+ satır);
  okunabilirlik için GPU profili servisleri `docker-compose.gpu.yml`'e,
  observability profili servisleri `docker-compose.observability.yml`'e
  taşındı — dosyanın kendi başlık yorumuna bakın. Üç dosya da
  `docker-compose.production.yml`'nin zaten kullandığı `-f` çok-dosya
  birleştirme deseniyle bir araya gelir.
- **Durum:** İncelendi ve `docs/module-notes` altında dokümante edildi.
