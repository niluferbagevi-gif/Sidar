# `core/config_app.py` — Uygulama Seviyesi Runtime Ayarları

- **Kaynak dosya:** `core/config_app.py`
- **Not dosyası:** `docs/module-notes/core/config_app.py.md`

**Amaç:** `config.py` facade'ının tükettiği uygulama adı/sürüm, debug modu,
multi-agent bayrağı, bellek turu limitleri ve log seviyesi gibi temel runtime
ayarlarını `AppRuntimeSettings` frozen dataclass'ı olarak sağlar.

**Özellikler:**
- `AppRuntimeSettings` — `project_name`, `version` (`sidar_version.PRODUCT_VERSION`'dan),
  `debug_mode`, `enable_multi_agent`, `max_memory_turns`, `memory_summary_keep_last`,
  `cli_fast_mode`, `log_level`, `response_language`.
- `load_app_runtime_settings()` — bu değerleri ortam değişkenlerinden
  (`core/config_env_helpers.py`'deki `get_bool_env`/`get_int_env` ile) okuyup
  dataclass'ı üretir.
