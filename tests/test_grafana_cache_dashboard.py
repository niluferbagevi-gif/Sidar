from pathlib import Path
import json


_HIT_RATE_FORMULA = (
    "sum(rate(sidar_semantic_cache_hits_total[5m])) / "
    "(sum(rate(sidar_semantic_cache_hits_total[5m])) + "
    "sum(rate(sidar_semantic_cache_misses_total[5m]))) * 100"
)


def _load_dashboard(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _panel_titles(dashboard: dict) -> set[str]:
    return {panel.get("title", "") for panel in dashboard.get("panels", [])}


def _panel_exprs(dashboard: dict) -> list[str]:
    exprs: list[str] = []
    for panel in dashboard.get("panels", []):
        for target in panel.get("targets", []):
            exprs.append(target.get("expr", ""))
    return exprs


def test_semantic_cache_dashboard_includes_deep_observability_panels():
    dashboard = _load_dashboard("grafana/dashboards/sidar_overview.json")

    titles = _panel_titles(dashboard)
    assert "Cache Redis Latency" in titles
    assert "Evictions / Redis Errors" in titles
    assert "Cache Items" in titles
    assert "Cache Lookups" in titles
    assert "Cache Hit Rate" in titles

    exprs = _panel_exprs(dashboard)
    assert "sidar_semantic_cache_items" in exprs
    assert "sidar_semantic_cache_redis_latency_ms" in exprs
    assert "sidar_semantic_cache_hits_total + sidar_semantic_cache_misses_total" in exprs
    assert "rate(sidar_semantic_cache_evictions_total[5m])" in exprs
    assert "rate(sidar_semantic_cache_redis_errors_total[5m])" in exprs
    assert "rate(sidar_semantic_cache_skips_total[5m])" in exprs
    assert _HIT_RATE_FORMULA in exprs


def test_docker_dashboard_includes_semantic_cache_panels():
    dashboard = _load_dashboard("docker/grafana/dashboards/sidar-llm-overview.json")

    titles = _panel_titles(dashboard)
    assert "Semantic Cache" in titles
    assert "Cache Hit Rate" in titles
    assert "Cache Hit/Miss Trend" in titles
    assert "Evictions / Redis Errors" in titles

    exprs = _panel_exprs(dashboard)
    assert _HIT_RATE_FORMULA in exprs
    assert "rate(sidar_semantic_cache_hits_total[5m])" in exprs
    assert "rate(sidar_semantic_cache_misses_total[5m])" in exprs
    assert "sidar_semantic_cache_items" in exprs
    assert "sidar_semantic_cache_redis_latency_ms" in exprs
