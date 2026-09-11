# `core/config_env_helpers.py` — Ortam Değişkeni Ayrıştırma Yardımcıları

- **Kaynak dosya:** `core/config_env_helpers.py`
- **Not dosyası:** `docs/module-notes/core/config_env_helpers.py.md`

**Amaç:** Tüm `core/config_*.py` domain modüllerinin ortak kullandığı, tip
güvenli ortam değişkeni okuma katmanı; sessizce hatalı değer kabul etmek yerine
geçersiz bool girdilerinde `ValueError` fırlatır.

**Özellikler:**
- `get_bool_env`/`get_external_bool_env` — yalnızca `"true"`/`"false"` (case-
  insensitive) kabul eder, başka değerde hata fırlatır (sessiz yanlış-pozitif
  yerine fail-fast).
- `get_int_env`, `get_float_env`, `get_list_env` (ayraçlı liste), `get_web_scrape_max_chars`.
- `get_prefixed_env`/`get_optional_prefixed_env`/`get_int_prefixed_env`/
  `get_float_prefixed_env`/`get_bool_prefixed_env` — yeni `SIDAR_*` önekli
  anahtar ile legacy anahtar arasında geriye dönük uyumlu okuma (önce yeni
  anahtar, yoksa legacy anahtar, o da yoksa default).
