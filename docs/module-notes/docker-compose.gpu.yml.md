# docker-compose.gpu.yml

- **Kaynak dosya:** `docker-compose.gpu.yml`
- **Not dosyası:** `docs/module-notes/docker-compose.gpu.yml.md`
- **Amaç:** GPU (NVIDIA) profili servisleri — `ollama-gpu`, `sidar-gpu` (CLI),
  `sidar-web-gpu`. `docker-compose.yml` (core) ile `-f` birleştirilir;
  tek başına yeterli değildir (postgres/redis/docker-socket-proxy gibi
  paylaşılan bağımlılıklar core dosyada kalır). Bkz.
  `docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile gpu up`.
- **Bölünme (P3):** `docker-compose.yml`'in 690+ satırlık tek dosya
  yapısından okunabilirlik için ayrıldı (bkz. `docker-compose.yml.md`).
  `docker-compose.production.yml`'nin `ollama-gpu`/`sidar-web-gpu`
  override-only blokları (image/build yok) bu dosyanın temel tanımlarına
  bağımlıdır — production overlay'i her zaman bu dosyayla birlikte
  kullanılmalıdır, `--profile cpu` çalışırken bile (bkz.
  `docker-compose.production.yml`'nin başlık yorumu).
- **Durum:** İncelendi ve `docs/module-notes` altında dokümante edildi.
