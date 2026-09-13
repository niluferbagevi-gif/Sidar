# `managers/code/platform.py` — Platforma Özel Çalıştırılabilir Keşfi

- **Kaynak dosya:** `managers/code/platform.py`
- **Not dosyası:** `docs/module-notes/managers/code/platform.py.md`

**Amaç:** LSP dil sunucusu ikili dosyalarını `PATH` dışında (venv/conda/home
gibi platforma özgü konumlarda) deterministik biçimde aramak için aday yol
listesi üretir; tüm bağımlılıklar (`os_name`, `sys_prefix`, `home_dir`)
parametre olarak enjekte edilir (test edilebilirlik).

**Özellikler:**
- `candidate_lsp_executable_paths(binary, *, base_dir, python_virtual_env="",
  python_conda_prefix="", os_name=os.name, sys_prefix=sys.prefix,
  home_dir=None)` — aday `Path` listesi döndürür.
