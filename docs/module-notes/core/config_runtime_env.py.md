# `core/config_runtime_env.py` — Reload-Time Ortam Override Akışı

- **Kaynak dosya:** `core/config_runtime_env.py`
- **Not dosyası:** `docs/module-notes/core/config_runtime_env.py.md`

**Amaç:** `Config.reload_environment()` çağrıldığında, süreç içinde zaten
yüklenmiş `Config` sınıf attribute'larını güncel ortam değişkenleriyle
(dependency-injected normalizer/URL çözücülerle) günceller.

**Özellikler:**
- `safe_choice_for_reload(value, default, allowed)` — serbest metin girdisini
  izin verilen sabit kümeye normalize eder, aksi halde default'a döner.
- `apply_runtime_env_overrides(config_cls, *, base_dir, get_int_env,
  get_database_url, get_container_database_url, normalize_ai_provider)` —
  `AI_PROVIDER`, `ACCESS_LEVEL` gibi alanları `config_cls` üzerinde yerinde
  günceller; DB URL çözümü ve provider normalizasyonu çağırana enjekte edilir
  (test edilebilirlik, facade'a geri döngüsel import olmadan).
