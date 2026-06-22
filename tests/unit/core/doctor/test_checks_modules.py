from __future__ import annotations

from core.doctor import DoctorCheck


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
