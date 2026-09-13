# `managers/code/docker.py` — Docker Sandbox Yardımcıları

- **Kaynak dosya:** `managers/code/docker.py`
- **Not dosyası:** `docs/module-notes/managers/code/docker.py.md`

**Amaç:** `CodeManager` facade'ından çıkarılan Docker sandbox limit/parametre
sanitizasyonu ve CLI komut kurma yardımcıları; `managers/code/docker_lifecycle.py`
ve `test_runner_orchestrator.py` tarafından tüketilir.

**Özellikler:**
- `DockerSandboxOwner` (Protocol) — sandbox sahibinin (CodeManager) beklenen
  arayüzü.
- `sanitize_docker_token(...)`, `sanitize_docker_network(value)`,
  `sanitize_docker_image(value)` — kullanıcı/config kökenli değerleri
  `DOCKER_MEMORY_RE`/`DOCKER_CPUS_RE`/`DOCKER_NETWORK_ALLOWED`/`DOCKER_IMAGE_RE`
  allowlist'lerine karşı doğrular (komut enjeksiyonuna karşı fail-closed).
- `resolve_sandbox_limits(...)` — CPU/bellek/network limitlerini config'ten
  çözer.
- `build_docker_cli_command(code, limits, *, image)`,
  `execute_code_with_docker_cli(...)` — doğrulanmış parametrelerle `docker run`
  argv'sini kurar ve çalıştırır.
- `PROJECT_TEST_IMAGE_CANDIDATES`, `LEGACY_PROJECT_IMAGE_PREFIXES` — test/CI
  sandbox image adaylarının canonical listesi.
