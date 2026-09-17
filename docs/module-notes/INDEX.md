# Module Notes Index

Bu dizin proje dosyalarının dokümantasyon notlarını içerir.

> Bu index elle senkron tutulmaz: `scripts/ci/check_module_notes_inventory.py`
> (CI'da `Base quality gates` job'ının parçası) her PR'da (1) buradaki her kaynak
> dosyanın ve not dosyasının gerçekten var olduğunu, (2) `docs/module-notes/`
> altındaki hiçbir not dosyasının bu index'te referanssız (orphan) kalmadığını
> doğrular, (3) dokümante edilmemiş production modül sayısının
> `docs/module-notes/inventory-debt-baseline.json`'daki ratchet tavanını
> aşmadığını kontrol eder. Sayılar aşağıda elle güncellenir; script'in kendisi
> bunları otomatik doğrulamaz.
> Baseline, 178 → 150 → 117 → 69 → 10 → **0** şeklinde art arda düşürülerek
> 2026-09-13'te dokümante edilmemiş production modül borcu tamamen
> sıfırlandı; tarihli azaltma hedefleri (`reduction_targets`) bu yüzden
> artık boş bir listedir — script borç sıfırken boş listeye izin verir.
> Yeni, notsuz bir production dosyası eklenirse CI bu ratchet'i (0) aşan
> sayıyı tespit eder; katkı, dosya için `docs/module-notes/` altına bir not
> ekleyip burada referanslamalıdır. `--update` borcu yükseltemez, yalnızca
> gerçek sayı 0'ın altına inemeyeceği için mevcut halinde tutar.

