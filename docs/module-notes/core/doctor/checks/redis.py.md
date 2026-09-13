# `core/doctor/checks/redis.py` — Redis Doktor Kontrolü

- **Kaynak dosya:** `core/doctor/checks/redis.py`
- **Not dosyası:** `docs/module-notes/core/doctor/checks/redis.py.md`

**Amaç:** Redis konfigürasyonunun (canlı broker gerektirmeden) varlığını
raporlayan `check_redis()`'i barındırır. `SIDAR_REDIS_URL`'in gerçek
bağlantıların çözüldüğü birincil değişken olduğunu (`core.config_rate_limit.resolve_redis_url`),
`REDIS_URL`'in ise yalnızca legacy alias olduğunu belgeler — yalnızca
`REDIS_URL`'e bakmak, sadece `SIDAR_REDIS_URL` set edilmiş kurulumlarda
(install_sidar.sh'ın `.env` varsayılanı) yanlış-pozitif "ayarlı değil"
uyarısı üretiyordu; bu modül bu regresyonu düzeltir.

**Özellikler:**
- `check_redis()` — `event_bus_backend == "redis"` iken URL yoksa `"warn"`,
  aksi halde `"pass"` döner; detaylarda `redis_url_set`/`event_bus_backend`/
  `required_for_remote_event_bus` taşır.
