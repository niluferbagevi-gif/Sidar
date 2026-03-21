from types import SimpleNamespace

from managers.system_health import SystemHealthManager


def test_get_health_summary_marks_status_degraded_when_dependency_checks_fail(monkeypatch):
    cfg = SimpleNamespace(
        ENABLE_DEPENDENCY_HEALTHCHECKS=True,
        HEALTHCHECK_CONNECT_TIMEOUT_MS=50,
        REDIS_URL="redis://redis:6379/0",
        DATABASE_URL="postgresql://sidar:sidar@postgresql:5432/sidar",
    )
    mgr = SystemHealthManager(use_gpu=False, cfg=cfg)

    monkeypatch.setattr(mgr, "get_cpu_usage", lambda interval=None: 1.0)
    monkeypatch.setattr(mgr, "get_memory_info", lambda: {"percent": 2.0})
    monkeypatch.setattr(mgr, "get_gpu_info", lambda: {"available": False})
    monkeypatch.setattr(mgr, "check_ollama", lambda: True)
    monkeypatch.setattr(mgr, "check_redis", lambda: {"healthy": False, "kind": "redis", "error": "down"})
    monkeypatch.setattr(mgr, "check_database", lambda: {"healthy": True, "kind": "database"})

    summary = mgr.get_health_summary()

    assert summary["status"] == "degraded"
    assert summary["dependencies"]["redis"]["healthy"] is False
    assert summary["dependencies"]["database"]["healthy"] is True


def test_check_database_sqlite_reports_missing_file(tmp_path):
    cfg = SimpleNamespace(
        ENABLE_DEPENDENCY_HEALTHCHECKS=True,
        HEALTHCHECK_CONNECT_TIMEOUT_MS=50,
        REDIS_URL="redis://redis:6379/0",
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'missing.db'}",
    )
    mgr = SystemHealthManager(use_gpu=False, cfg=cfg)

    status = mgr.check_database()

    assert status["healthy"] is False
    assert status["mode"] == "sqlite"
