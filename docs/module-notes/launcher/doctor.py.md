# `launcher/doctor.py` — Launcher Doktor Yardımcıları (Saf Sunum Katmanı)

- **Kaynak dosya:** `launcher/doctor.py`
- **Not dosyası:** `docs/module-notes/launcher/doctor.py.md`

**Amaç:** `main.py`'nin Doctor auto-fix akışından çıkarılan, yalnızca
durumsuz (stateless) parçalar: komut listesi çözümü, fallback seçimi, durum
biçimlendirme, kayıp-env-anahtarı diff'i. Durumlu orkestrasyon (testlerin
doğrudan attribute-assignment ile poke ettiği
`main._LAST_DOCTOR_AUTO_FIX_REVALIDATION`, `main._DOCTOR_APPLY_ALL_APPROVED`
gibi modül-seviyesi global'leri mutasyona uğratan `_run_doctor_auto_fix`,
revalidation cache, interactive `confirm` wizard'ı) bilinçli olarak
`main.py`'de bırakılmıştır — bu state'i taşımak ya testlerin doğrudan
attribute erişimini kırar ya da parametre olarak thread etmeyi gerektiren
ayrı, daha büyük bir tasarım değişikliği olurdu.

**Özellikler:**
- `doctor_status_icon(status)`, `print_doctor_check_summary(check)` — terminal
  sunumu (ANSI renkleri `main.py`'nin CYAN/GREEN/YELLOW/RED/RESET
  sabitleriyle birebir aynı, bağımsız tutulur — döngüsel import önlemek için).
- `doctor_auto_fix_commands(details)`, `doctor_auto_fix_fallback_commands(details)`,
  `select_doctor_auto_fix_commands(check_name, commands)` — bir kontrolün
  detaylarından çalıştırılabilir auto-fix komut listesini çözer.
- `doctor_auto_fix_lost_env_keys(...)` — auto-fix sonrası kaybolan env
  anahtarlarının diff'ini hesaplar.
