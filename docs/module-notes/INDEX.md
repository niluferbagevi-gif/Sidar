# Module Notes Index

Bu dizin proje dosyalarının dokümantasyon notlarını içerir.

> Bu index elle senkron tutulmaz: `scripts/ci/check_module_notes_inventory.py`
> (CI'da `Base quality gates` job'ının parçası) her PR'da (1) buradaki her kaynak
> dosyanın ve not dosyasının gerçekten var olduğunu, (2) `docs/module-notes/`
> altındaki hiçbir not dosyasının bu index'te referanssız (orphan) kalmadığını
> doğrular, (3) dokümante edilmemiş production modül sayısının
> `docs/module-notes/inventory-debt-baseline.json`'daki ratchet tavanını
> aşmadığını kontrol eder. Sayılar aşağıda elle güncellenir; script bunları
> `--verify-counts` ile de doğrulayabilir.
> Baseline tarihli 150 → 100 → 50 → 0 azaltma hedefleri taşır; yeni bir note
> eklendiğinde CI daha düşük gerçek sayıyı görür ve baseline aynı PR'da
> `--update` ile aşağı çekilmeden geçmez. `--update` borcu yükseltemez.

- **Toplam kaynak dosya (tests dahil):** 366
- **Tests dışı dosya sayısı (ayrı not üretilen):** 67
- **Tests dosya sayısı (tek notta özetlenen, `tests/**/*.py`):** 299

