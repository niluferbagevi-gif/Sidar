from pathlib import Path


def test_config_and_runtime_sources_expose_pool_settings():
    config_src = Path('config.py').read_text(encoding='utf-8')
    web_src = Path('web_server.py').read_text(encoding='utf-8')
    llm_src = Path('core/llm_client.py').read_text(encoding='utf-8')
    event_src = Path('agent/core/event_stream.py').read_text(encoding='utf-8')

    assert 'REDIS_MAX_CONNECTIONS' in config_src
    assert 'DB_POOL_SIZE' in config_src
    assert 'max_connections=max(1, int(getattr(cfg, "REDIS_MAX_CONNECTIONS", 50) or 50))' in web_src
    assert 'REDIS_MAX_CONNECTIONS' in llm_src
    assert 'self._redis_max_connections' in event_src


def test_docker_compose_and_helm_define_pool_envs_and_overrides():
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')
    values = Path('helm/sidar/values.yaml').read_text(encoding='utf-8')
    staging = Path('helm/sidar/values-staging.yaml').read_text(encoding='utf-8')
    prod = Path('helm/sidar/values-prod.yaml').read_text(encoding='utf-8')
    web_tpl = Path('helm/sidar/templates/deployment-web.yaml').read_text(encoding='utf-8')
    ai_tpl = Path('helm/sidar/templates/deployment-ai-worker.yaml').read_text(encoding='utf-8')

    assert 'DB_POOL_SIZE=${DB_POOL_SIZE:-10}' in compose
    assert 'REDIS_MAX_CONNECTIONS=${REDIS_MAX_CONNECTIONS:-100}' in compose
    assert 'database:\n  poolSize: 10' in values
    assert 'maxConnections: 100' in values
    assert 'database:\n  poolSize: 8' in staging
    assert 'maxConnections: 60' in staging
    assert 'database:\n  poolSize: 30' in prod
    assert 'maxConnections: 200' in prod
    assert 'name: DB_POOL_SIZE' in web_tpl and 'name: REDIS_MAX_CONNECTIONS' in web_tpl
    assert 'name: DB_POOL_SIZE' in ai_tpl and 'name: REDIS_MAX_CONNECTIONS' in ai_tpl


def test_production_cutover_runbook_documents_pool_review_and_deploy_steps():
    playbook = Path('runbooks/production-cutover-playbook.md').read_text(encoding='utf-8')

    assert '## 10) PostgreSQL ve Redis pool doğrulaması' in playbook
    assert 'helm upgrade --install sidar ./helm/sidar' in playbook
    assert 'docker compose up -d postgres redis jaeger prometheus grafana sidar-web' in playbook
    assert 'docker/grafana/dashboards/sidar-llm-overview.json' in playbook
    assert 'grafana/dashboards/sidar_overview.json' in playbook