# `core/config_runtime_paths.py` — Runtime Dizin Yolu Çözümü

- **Kaynak dosya:** `core/config_runtime_paths.py`
- **Not dosyası:** `docs/module-notes/core/config_runtime_paths.py.md`

**Amaç:** Repo kök dizininden `temp`/`logs`/`data`/`rag` gibi runtime alt
dizinlerinin yollarını türetip `RuntimePathSettings` olarak sağlar;
`core/config_dirs.py`'nin `initialize_directories()`'ine beslenen
`required_dirs` listesinin kaynağıdır.

**Özellikler:**
- `RuntimePathSettings` (frozen dataclass) — `base_dir`, `temp_dir`,
  `logs_dir`, `data_dir`, `memory_file`, `required_dirs`, `rag_dir`.
- `_resolve_base_relative_path(base_dir, raw_path)` — göreli yolu
  `base_dir`'e göre çözer; mutlak yol verilirse olduğu gibi kullanır.