## Not dosyaları
- `.env.example` → `docs/module-notes/env.example.md`
- `.github/workflows/ci.yml` → `docs/module-notes/.github/workflows/ci.yml.md`
- `.github/workflows/migration-cutover-checks.yml` → `docs/module-notes/.github/workflows/migration-cutover-checks.yml.md`
- `.gitignore` → `docs/module-notes/gitignore.md`
- `CHANGELOG.md` → `docs/module-notes/CHANGELOG.md.md`
- `docs/CLAUDE.md` → `docs/module-notes/CLAUDE.md.md`
- `Dockerfile` → `docs/module-notes/Dockerfile.md`
- `docs/PROJE_RAPORU.md` → `docs/module-notes/PROJE_RAPORU.md.md`
- `README.md` → `docs/module-notes/README.md.md`
- `docs/RFC-MultiAgent.md` → `docs/module-notes/RFC-MultiAgent.md.md`
- `docs/SIDAR.md` → `docs/module-notes/SIDAR.md.md`
- `agent/__init__.py` → `docs/module-notes/agent/__init__.py.md`
- `agent/auto_handle.py` → `docs/module-notes/agent/auto_handle.py.md`
- `agent/base_agent.py` → `docs/module-notes/agent/base_agent.py.md`
- `agent/core/__init__.py` → `docs/module-notes/agent/core/__init__.py.md`
- `agent/core/contracts.py` → `docs/module-notes/agent/core/contracts.py.md`
- `agent/core/event_stream.py` → `docs/module-notes/agent/core/event_stream.py.md`
- `agent/core/memory_hub.py` → `docs/module-notes/agent/core/memory_hub.py.md`
- `agent/core/registry.py` → `docs/module-notes/agent/core/registry.py.md`
- `agent/core/supervisor.py` → `docs/module-notes/agent/core/supervisor.py.md`
- `agent/definitions.py` → `docs/module-notes/agent/definitions.py.md`
- `agent/roles/__init__.py` → `docs/module-notes/agent/roles/__init__.py.md`
- `agent/roles/coder_agent.py` → `docs/module-notes/agent/roles/coder_agent.py.md`
- `agent/roles/researcher_agent.py` → `docs/module-notes/agent/roles/researcher_agent.py.md`
- `agent/roles/reviewer_agent.py` → `docs/module-notes/agent/roles/reviewer_agent.py.md`
- `agent/registry.py` → `docs/module-notes/agent/registry.py.md`
- `agent/sidar_agent.py` → `docs/module-notes/agent/sidar_agent.py.md`
- `agent/tooling.py` → `docs/module-notes/agent/tooling.py.md`
- `alembic.ini` → `docs/module-notes/alembic.ini.md`
- `cli.py` → `docs/module-notes/cli.py.md`
- `config.py` → `docs/module-notes/config.py.md`
- `core/__init__.py` → `docs/module-notes/core/__init__.py.md`
- `core/db/` → `docs/module-notes/core/db.py.md`
- `core/llm_client.py` → `docs/module-notes/core/llm_client.py.md`
- `core/llm_metrics.py` → `docs/module-notes/core/llm_metrics.py.md`
- `core/memory.py` → `docs/module-notes/core/memory.py.md`
- `core/rag/` → `docs/module-notes/core/rag.py.md`
- `data/.gitkeep` → `docs/module-notes/data/gitkeep.md`
- `docker-compose.yml` → `docs/module-notes/docker-compose.yml.md`
- `docker_setup/grafana/dashboards/sidar-llm-overview.json` → `docs/module-notes/docker_setup/grafana/dashboards/sidar-llm-overview.json.md`
- `docker_setup/grafana/provisioning/dashboards/dashboards.yml` → `docs/module-notes/docker_setup/grafana/provisioning/dashboards/dashboards.yml.md`
- `docker_setup/grafana/provisioning/datasources/prometheus.yml` → `docs/module-notes/docker_setup/grafana/provisioning/datasources/prometheus.yml.md`
- `docker_setup/prometheus/prometheus.yml` → `docs/module-notes/docker_setup/prometheus/prometheus.yml.md`
- `github_upload.py` → `docs/module-notes/github_upload.py.md`
- `gui_launcher.py` → `docs/module-notes/gui_launcher.py.md`
- `install_sidar.sh` → `docs/module-notes/install_sidar.sh.md`
- `main.py` → `docs/module-notes/main.py.md`
- `managers/__init__.py` → `docs/module-notes/managers/__init__.py.md`
- `managers/code_manager.py` → `docs/module-notes/managers/code_manager.py.md`
- `managers/github_manager.py` → `docs/module-notes/managers/github_manager.py.md`
- `managers/package_info.py` → `docs/module-notes/managers/package_info.py.md`
- `managers/security.py` → `docs/module-notes/managers/security.py.md`
- `managers/system_health.py` → `docs/module-notes/managers/system_health.py.md`
- `managers/todo_manager.py` → `docs/module-notes/managers/todo_manager.py.md`
- `managers/web_search.py` → `docs/module-notes/managers/web_search.py.md`
- `migrations/env.py` → `docs/module-notes/migrations/env.py.md`
- `migrations/script.py.mako` → `docs/module-notes/migrations/script.py.mako.md`
- `migrations/versions/0001_baseline_schema.py` → `docs/module-notes/migrations/versions/0001_baseline_schema.py.md`
- `pyproject.toml` → `docs/module-notes/pyproject.toml.md`
- `run_tests.sh` → `docs/module-notes/run_tests.sh.md`
- `runbooks/production-cutover-playbook.md` → `docs/module-notes/runbooks/production-cutover-playbook.md.md`
- `scripts/audit_metrics.sh` → `docs/module-notes/scripts/audit_metrics.sh.md`
- `scripts/check_empty_test_artifacts.sh` → `docs/module-notes/scripts/check_empty_test_artifacts.sh.md`
- `scripts/collect_repo_metrics.sh` → `docs/module-notes/scripts/collect_repo_metrics.sh.md`
- `scripts/install_host_sandbox.sh` → `docs/module-notes/scripts/install_host_sandbox.sh.md`
- `scripts/load_test_db_pool.py` → `docs/module-notes/scripts/load_test_db_pool.py.md`
- `scripts/migrate_sqlite_to_pg.py` → `docs/module-notes/scripts/migrate_sqlite_to_pg.py.md`
- `web_server.py` → `docs/module-notes/web_server.py.md`
- `tests/*` → `docs/module-notes/tests.md`

## Ek notlar (tekil kaynak dosyasına değil, bir konuya/mimari alana bağlı)

Bu notlar `Kaynak dosya` → `Not dosyası` eşlemesi taşımaz; birden fazla dosyayı
kapsayan mimari/operasyon konularını belgeler. `check_module_notes_inventory.py`
bu notları da index'te referanslı sayar, ama yukarıdaki kaynak-dosya
sözleşmelerini onlara uygulamaz.

- `docs/module-notes/modularization.md` — Büyük facade/monolith dosyaların
  (`core/rag/` dahil) kademeli parçalanma haritası.
- `docs/module-notes/install_sidar_modularization.md` — `install_sidar.sh` ve
  `scripts/install_modules/*.sh` arasındaki modüler geliştirme/bundle akışı.
