# `core/config_dotenv.py` — Dotenv Öncelik Zinciri ve Tanılama

- **Kaynak dosya:** `core/config_dotenv.py`
- **Not dosyası:** `docs/module-notes/core/config_dotenv.py.md`

**Amaç:** `.env` → `.env.advanced` → ortam → `DOTENV_FILE` → `SIDAR_KEYS_FILE`
öncelik zincirini (`DotenvReloadPlan`) doğrular ve `reload_environment()`
sırasında hangi anahtarın hangi katmandan geldiğini (değer loglanmadan)
izlemeye yarayan yardımcıları barındırır.

**Özellikler:**
- `DotenvReloadPlan` (pydantic, frozen) — profile/base/advanced/explicit/secret
  dosya yolları ve sabit 5 elemanlı `labels` demeti; `profile` path traversal
  (`/`, `\`, `..`) karakterlerine karşı `field_validator` ile doğrulanır.
- `build_dotenv_reload_plan(...)` — facade global'larına dokunmadan planı kurar
  ve `validate_secret_overlay(...)` callback'iyle `SIDAR_KEYS_FILE`'ı doğrular.
- `parse_dotenv_source_values(path)` — basit `KEY=VALUE` satırlarını (tırnak/
  `export` desteğiyle) ayrıştırır; I/O hatasında sessizce boş sözlük döner.
- `record_dotenv_key_sources(...)` — hangi anahtarın hangi dosyadan/override
  bayrağıyla geldiğini `key_sources` sözlüğüne yazar; değerleri değil kaynağını
  tutar (secret sızıntısını önler).
- `reset_dotenv_managed_environment(...)` — reload öncesi önceden yönetilen
  anahtarları orijinal değerlerine geri sarar.
