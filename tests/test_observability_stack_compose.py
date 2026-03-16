from pathlib import Path

import yaml


def test_compose_includes_observability_stack_and_tracing_wiring():
    compose = yaml.safe_load(Path('docker-compose.yml').read_text(encoding='utf-8'))
    services = compose.get('services', {})

    assert 'redis' in services
    assert 'postgres' in services
    assert 'jaeger' in services
    assert 'sidar-web' in services

    web = services['sidar-web']
    depends_on = web.get('depends_on', [])
    assert 'redis' in depends_on
    assert 'postgres' in depends_on
    assert 'jaeger' in depends_on

    env_list = web.get('environment', [])
    env_blob = '\n'.join(str(x) for x in env_list)

    assert 'ENABLE_TRACING' in env_blob
    assert 'OTEL_EXPORTER_ENDPOINT' in env_blob
    assert 'DATABASE_URL' in env_blob



def test_compose_exposes_jaeger_ui_port():
    compose = yaml.safe_load(Path('docker-compose.yml').read_text(encoding='utf-8'))
    jaeger = compose['services']['jaeger']
    ports = jaeger.get('ports', [])
    assert '16686:16686' in ports
    assert '4317:4317' in ports
