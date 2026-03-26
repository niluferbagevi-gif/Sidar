# requirements-dev.txt

- **Kaynak dosya:** `requirements-dev.txt`
- **Not dosyası:** `docs/module-notes/requirements-dev.txt.md`
- **Amaç:** `pyproject.toml` içindeki `dev` extra grubunun `uv` ile derlenmiş, sürüm sabitlenmiş kilit dosyasıdır.
- **Üretim komutu:** `uv pip compile pyproject.toml --extra dev -o requirements-dev.txt`
- **Not:** CI/CD test, lint ve tip kontrol adımlarında kullanılmak üzere tutulur; elle düzenlenmez.
- **Durum:** UV mimarisiyle senkronize edildi.
