# `managers/code/runner.py` — Kabuktan Bağımsız Komut Argüman Kurulumu

- **Kaynak dosya:** `managers/code/runner.py`
- **Not dosyası:** `docs/module-notes/managers/code/runner.py.md`

**Amaç:** Kullanıcı kabuk komutlarını `shell=True` kullanmadan (argv listesi
olarak) güvenli biçimde ayrıştırıp çalıştırmak için yardımcılar; yıkıcı komut
kalıplarını (`rm -rf /`, fork bomb vb.) tespit eder. Alt süreç çağrıları
`core/utils/trusted_subprocess.py` üzerinden geçer.

**Özellikler:**
- `SandboxRunner` (Protocol) — production container shell delegasyonu için
  çağrılabilir sözleşme.
- `requires_container_shell(manager)` — komutun izole container shell'i
  gerektirip gerektirmediğini belirler.
- `build_sanitized_shell_args(...)` — `shlex` tabanlı, shell metakarakter
  enjeksiyonuna kapalı argv listesi kurar.
- `find_destructive_shell_pattern(command)` — bilinen yıkıcı kalıpları
  (regex tabanlı) tespit eder; bulunursa komut reddedilir.
- `run_shell_command(...)` — doğrulanmış argv'yi `run_trusted_command()` ile
  çalıştırır.
