# `core/doctor/checks/security.py` — Güvenlik/Ortam Profili Doktor Kontrolü

- **Kaynak dosya:** `core/doctor/checks/security.py`
- **Not dosyası:** `docs/module-notes/core/doctor/checks/security.py.md`

**Amaç:** `check_environment_profile()`'ın gerçek gövdesini (ve yalnız onun
kullandığı `_read_env_file_assignments` private helper'ını) barındırır —
`redis.py::check_redis` ile aynı desende, kendi kendine yeten bir
implementasyon (`docs/REFACTOR_PLAN.md`'nin `core/doctor/__init__.py`
maddesinde işaretlenen 9 pass-through fonksiyondan ilk taşınanı).
`core/doctor/__init__.py`'deki `check_environment_profile` artık bu modüle
deferred-import ile delege eden ince bir pass-through'tur (döngüsel
import'tan kaçınmak için fonksiyon-lokal import kullanır). `BASE_DIR`
değeri `import core.doctor as _doctor` + `_doctor.BASE_DIR` ile dinamik
referanslanır — `from core.doctor import BASE_DIR` değeri sabitler ve
`monkeypatch.setattr(doctor, "BASE_DIR", ...)` kullanan testleri bozar.

**Özellikler:**
- `check_environment_profile()` — `SIDAR_ENV` profilinin izole dotenv
  dosyasına sahip olup olmadığını doğrular (`.env.{profile}`/`.env.{profile}.example`
  varlığı, development/dev/local profillerinde `POSTGRES_DB` izolasyonu).
- `_read_env_file_assignments(path)` — bir dotenv dosyasından basit
  `KEY=VALUE` atamalarını (sır açma yapmadan) okur.
