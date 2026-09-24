# `launcher/env_reload.py` — Doctor Auto-Fix Sonrası Env Yeniden Yükleme

- **Kaynak dosya:** `launcher/env_reload.py`
- **Not dosyası:** `docs/module-notes/launcher/env_reload.py.md`

**Amaç:** Doctor auto-fix alt süreci dotenv dosyalarını değiştirdikten sonra ilgili
anahtarları launcher sürecinin `os.environ`'una geri uygular. Değerler loglanmaz.
`main.py`'den taşındı; `cfg`'yi yeniden atayan `_reload_config_environment`
testler `main.cfg`'yi patch ettiği için `main.py`'de kaldı.

**Özellikler:**
- `parse_env_source_file(path)` — basit `KEY=value` / `export KEY=value`
  satırlarını, tırnakları soyarak okur; geçersiz satırları atlar.
- `reload_env_source_definitions(details)` — Doctor'ın `env_source_definitions`
  kaynaklarındaki anahtarları uygular.
- `DATABASE_AUTO_FIX_ENV_KEYS`, `reload_database_env_from_dotenv_chain(config_module, *, logger_obj)`
  — yüklenen dotenv zincirinden veritabanı anahtarlarını override sırasına göre
  uygular ve `Config.DATABASE_URL`/`CONTAINER_DATABASE_URL`'i tazeler.
