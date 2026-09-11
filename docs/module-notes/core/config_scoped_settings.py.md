# `core/config_scoped_settings.py` — Dotenv-Scoped Settings Subclass Üretici

- **Kaynak dosya:** `core/config_scoped_settings.py`
- **Not dosyası:** `docs/module-notes/core/config_scoped_settings.py.md`

**Amaç:** `config_llm.py` ve `config_quality.py`'nin ikisinin de ihtiyaç
duyduğu, belirli bir dotenv dosyasından (facade'ın çözdüğü `ENV_PATH`/
`.env.advanced` zinciri) okuyan `pydantic-settings` alt sınıfı üretme
mantığını tek yere indirir. `pydantic-settings`'in özel `_env_file=...` init
kwarg'ı `mypy --strict` altında untyped-call uyarısı verdiği için, her çağrı
noktasında dinamik kwarg yerine `type(...)` ile throwaway bir `model_config`
alt sınıfı kurulur — bir kod incelemesinde iki dosyada birebir kopyalanmış
~15 satırlık blok bulunup buraya taşındı (bkz. `config.py.md`).

**Özellikler:**
- `build_scoped_settings_type(...)` — verilen `BaseSettings` alt sınıfını,
  belirtilen dotenv dosyasına scoped `SettingsConfigDict` ile saran yeni bir
  tip döndürür; çağıranlar tamamen tipli, dinamik kwarg'sız `SettingsClass()`
  kullanabilir.
- Doğrulama: `tests/unit/root/test_config.py::test_load_llm_settings_reads_scoped_dotenv_without_dynamic_init_kwargs`.
