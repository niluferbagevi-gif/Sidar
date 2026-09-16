# `core/doctor/reporting.py` — Doktor Rapor Biçimlendirme/Kalıcılık

- **Kaynak dosya:** `core/doctor/reporting.py`
- **Not dosyası:** `docs/module-notes/core/doctor/reporting.py.md`

**Amaç:** Doktor kontrol sonuçlarından JSON-serializable, şema versiyonlu
birleşik rapor üreten saf yardımcıları barındırır; dosya I/O ve zaman
bağımlılıkları parametre olarak enjekte edilir (test edilebilirlik).

**Özellikler:**
- `build_doctor_report(checks, *, generated_at_unix=None, schema_version=1)`
  — her kontrolü `validate_doctor_check_contract()` ile doğrular; genel durumu
  `"fail" > "warn" > "pass"` önceliğiyle özetler; GPU stres testi gerekip
  gerekmediğini (`run_gpu_stress`) detaylardan türetir.
