# `managers/code/shell_sandbox.py` — CodeManager Shell Sandbox Adaptörü

- **Kaynak dosya:** `managers/code/shell_sandbox.py`
- **Not dosyası:** `docs/module-notes/managers/code/shell_sandbox.py.md`

**Amaç:** `ShellSandboxAdapter` sınıfı, Docker sandbox içinde shell komutu
çalıştırma akışını yönetir — hangi sandbox image'ının kullanılacağını seçer
ve gerçek yürütmeyi `managers/code/test_runner_orchestrator.py`'ye delege
eder.

**Özellikler:**
- `select_shell_sandbox_image()` — komut `uv`/pytest araçları gerektiriyorsa
  (`command_requires_uv_tooling()`) proje test image'ını, aksi halde genel
  REPL image'ını seçer.
- `run_shell_in_sandbox()` — `owner.code_execution_backend` `disabled`/`none`/`off`
  ise fail-closed olarak reddeder (deployment-mode koruması); aksi halde
  Docker'ı başlatıp (`ensure_docker_initialized()`) komutu sandbox içinde
  çalıştırır.
- `build_shell_preflight_command()`/`command_invokes_pytest()` —
  `pytest_parser.py`'deki yardımcı fonksiyonlara ince birer geçiş.
