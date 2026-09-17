# `managers/code/linter_runners.py` — Doğrulama ve Lint Yardımcıları

- **Kaynak dosya:** `managers/code/linter_runners.py`
- **Not dosyası:** `docs/module-notes/managers/code/linter_runners.py.md`

**Amaç:** Üretilen dosyalar için best-effort biçimlendirme (ruff) ve
sözdizimi/JSON doğrulama yardımcıları; `core/utils/trusted_subprocess.py`
üzerinden çalıştırılır.

**Özellikler:**
- `post_process_written_file(target)` — yalnızca `.py` dosyalarında, `ruff`
  PATH'te mevcutsa best-effort format uygular.
- `validate_python_syntax(code)` — `ast.parse` ile sözdizimi doğrular,
  `(bool, mesaj)` döner.
- `validate_json(content)` — `json.loads` ile geçerliliği doğrular.
