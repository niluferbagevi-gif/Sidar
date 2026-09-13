# `core/config_hardware.py` — Donanım/VRAM Politika Yardımcıları

- **Kaynak dosya:** `core/config_hardware.py`
- **Not dosyası:** `docs/module-notes/core/config_hardware.py.md`

**Amaç:** `core/config_gpu_detect.py`'deki `HardwareInfo`'yu kullanarak GPU
runtime talebinin (env/Compose profili üzerinden) açıkça istenip
istenmediğini belirler ve VRAM bütçe/normalizasyon politikasını uygular.

**Özellikler:**
- `_gpu_runtime_requested(environ, get_bool_env=...)` — `USE_GPU`/`REQUIRE_GPU`
  bayrakları veya `COMPOSE_PROFILES` içinde GPU profili olup olmadığını saf
  fonksiyon olarak (test edilebilir, dependency-injected `get_bool_env` ile)
  değerlendirir.
