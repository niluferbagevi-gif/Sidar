# `core/config_summary.py` — Sistem Bilgisi ve Yapılandırma Özeti

- **Kaynak dosya:** `core/config_summary.py`
- **Not dosyası:** `docs/module-notes/core/config_summary.py.md`

**Amaç:** `Config.get_system_info()` ve `Config.print_config_summary()` gövdelerini
`config.py` facade'ından ayırır. Her iki fonksiyon da yalnız class attribute okur;
donanım bilgisinin lazy yüklenmesi facade'da kalır.

**Özellikler:**
- `build_system_info(config_cls)` — proje/sürüm, sağlayıcı, erişim seviyesi, GPU/CPU,
  web portları, HF önbellek bayrakları, rate-limit, tracing ve semantic cache
  değerlerini sözlük olarak döndürür. `REDIS_URL` gibi bağlantı adresleri ve gizli
  anahtarlar bilinçli olarak dışarıda bırakılır.
- `print_config_summary(config_cls, *, base_dir)` — konsola yapılandırma özet
  banner'ını yazar; sağlayıcıya göre ilgili model adını ve `RAG_DIR`'i `base_dir`'e
  göreli gösterir.

**Testler:** `tests/unit/root/test_config.py` (facade üzerinden).
