# `core/config_dirs.py` — Dizin ve Log Dosyası Yardımcıları

- **Kaynak dosya:** `core/config_dirs.py`
- **Not dosyası:** `docs/module-notes/core/config_dirs.py.md`

**Amaç:** Repo kök dizinini config dosya yolundan çözer, gerekli runtime
dizinlerini oluşturur ve log dosyası izin sorunlarını best-effort onarır.

**Özellikler:**
- `resolve_base_dir(config_file)` — `config.py`'nin bulunduğu dizini repo kökü
  olarak çözer.
- `repair_log_file_permissions(log_file)` — log dosyası yazılabilir değilse
  `os.chown`/`chmod` ile (varsa) düzeltmeyi dener; izin hatalarını yutar.
- `initialize_directories(required_dirs, logger)` — gerekli dizinleri
  `mkdir(parents=True, exist_ok=True)` ile oluşturur, başarısız olanları loglar.
