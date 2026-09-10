# `core/doctor/launcher_preflight.py` — Launcher Doktor Ön Kontrol Orkestrasyonu

- **Kaynak dosya:** `core/doctor/launcher_preflight.py`
- **Not dosyası:** `docs/module-notes/core/doctor/launcher_preflight.py.md`

**Amaç:** CLI launcher'ın kısa hazırlık akışını canonical `core.doctor`
kontrolleriyle senkron tutar; launcher UI renkleri/onay istemleri/ortam
reload hook'larının sahipliğini launcher'da bırakırken, kontrollerin
sırasını, atlama (skip) politikasını ve paralel çalıştırma planını burada
merkezileştirir.

**Özellikler:**
- `LauncherDoctorPreflightHooks` (frozen dataclass) — launcher'ın sağladığı
  `confirm`, `print_check_summary`, `doctor_auto_fix_commands`,
  `invoke_auto_fix`, `clear_revalidation_cache` callback'leri; dependency
  injection ile `core.doctor.launcher_preflight`'ın `main.py`'ye geri
  bağımlı olmasını önler.
- `concurrent.futures` ile kontrolleri paralel çalıştırır.
