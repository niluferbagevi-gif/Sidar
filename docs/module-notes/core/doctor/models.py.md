# `core/doctor/models.py` — Doktor Sonuç Modelleri ve Güvenlik Regex'leri

- **Kaynak dosya:** `core/doctor/models.py`
- **Not dosyası:** `docs/module-notes/core/doctor/models.py.md`

**Amaç:** Tüm doktor kontrollerinin ortak sonuç sözleşmesini
(`DoctorCheckContract`) ve auto-fix komutlarının güvenli olup olmadığını
doğrulayan saf (yan etkisiz) regex/validasyon yardımcılarını barındırır.

**Özellikler:**
- `DoctorCheckContract` (`runtime_checkable` Protocol) — `name`/`status`/
  `message` alanlarını zorunlu kılar; `status` yalnızca `{"pass","warn","fail"}`.
- `_SENSITIVE_ASSIGNMENT_RE`, `_URL_PASSWORD_RE` — log/mesaj metinlerinde
  `password=`/`secret=`/URL içi şifre gibi hassas değerleri tespit etmek için
  kullanılan regex'ler (maskeleme, `core/doctor/__init__.py`'nin `_redact_*`
  fonksiyonlarıyla birlikte çalışır).
- `_AUTO_FIX_ARG_RE`, `_AUTO_FIX_MODULE_RE`, `_ALLOWED_DOCKER_COMPOSE_AUTO_FIXES`
  — `validate_auto_fix_command()`'ın dayandığı allowlist: yalnızca izin
  verilen karakter kümesindeki argümanlara ve `scripts`/`core.doctor` modül
  adlarına sahip auto-fix komutları kabul edilir (keyfi komut enjeksiyonuna
  karşı fail-closed doğrulama).
- `validate_doctor_check_contract(check)` — bir nesnenin `DoctorCheckContract`'a
  uygunluğunu çalışma zamanında doğrular.
