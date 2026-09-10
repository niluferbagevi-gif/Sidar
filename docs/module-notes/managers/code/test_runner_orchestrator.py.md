# `managers/code/test_runner_orchestrator.py` — Pytest Sandbox Orkestrasyonu

- **Kaynak dosya:** `managers/code/test_runner_orchestrator.py`
- **Not dosyası:** `docs/module-notes/managers/code/test_runner_orchestrator.py.md`

**Amaç:** `CodeManager`'ın sandbox içinde pytest/shell komutu çalıştırma ve
çıktısını yapılandırılmış sonuca (geçen/kalan test sayısı, hata özetleri)
dönüştürme mantığını barındırır; `managers/code/docker.py`'deki image
sanitizasyonunu ve `core/utils/trusted_subprocess.py`'yi kullanır.

**Özellikler:**
- `build_pytest_preflight_command(manager, command)`,
  `build_shell_preflight_command(manager, command)` — sandbox içinde pytest'i
  image/proje venv/`uv`'den bulan preflight komutları kurar.
- `run_shell_in_sandbox(...)` — hazırlanan komutu izole sandbox'ta çalıştırır.
- `analyze_pytest_output(output)` — pytest çıktısını yapılandırılmış özet
  sözlüğüne ayrıştırır.
- `normalize_pytest_command(command)`, `run_pytest_and_collect(...)` — komut
  normalizasyonu ve uçtan uca çalıştırma/sonuç toplama.
