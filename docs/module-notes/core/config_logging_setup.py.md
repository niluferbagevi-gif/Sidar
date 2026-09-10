# `core/config_logging_setup.py` — Geriye Dönük Uyumlu Log Kurulum Sarmalayıcıları

- **Kaynak dosya:** `core/config_logging_setup.py`
- **Not dosyası:** `docs/module-notes/core/config_logging_setup.py.md`

**Amaç:** Gerçek log yapılandırma mantığı `core/logging_config.py`'ye
taşındıktan sonra, `config.py` facade'ının eski import yüzeyini kırmadan
aynı fonksiyonları re-export eden ince bir uyumluluk katmanı.

**Özellikler:**
- `log_first_load_info(logger, first_config_load_logged, message, *args)` —
  ilk config yüklemesinde `INFO`, sonraki reload'larda `DEBUG` seviyesinde
  loglar (başlangıç gürültüsünü tekrar reload'larda bastırır).
- `core.logging_config`'ten `LoggingConfigState`, `configure_noisy_dependency_loggers`,
  `configure_sidar_logging`, `get_sidar_locale`, `localized_log_message`'ı
  re-export eder.
