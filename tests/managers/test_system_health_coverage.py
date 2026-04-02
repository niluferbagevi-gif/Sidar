from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from managers.system_health import SystemHealthManager, render_llm_metrics_prometheus


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> SystemHealthManager:
    monkeypatch.setattr(SystemHealthManager, "_check_import", staticmethod(lambda _name: False))
    monkeypatch.setattr(SystemHealthManager, "_check_gpu", lambda self: False)
    return SystemHealthManager(use_gpu=False, cfg=SimpleNamespace())


def test_render_llm_metrics_prometheus_includes_totals_and_aliases() -> None:
    payload = {
        "totals": {"calls": 3, "cost_usd": 1.5, "total_tokens": 200, "failures": 1},
        "cache": {"hits": 2, "misses": 1, "skips": 0, "evictions": 4, "redis_errors": 0, "hit_rate": 0.66, "items": 7, "redis_latency_ms": 12.0},
    }

    text = render_llm_metrics_prometheus(payload)

    assert "sidar_llm_calls_total 3" in text
    assert "sidar_semantic_cache_hits_total 2" in text
    assert "sidar_cache_hits_total 2" in text


def test_check_redis_returns_disabled_when_url_missing(manager: SystemHealthManager) -> None:
    manager.cfg = SimpleNamespace(REDIS_URL="")

    result = manager.check_redis()

    assert result == {"healthy": True, "kind": "redis", "mode": "disabled"}


def test_check_database_sqlite_missing_file_returns_error(manager: SystemHealthManager, tmp_path: Path) -> None:
    missing = tmp_path / "no.db"
    manager.cfg = SimpleNamespace(DATABASE_URL=f"sqlite:///{missing}")

    result = manager.check_database()

    assert result["healthy"] is False
    assert result["mode"] == "sqlite"
    assert "not found" in result["error"]


def test_get_health_summary_marks_degraded_when_dependency_unhealthy(manager: SystemHealthManager, monkeypatch: pytest.MonkeyPatch) -> None:
    manager.cfg = SimpleNamespace(ENABLE_DEPENDENCY_HEALTHCHECKS=True)
    monkeypatch.setattr(manager, "get_cpu_usage", lambda *_args, **_kwargs: 25.0)
    monkeypatch.setattr(manager, "get_memory_info", lambda: {"percent": 60.0})
    monkeypatch.setattr(manager, "get_gpu_info", lambda: {"available": False})
    monkeypatch.setattr(manager, "check_ollama", lambda: True)
    monkeypatch.setattr(
        manager,
        "get_dependency_health",
        lambda: {
            "redis": {"healthy": True},
            "database": {"healthy": False, "error": "dial timeout"},
        },
    )

    summary = manager.get_health_summary()

    assert summary["status"] == "degraded"
    assert summary["dependencies"]["database"]["healthy"] is False
