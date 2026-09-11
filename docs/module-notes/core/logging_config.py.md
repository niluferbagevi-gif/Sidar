# `core/logging_config.py` — Logging Yapılandırma Yardımcıları

- **Kaynak dosya:** `core/logging_config.py`
- **Not dosyası:** `docs/module-notes/core/logging_config.py.md`

**Amaç:** Sidar runtime'ının log kurulumu ve yerelleştirilmiş log
mesajlarını barındırır; `core/config_logging_setup.py`'nin canonical
implementasyonu (o dosya yalnızca geriye dönük uyumlu re-export'tur).

**Özellikler:**
- `LOG_MESSAGES` — `tr`/`en` yerelleştirilmiş sabit log mesajları sözlüğü
  (örn. log dosyasına yazılamama, config reload bastırma).
- `LoggingConfigState` (dataclass) — logging kurulumunun mevcut durumunu
  taşır.
- `get_sidar_locale()`, `localized_log_message(key)` — aktif dile göre
  mesaj çözer.
- `configure_noisy_dependency_loggers(...)` — gürültülü üçüncü taraf
  logger'ların (`httpx`, `urllib3` vb.) seviyesini bastırır.
- `_log_format(log_level_str)`, `configure_sidar_logging(...)` — log
  formatını ve handler'larını (konsol + best-effort dosya) kurar.
