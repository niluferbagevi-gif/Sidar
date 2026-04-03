from __future__ import annotations

from types import SimpleNamespace

import pytest

from managers.system_health import SystemHealthManager


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> SystemHealthManager:
    monkeypatch.setattr(SystemHealthManager, "_check_import", staticmethod(lambda _name: False))
    monkeypatch.setattr(SystemHealthManager, "_check_gpu", lambda self: False)
    return SystemHealthManager(use_gpu=False, cfg=SimpleNamespace())


def test_system_health_tcp_dependency_error_and_database_modes(manager: SystemHealthManager, monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: _Ctx())
    ok = manager._tcp_dependency_health("localhost", 1234, label="redis")
    assert ok["healthy"] is True

    def _raise(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(socket, "create_connection", _raise)
    failed = manager._tcp_dependency_health("localhost", 5432, label="database")
    assert failed["healthy"] is False
    assert "connection refused" in failed["error"]

    manager.cfg = SimpleNamespace(DATABASE_URL="postgresql://u:p@db.internal:5544/app")
    db = manager.check_database()
    assert db["mode"] == "postgresql"
    assert db["target"].endswith(":5544")


def test_system_health_full_report_and_repr(manager: SystemHealthManager, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager, "get_cpu_usage", lambda *_args, **_kwargs: 10.0)
    monkeypatch.setattr(manager, "get_memory_info", lambda: {"used_gb": 2.0, "total_gb": 8.0, "percent": 25.0})
    monkeypatch.setattr(manager, "check_ollama", lambda: True)
    monkeypatch.setattr(manager, "get_gpu_info", lambda: {"available": False, "reason": "GPU disabled"})

    captured = {}
    monkeypatch.setattr(manager, "update_prometheus_metrics", lambda payload: captured.update(payload))

    report = manager.full_report()
    assert "[Sistem Sağlık Raporu]" in report
    assert "Ollama    : Çevrimiçi" in report
    assert captured["cpu_percent"] == 10.0
    assert "SystemHealthManager" in repr(manager)
