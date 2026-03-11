from pathlib import Path
import json


def test_grafana_dashboard_and_provisioning_files_exist():
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')
    assert './docker/grafana/provisioning:/etc/grafana/provisioning:ro' in compose
    assert './docker/grafana/dashboards:/var/lib/grafana/dashboards:ro' in compose

    ds = Path('docker/grafana/provisioning/datasources/prometheus.yml').read_text(encoding='utf-8')
    assert 'name: Prometheus' in ds
    assert 'url: http://prometheus:9090' in ds

    providers = Path('docker/grafana/provisioning/dashboards/dashboards.yml').read_text(encoding='utf-8')
    assert 'path: /var/lib/grafana/dashboards' in providers


def test_sidar_dashboard_includes_required_panels_and_queries():
    dashboard = json.loads(Path('docker/grafana/dashboards/sidar-llm-overview.json').read_text(encoding='utf-8'))
    titles = {panel.get('title', '') for panel in dashboard.get('panels', [])}
    assert 'Günlük Token Maliyeti (USD)' in titles
    assert 'Ajan Bazlı Hata Oranı (429 Rate Limit)' in titles
    assert 'Aktif Kullanıcı Sayısı (LLM çağrısı yapan)' in titles

    exprs = []
    for panel in dashboard.get('panels', []):
        for target in panel.get('targets', []):
            exprs.append(target.get('expr', ''))

    assert any('sidar_llm_cost_total_usd' in q for q in exprs)
    assert any('sidar_llm_failures_total' in q and 'sidar_llm_calls_total' in q for q in exprs)
    assert any('sidar_llm_user_calls_total' in q for q in exprs)
