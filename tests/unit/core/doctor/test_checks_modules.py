from __future__ import annotations

from core.doctor import DoctorCheck


def test_check_redis_passes_when_url_is_configured(monkeypatch):
    from core.doctor.checks import redis as redis_checks

    monkeypatch.setenv("REDIS_URL", "redis://cache.local:6379/0")
    monkeypatch.setenv("SIDAR_EVENT_BUS_BACKEND", "redis")

    check = redis_checks.check_redis()

    assert check.status == "pass"
    assert check.message == "Redis URL is configured"
    assert check.details == {
        "redis_url_set": True,
        "event_bus_backend": "redis",
        "required_for_remote_event_bus": True,
    }


def test_check_redis_warns_when_redis_backend_has_no_url(monkeypatch):
    from core.doctor.checks import redis as redis_checks

    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("SIDAR_EVENT_BUS_BACKEND", "redis")

    check = redis_checks.check_redis()

    assert check.status == "warn"
    assert check.message == "REDIS_URL is not set; Redis event bus will use local fallback"
    assert check.details == {
        "redis_url_set": False,
        "event_bus_backend": "redis",
        "required_for_remote_event_bus": True,
    }


def test_check_redis_passes_when_non_redis_backend_has_no_url(monkeypatch):
    from core.doctor.checks import redis as redis_checks

    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("SIDAR_EVENT_BUS_BACKEND", "kafka")

    check = redis_checks.check_redis()

    assert check.status == "pass"
    assert check.message == "Redis is not the selected event bus backend"
    assert check.details == {
        "redis_url_set": False,
        "event_bus_backend": "kafka",
        "required_for_remote_event_bus": False,
    }


def test_check_rag_index_ready_delegates_to_doctor(monkeypatch):
    from core.doctor.checks import rag as rag_checks

    sentinel = DoctorCheck("rag_index", "pass", "ok", {})
    monkeypatch.setattr(rag_checks._doctor, "check_rag_index_ready", lambda: sentinel)

    assert rag_checks.check_rag_index_ready() is sentinel


def test_check_graphrag_entity_memory_ready_delegates_to_doctor(monkeypatch):
    from core.doctor.checks import rag as rag_checks

    sentinel = DoctorCheck("graphrag_entity_memory", "pass", "ok", {})
    monkeypatch.setattr(
        rag_checks._doctor, "check_graphrag_entity_memory_ready", lambda: sentinel
    )

    assert rag_checks.check_graphrag_entity_memory_ready() is sentinel


def test_check_rag_readiness_delegates_to_doctor(monkeypatch):
    from core.doctor.checks import rag as rag_checks

    sentinel = DoctorCheck("rag", "pass", "ok", {})
    monkeypatch.setattr(rag_checks._doctor, "check_rag_readiness", lambda: sentinel)

    assert rag_checks.check_rag_readiness() is sentinel