- **Toplam kaynak dosya (tests dahil):** 520
- **Tests dışı dosya sayısı (ayrı not üretilen):** 221
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
- `agent/bootstrap.py` → `docs/module-notes/agent/bootstrap.py.md`
- `agent/core/__init__.py` → `docs/module-notes/agent/core/__init__.py.md`
- `agent/autonomy/` → `docs/module-notes/agent/autonomy.md`
- `agent/core/circuit_breaker.py` → `docs/module-notes/agent/core/circuit_breaker.py.md`
- `agent/core/contracts.py` → `docs/module-notes/agent/core/contracts.py.md`
- `agent/core/contracts_fallback.py` → `docs/module-notes/agent/core/contracts_fallback.py.md`
- `agent/core/event_backends/` → `docs/module-notes/agent/core/event_backends.md`
- `agent/core/event_stream.py` → `docs/module-notes/agent/core/event_stream.py.md`
- `agent/core/memory_hub.py` → `docs/module-notes/agent/core/memory_hub.py.md`
- `agent/core/registry.py` → `docs/module-notes/agent/core/registry.py.md`
- `agent/core/supervisor.py` → `docs/module-notes/agent/core/supervisor.py.md`
- `agent/definitions.py` → `docs/module-notes/agent/definitions.py.md`
- `agent/federation/` → `docs/module-notes/agent/federation.md`
- `agent/github/` → `docs/module-notes/agent/github.md`
- `agent/maintenance/` → `docs/module-notes/agent/maintenance.md`
- `agent/roles/__init__.py` → `docs/module-notes/agent/roles/__init__.py.md`
- `agent/roles/coder_agent.py` → `docs/module-notes/agent/roles/coder_agent.py.md`
- `agent/roles/coverage/` → `docs/module-notes/agent/roles/coverage.md`
- `agent/roles/coverage_agent.py` → `docs/module-notes/agent/roles/coverage_agent.py.md`
- `agent/roles/poyraz_agent.py` → `docs/module-notes/agent/roles/poyraz_agent.py.md`
- `agent/roles/qa_agent.py` → `docs/module-notes/agent/roles/qa_agent.py.md`
- `agent/roles/researcher_agent.py` → `docs/module-notes/agent/roles/researcher_agent.py.md`
- `agent/roles/reviewer/__init__.py` → `docs/module-notes/agent/roles/reviewer/__init__.py.md`
- `agent/roles/reviewer/judge.py` → `docs/module-notes/agent/roles/reviewer/judge.py.md`
- `agent/roles/reviewer_agent.py` → `docs/module-notes/agent/roles/reviewer_agent.py.md`
- `agent/registry.py` → `docs/module-notes/agent/registry.py.md`
- `agent/self_heal/` → `docs/module-notes/agent/self_heal.md`
- `agent/services/` → `docs/module-notes/agent/services.md`
- `agent/swarm.py` → `docs/module-notes/agent/swarm.py.md`
- `agent/sidar_agent.py` → `docs/module-notes/agent/sidar_agent.py.md`
- `agent/tooling.py` → `docs/module-notes/agent/tooling.py.md`
- `agent/triggers.py` → `docs/module-notes/agent/triggers.py.md`
- `alembic.ini` → `docs/module-notes/alembic.ini.md`
- `cli.py` → `docs/module-notes/cli.py.md`
- `config.py` → `docs/module-notes/config.py.md`
- `core/__init__.py` → `docs/module-notes/core/__init__.py.md`
- `core/active_learning.py` → `docs/module-notes/core/active_learning.py.md`
- `core/agent_metrics.py` → `docs/module-notes/core/agent_metrics.py.md`
- `core/cache/` → `docs/module-notes/core/cache.md`
- `core/cache_metrics.py` → `docs/module-notes/core/cache_metrics.py.md`
- `core/ci_remediation.py` → `docs/module-notes/core/ci_remediation.py.md`
- `core/config_app.py` → `docs/module-notes/core/config_app.py.md`
- `core/config_dirs.py` → `docs/module-notes/core/config_dirs.py.md`
- `core/config_dotenv.py` → `docs/module-notes/core/config_dotenv.py.md`
- `core/config_env_helpers.py` → `docs/module-notes/core/config_env_helpers.py.md`
- `core/config_event_bus.py` → `docs/module-notes/core/config_event_bus.py.md`
- `core/config_gpu_detect.py` → `docs/module-notes/core/config_gpu_detect.py.md`
- `core/config_hardware.py` → `docs/module-notes/core/config_hardware.py.md`
- `core/config_logging_setup.py` → `docs/module-notes/core/config_logging_setup.py.md`
- `core/config_observability.py` → `docs/module-notes/core/config_observability.py.md`
- `core/config_orchestrator.py` → `docs/module-notes/core/config_orchestrator.py.md`
- `core/config_postgres.py` → `docs/module-notes/core/config_postgres.py.md`
- `core/config_rag_store.py` → `docs/module-notes/core/config_rag_store.py.md`
- `core/config_rate_limit.py` → `docs/module-notes/core/config_rate_limit.py.md`
- `core/config_runtime_env.py` → `docs/module-notes/core/config_runtime_env.py.md`
- `core/config_runtime_paths.py` → `docs/module-notes/core/config_runtime_paths.py.md`
- `core/config_sandbox.py` → `docs/module-notes/core/config_sandbox.py.md`
- `core/config_scoped_settings.py` → `docs/module-notes/core/config_scoped_settings.py.md`
- `core/config_secret_hardening.py` → `docs/module-notes/core/config_secret_hardening.py.md`
- `core/config_secrets.py` → `docs/module-notes/core/config_secrets.py.md`
- `core/config_validators.py` → `docs/module-notes/core/config_validators.py.md`
- `core/db/` → `docs/module-notes/core/db.py.md`
- `core/db_components/` → `docs/module-notes/core/db_components.md`
- `core/distributed_lock.py` → `docs/module-notes/core/distributed_lock.py.md`
- `core/dlp.py` → `docs/module-notes/core/dlp.py.md`
- `core/embeddings.py` → `docs/module-notes/core/embeddings.py.md`
- `core/entity_memory.py` → `docs/module-notes/core/entity_memory.py.md`
- `core/doctor/__init__.py` → `docs/module-notes/core/doctor/__init__.py.md`
- `core/doctor/__main__.py` → `docs/module-notes/core/doctor/__main__.py.md`
- `core/doctor/checks/__init__.py` → `docs/module-notes/core/doctor/checks/__init__.py.md`
- `core/doctor/checks/database.py` → `docs/module-notes/core/doctor/checks/database.py.md`
- `core/doctor/checks/gpu.py` → `docs/module-notes/core/doctor/checks/gpu.py.md`
- `core/doctor/checks/media.py` → `docs/module-notes/core/doctor/checks/media.py.md`
- `core/doctor/checks/rag.py` → `docs/module-notes/core/doctor/checks/rag.py.md`
- `core/doctor/checks/redis.py` → `docs/module-notes/core/doctor/checks/redis.py.md`
- `core/doctor/checks/security.py` → `docs/module-notes/core/doctor/checks/security.py.md`
- `core/doctor/launcher_preflight.py` → `docs/module-notes/core/doctor/launcher_preflight.py.md`
- `core/doctor/models.py` → `docs/module-notes/core/doctor/models.py.md`
- `core/doctor/reporting.py` → `docs/module-notes/core/doctor/reporting.py.md`
- `core/hitl.py` → `docs/module-notes/core/hitl.py.md`
- `core/judge.py` → `docs/module-notes/core/judge.py.md`
- `core/llm/` → `docs/module-notes/core/llm.md`
- `core/llm_client.py` → `docs/module-notes/core/llm_client.py.md`
- `core/llm_metrics.py` → `docs/module-notes/core/llm_metrics.py.md`
- `core/llm_pricing.py` → `docs/module-notes/core/llm_pricing.py.md`
- `core/logging_config.py` → `docs/module-notes/core/logging_config.py.md`
- `core/memory.py` → `docs/module-notes/core/memory.py.md`
- `core/models.py` → `docs/module-notes/core/models.py.md`
- `core/multimodal.py` → `docs/module-notes/core/multimodal.py.md`
- `core/rag/` → `docs/module-notes/core/rag.py.md`
- `core/router.py` → `docs/module-notes/core/router.py.md`
- `core/test_fixture_policy.py` → `docs/module-notes/core/test_fixture_policy.py.md`
- `core/utils/__init__.py` → `docs/module-notes/core/utils/__init__.py.md`
- `core/utils/json_repair.py` → `docs/module-notes/core/utils/json_repair.py.md`
- `core/utils/network_validation.py` → `docs/module-notes/core/utils/network_validation.py.md`
- `core/utils/token_counter.py` → `docs/module-notes/core/utils/token_counter.py.md`
- `core/utils/trusted_subprocess.py` → `docs/module-notes/core/utils/trusted_subprocess.py.md`
- `core/utils/trusted_urlopen.py` → `docs/module-notes/core/utils/trusted_urlopen.py.md`
- `core/vision.py` → `docs/module-notes/core/vision.py.md`
- `core/voice.py` → `docs/module-notes/core/voice.py.md`
- `data/.gitkeep` → `docs/module-notes/data/gitkeep.md`
- `docker-compose.yml` → `docs/module-notes/docker-compose.yml.md`
- `docker-compose.gpu.yml` → `docs/module-notes/docker-compose.gpu.yml.md`
- `docker-compose.observability.yml` → `docs/module-notes/docker-compose.observability.yml.md`
- `docker_setup/grafana/dashboards/sidar-llm-overview.json` → `docs/module-notes/docker_setup/grafana/dashboards/sidar-llm-overview.json.md`
- `docker_setup/grafana/provisioning/dashboards/dashboards.yml` → `docs/module-notes/docker_setup/grafana/provisioning/dashboards/dashboards.yml.md`
- `docker_setup/grafana/provisioning/datasources/prometheus.yml` → `docs/module-notes/docker_setup/grafana/provisioning/datasources/prometheus.yml.md`
- `docker_setup/prometheus/prometheus.yml` → `docs/module-notes/docker_setup/prometheus/prometheus.yml.md`
- `github_upload.py` → `docs/module-notes/github_upload.py.md`
- `gui_launcher.py` → `docs/module-notes/gui_launcher.py.md`
- `install_sidar.sh` → `docs/module-notes/install_sidar.sh.md`
- `launcher/__init__.py` → `docs/module-notes/launcher/__init__.py.md`
- `launcher/doctor.py` → `docs/module-notes/launcher/doctor.py.md`
- `launcher/process.py` → `docs/module-notes/launcher/process.py.md`
- `launcher/selection.py` → `docs/module-notes/launcher/selection.py.md`
- `launcher/ui.py` → `docs/module-notes/launcher/ui.py.md`
- `main.py` → `docs/module-notes/main.py.md`
- `managers/__init__.py` → `docs/module-notes/managers/__init__.py.md`
- `managers/browser_manager.py` → `docs/module-notes/managers/browser_manager.py.md`
- `managers/code/__init__.py` → `docs/module-notes/managers/code/__init__.py.md`
- `managers/code/docker.py` → `docs/module-notes/managers/code/docker.py.md`
- `managers/code/docker_lifecycle.py` → `docs/module-notes/managers/code/docker_lifecycle.py.md`
- `managers/code/file_io_security.py` → `docs/module-notes/managers/code/file_io_security.py.md`
- `managers/code/git_validation.py` → `docs/module-notes/managers/code/git_validation.py.md`
- `managers/code/linter_runners.py` → `docs/module-notes/managers/code/linter_runners.py.md`
- `managers/code/lsp.py` → `docs/module-notes/managers/code/lsp.py.md`
- `managers/code/patcher.py` → `docs/module-notes/managers/code/patcher.py.md`
- `managers/code/platform.py` → `docs/module-notes/managers/code/platform.py.md`
- `managers/code/pytest_parser.py` → `docs/module-notes/managers/code/pytest_parser.py.md`
- `managers/code/runner.py` → `docs/module-notes/managers/code/runner.py.md`
- `managers/code/security_adapter.py` → `docs/module-notes/managers/code/security_adapter.py.md`
- `managers/code/shell_sandbox.py` → `docs/module-notes/managers/code/shell_sandbox.py.md`
- `managers/code/test_runner_orchestrator.py` → `docs/module-notes/managers/code/test_runner_orchestrator.py.md`
- `managers/code_manager.py` → `docs/module-notes/managers/code_manager.py.md`
- `managers/github_manager.py` → `docs/module-notes/managers/github_manager.py.md`
- `managers/image_resolver.py` → `docs/module-notes/managers/image_resolver.py.md`
- `managers/jira_manager.py` → `docs/module-notes/managers/jira_manager.py.md`
- `managers/package_info.py` → `docs/module-notes/managers/package_info.py.md`
- `managers/security.py` → `docs/module-notes/managers/security.py.md`
- `managers/slack_manager.py` → `docs/module-notes/managers/slack_manager.py.md`
- `managers/social_media_manager.py` → `docs/module-notes/managers/social_media_manager.py.md`
- `managers/system_health.py` → `docs/module-notes/managers/system_health.py.md`
- `managers/teams_manager.py` → `docs/module-notes/managers/teams_manager.py.md`
- `managers/todo_manager.py` → `docs/module-notes/managers/todo_manager.py.md`
- `managers/web_search.py` → `docs/module-notes/managers/web_search.py.md`
- `managers/youtube_manager.py` → `docs/module-notes/managers/youtube_manager.py.md`
- `migrations/env.py` → `docs/module-notes/migrations/env.py.md`
- `migrations/script.py.mako` → `docs/module-notes/migrations/script.py.mako.md`
- `migrations/versions/0001_baseline_schema.py` → `docs/module-notes/migrations/versions/0001_baseline_schema.py.md`
- `plugins/__init__.py` → `docs/module-notes/plugins/__init__.py.md`
- `plugins/aws_management_agent.py` → `docs/module-notes/plugins/aws_management_agent.py.md`
- `plugins/crypto_price_agent.py` → `docs/module-notes/plugins/crypto_price_agent.py.md`
- `plugins/manifest.py` → `docs/module-notes/plugins/manifest.py.md`
- `plugins/slack_notification_agent.py` → `docs/module-notes/plugins/slack_notification_agent.py.md`
- `plugins/upload_agent.py` → `docs/module-notes/plugins/upload_agent.py.md`
- `pyproject.toml` → `docs/module-notes/pyproject.toml.md`
- `run_tests.sh` → `docs/module-notes/run_tests.sh.md`
- `runbooks/production-cutover-playbook.md` → `docs/module-notes/runbooks/production-cutover-playbook.md.md`
- `scripts/audit_metrics.sh` → `docs/module-notes/scripts/audit_metrics.sh.md`
- `scripts/check_empty_test_artifacts.sh` → `docs/module-notes/scripts/check_empty_test_artifacts.sh.md`
- `scripts/collect_repo_metrics.sh` → `docs/module-notes/scripts/collect_repo_metrics.sh.md`
- `scripts/install_host_sandbox.sh` → `docs/module-notes/scripts/install_host_sandbox.sh.md`
- `scripts/load_test_db_pool.py` → `docs/module-notes/scripts/load_test_db_pool.py.md`
- `scripts/migrate_sqlite_to_pg.py` → `docs/module-notes/scripts/migrate_sqlite_to_pg.py.md`
- `web/__init__.py` → `docs/module-notes/web/__init__.py.md`
- `web/app_factory.py` → `docs/module-notes/web/app_factory.py.md`
- `web/autonomy_bridge.py` → `docs/module-notes/web/autonomy_bridge.py.md`
- `web/bootstrap.py` → `docs/module-notes/web/bootstrap.py.md`
- `web/cli.py` → `docs/module-notes/web/cli.py.md`
- `web/collaboration_service.py` → `docs/module-notes/web/collaboration_service.py.md`
- `web/middleware/__init__.py` → `docs/module-notes/web/middleware/__init__.py.md`
- `web/middleware/access_policy.py` → `docs/module-notes/web/middleware/access_policy.py.md`
- `web/middleware/cors.py` → `docs/module-notes/web/middleware/cors.py.md`
- `web/middleware/ratelimit.py` → `docs/module-notes/web/middleware/ratelimit.py.md`
- `web/plugins/__init__.py` → `docs/module-notes/web/plugins/__init__.py.md`
- `web/plugins/sandbox.py` → `docs/module-notes/web/plugins/sandbox.py.md`
- `web/plugins/worker.py` → `docs/module-notes/web/plugins/worker.py.md`
- `web/process_lifecycle.py` → `docs/module-notes/web/process_lifecycle.py.md`
- `web/routes/__init__.py` → `docs/module-notes/web/routes/__init__.py.md`
- `web/routes/agent.py` → `docs/module-notes/web/routes/agent.py.md`
- `web/routes/auth_admin.py` → `docs/module-notes/web/routes/auth_admin.py.md`
- `web/routes/autonomy.py` → `docs/module-notes/web/routes/autonomy.py.md`
- `web/routes/collaboration.py` → `docs/module-notes/web/routes/collaboration.py.md`
- `web/routes/coverage_ops.py` → `docs/module-notes/web/routes/coverage_ops.py.md`
- `web/routes/federation.py` → `docs/module-notes/web/routes/federation.py.md`
- `web/routes/health.py` → `docs/module-notes/web/routes/health.py.md`
- `web/routes/health_runtime.py` → `docs/module-notes/web/routes/health_runtime.py.md`
- `web/routes/hitl.py` → `docs/module-notes/web/routes/hitl.py.md`
- `web/routes/integrations.py` → `docs/module-notes/web/routes/integrations.py.md`
- `web/routes/memory_feedback.py` → `docs/module-notes/web/routes/memory_feedback.py.md`
- `web/routes/metrics.py` → `docs/module-notes/web/routes/metrics.py.md`
- `web/routes/operations.py` → `docs/module-notes/web/routes/operations.py.md`
- `web/routes/operations_models.py` → `docs/module-notes/web/routes/operations_models.py.md`
- `web/routes/orchestration.py` → `docs/module-notes/web/routes/orchestration.py.md`
- `web/routes/plugin_marketplace.py` → `docs/module-notes/web/routes/plugin_marketplace.py.md`
- `web/routes/project_ops.py` → `docs/module-notes/web/routes/project_ops.py.md`
- `web/routes/rag.py` → `docs/module-notes/web/routes/rag.py.md`
- `web/routes/request_models.py` → `docs/module-notes/web/routes/request_models.py.md`
- `web/routes/serialization.py` → `docs/module-notes/web/routes/serialization.py.md`
- `web/routes/static.py` → `docs/module-notes/web/routes/static.py.md`
- `web/routes/vision.py` → `docs/module-notes/web/routes/vision.py.md`
- `web/routes/webhooks.py` → `docs/module-notes/web/routes/webhooks.py.md`
- `web/routes/ws_chat.py` → `docs/module-notes/web/routes/ws_chat.py.md`
- `web/routes/ws_lifecycle.py` → `docs/module-notes/web/routes/ws_lifecycle.py.md`
- `web/routes/ws_voice.py` → `docs/module-notes/web/routes/ws_voice.py.md`
- `web/security.py` → `docs/module-notes/web/security.py.md`
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
