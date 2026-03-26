from types import SimpleNamespace

from managers.system_health import SystemHealthManager


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_tcp_dependency_health_success_and_exception(monkeypatch):
    cfg = SimpleNamespace(HEALTHCHECK_CONNECT_TIMEOUT_MS=25, REDIS_URL="", DATABASE_URL="")
    mgr = SystemHealthManager(use_gpu=False, cfg=cfg)

    seen = {}

    def _ok(addr, timeout):
        seen["addr"] = addr
        seen["timeout"] = timeout
        return _Conn()

    monkeypatch.setattr("managers.system_health.socket.create_connection", _ok)
    ok = mgr._tcp_dependency_health("redis", 6380, label="redis")
    assert ok == {"healthy": True, "target": "redis:6380", "kind": "redis"}
    assert seen == {"addr": ("redis", 6380), "timeout": 0.05}

    def _boom(addr, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr("managers.system_health.socket.create_connection", _boom)
    failed = mgr._tcp_dependency_health("db", 5432, label="database")
    assert failed["healthy"] is False
    assert failed["target"] == "db:5432"
    assert failed["kind"] == "database"
    assert "connection refused" in failed["error"]


def test_check_redis_disabled_and_tcp_mode(monkeypatch):
    disabled_mgr = SystemHealthManager(
        use_gpu=False,
        cfg=SimpleNamespace(HEALTHCHECK_CONNECT_TIMEOUT_MS=50, REDIS_URL="", DATABASE_URL=""),
    )
    assert disabled_mgr.check_redis() == {"healthy": True, "kind": "redis", "mode": "disabled"}

    tcp_mgr = SystemHealthManager(
        use_gpu=False,
        cfg=SimpleNamespace(
            HEALTHCHECK_CONNECT_TIMEOUT_MS=50,
            REDIS_URL="redis://cache.internal:6381/0",
            DATABASE_URL="",
        ),
    )

    def _tcp(host, port, *, label):
        assert host == "cache.internal"
        assert port == 6381
        assert label == "redis"
        return {"healthy": False, "target": f"{host}:{port}", "kind": label, "error": "timeout"}

    monkeypatch.setattr(tcp_mgr, "_tcp_dependency_health", _tcp)
    status = tcp_mgr.check_redis()
    assert status["mode"] == "tcp"
    assert status["healthy"] is False
    assert status["target"] == "cache.internal:6381"


def test_check_database_disabled_and_tcp_mode(monkeypatch):
    disabled_mgr = SystemHealthManager(
        use_gpu=False,
        cfg=SimpleNamespace(HEALTHCHECK_CONNECT_TIMEOUT_MS=50, REDIS_URL="", DATABASE_URL=""),
    )
    assert disabled_mgr.check_database() == {"healthy": True, "kind": "database", "mode": "disabled"}

    tcp_mgr = SystemHealthManager(
        use_gpu=False,
        cfg=SimpleNamespace(
            HEALTHCHECK_CONNECT_TIMEOUT_MS=50,
            REDIS_URL="",
            DATABASE_URL="postgresql://sidar:pw@db.internal:5433/sidar",
        ),
    )

    def _tcp(host, port, *, label):
        assert host == "db.internal"
        assert port == 5433
        assert label == "database"
        return {"healthy": True, "target": f"{host}:{port}", "kind": label}

    monkeypatch.setattr(tcp_mgr, "_tcp_dependency_health", _tcp)
    status = tcp_mgr.check_database()
    assert status == {
        "healthy": True,
        "target": "db.internal:5433",
        "kind": "database",
        "mode": "postgresql",
    }