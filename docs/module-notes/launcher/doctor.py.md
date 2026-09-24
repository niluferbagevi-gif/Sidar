# `launcher/doctor.py` — Launcher Doktor Yardımcıları (Saf Sunum Katmanı)

- **Kaynak dosya:** `launcher/doctor.py`
- **Not dosyası:** `docs/module-notes/launcher/doctor.py.md`

**Amaç:** `main.py`'nin Doctor auto-fix akışı: komut listesi çözümü, fallback
seçimi, durum biçimlendirme, kayıp-env-anahtarı diff'i ve auto-fix komut/döngü/
yeniden doğrulama mantığı. Durum (`main._LAST_DOCTOR_AUTO_FIX_REVALIDATION`,
`main._DOCTOR_APPLY_ALL_APPROVED`) testler doğrudan eriştiği için `main.py`'de
kalır; `main`'deki aynı adlı sarmalayıcılar bu durumu yönetir ve `confirm`,
komut çalıştırıcı, env yeniden yükleyici gibi işbirlikçileri çağrı anında
parametre olarak geçirir.

**Özellikler:**
- `doctor_status_icon(status)`, `print_doctor_check_summary(check)` — terminal
  sunumu (ANSI renkleri `main.py`'nin CYAN/GREEN/YELLOW/RED/RESET
  sabitleriyle birebir aynı, bağımsız tutulur — döngüsel import önlemek için).
- `doctor_auto_fix_commands(details)`, `doctor_auto_fix_fallback_commands(details)`,
  `select_doctor_auto_fix_commands(check_name, commands)` — bir kontrolün
  detaylarından çalıştırılabilir auto-fix komut listesini çözer.
- `doctor_auto_fix_lost_env_keys(...)` — auto-fix sonrası kaybolan env
  anahtarlarının diff'ini hesaplar.
- `run_doctor_auto_fix_command(auto_fix, *, cwd, env, format_cmd, logger_obj)` —
  komutu `core.doctor.validate_auto_fix_command` ile doğrular, shell kullanmadan çalıştırır.
- `run_doctor_auto_fix(check, check_func, *, apply_all_mode, confirm, run_command, revalidate, max_retries, stdin_isatty)`
  — onay, deneme limiti, fallback komutları ve her başarılı adımdan sonra yeniden doğrulama.
- `revalidate_doctor_check_after_auto_fix(..., reload_environment, handled_exceptions, logger_obj)`
  — env'i yeniden yükleyip kontrolü tekrar çalıştırır; sonucu döndürür (çağıran cache'ler).
