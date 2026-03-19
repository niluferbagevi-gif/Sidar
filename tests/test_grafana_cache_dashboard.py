from pathlib import Path
import json


def test_semantic_cache_dashboard_includes_deep_observability_panels():
    dashboard = json.loads(Path("grafana/dashboards/sidar_overview.json").read_text(encoding="utf-8"))

    titles = {panel.get("title", "") for panel in dashboard.get("panels", [])}
    assert "Cache Redis Latency" in titles
    assert "Evictions / Redis Errors" in titles
    assert "Cache Items" in titles
    assert "Cache Lookups" in titles

    exprs = []
    for panel in dashboard.get("panels", []):
        for target in panel.get("targets", []):
            exprs.append(target.get("expr", ""))

    assert "sidar_cache_items" in exprs
    assert "sidar_cache_redis_latency_ms" in exprs
    assert "sidar_cache_hits_total + sidar_cache_misses_total" in exprs
    assert "rate(sidar_cache_evictions_total[5m])" in exprs
    assert "rate(sidar_cache_redis_errors_total[5m])" in exprs
    assert "rate(sidar_cache_skips_total[5m])" in exprs