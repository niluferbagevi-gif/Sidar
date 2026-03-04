# managers/system_health.py Teknik Notu

`SystemHealthManager`, CPU/RAM/GPU sağlık ölçümleri ve optimizasyon çağrılarını kapsar.

## Sorumluluklar
- Sistem kaynak raporu üretmek
- GPU belleği optimizasyon yardımcıları
- CPU-only ve GPU modlarında tutarlı çıktı vermek

## Bağlantılar
- Ayar kaynağı: `config.py` (`USE_GPU` ve donanım bilgileri)
- Tüketen: `SidarAgent`, `web_server.py` (status/metrics)

## Not
- Ölçüm çağrıları sıklaştığında sampling/caching stratejileri önem kazanır.