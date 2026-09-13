# `managers/code/pytest_parser.py` — Kabuk Komutu Sınıflandırma Yardımcıları

- **Kaynak dosya:** `managers/code/pytest_parser.py`
- **Not dosyası:** `docs/module-notes/managers/code/pytest_parser.py.md`

**Amaç:** `CodeManager`'ın pytest preflight akışında kullanılan, bir kabuk
komutunun pytest'e ait argümanlarını ayıklayan ve `uv run pytest`/
`python -m pytest` gibi kalıpları tanıyan saf ayrıştırma yardımcıları.

**Özellikler:**
- `extract_pytest_args(command)` — `shlex.split` ile ayrıştırır, `uv run` /
  `python -m` önekli komutlardan yalnızca pytest'e ait argümanları döndürür.
- `command_requires_uv_tooling(command)`, `command_invokes_pytest(command)` —
  komutun `uv`/pytest gerektirip gerektirmediğini sınıflandırır.
