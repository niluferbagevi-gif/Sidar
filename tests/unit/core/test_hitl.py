from __future__ import annotations

import asyncio
from typing import Any

import pytest

import core.hitl as hitl
from tests.fixtures.factories import build_hitl_request


@pytest.fixture(autouse=True)
def reset_hitl_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hitl, "_STORE", hitl._HITLStore())
    monkeypatch.setattr(hitl, "_GATE", None)
    monkeypatch.setattr(hitl, "_broadcast_hook", None)
    monkeypatch.delenv("HITL_ENABLED", raising=False)
    monkeypatch.delenv("HITL_TIMEOUT_SECONDS", raising=False)


def run(coro):
    return asyncio.run(coro)


def _make_request(
    *, request_id: str, expires_at: float, decision: hitl.HITLDecision = hitl.HITLDecision.PENDING
) -> hitl.HITLRequest:
    return build_hitl_request(
        request_id=request_id,
        expires_at=expires_at,
        decision=decision,
    )


def test_hitl_request_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    req = _make_request(request_id="r1", expires_at=100.0)
    monkeypatch.setattr(hitl.time, "time", lambda: 99.0)
    assert req.is_expired() is False

    monkeypatch.setattr(hitl.time, "time", lambda: 101.0)
    assert req.is_expired() is True

    as_dict = req.to_dict()
    assert as_dict["decision"] == "pending"


def test_store_add_get_pending_recent_and_eviction(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = hitl._HITLStore(max_size=2)

    req1 = _make_request(request_id="old", expires_at=50.0)
    req2 = _make_request(request_id="live", expires_at=200.0)
    req3 = _make_request(request_id="new", expires_at=300.0)

    with caplog.at_level("WARNING"):
        run(store.add(req1))
        run(store.add(req2))
        run(store.add(req3))

    assert run(store.get("old")) is None
    assert run(store.get("missing")) is None
    assert run(store.get("live")).request_id == "live"

    monkeypatch.setattr(hitl.time, "time", lambda: 100.0)
    pending = run(store.pending())
    assert [r.request_id for r in pending] == ["live", "new"]
    assert "HITL: Kuyruk dolu, bekleyen istek düşürüldü: old" in caplog.text

    recent = run(store.all_recent(limit=1))
    assert [r.request_id for r in recent] == ["new"]


def test_store_logs_when_evicted_request_is_already_decided(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = hitl._HITLStore(max_size=1)
    decided = _make_request(request_id="done", expires_at=50.0, decision=hitl.HITLDecision.APPROVED)
    newest = _make_request(request_id="new", expires_at=60.0)

    run(store.add(decided))
    with caplog.at_level("WARNING"):
        run(store.add(newest))

    assert (
        "HITL: Kuyruk dolu, kararı verilmiş istek düşürüldü: done (karar=approved)" in caplog.text
    )


def test_store_pending_marks_expired_as_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    store = hitl._HITLStore()
    expired = _make_request(request_id="exp", expires_at=10.0)
    run(store.add(expired))

    monkeypatch.setattr(hitl.time, "time", lambda: 20.0)
    assert run(store.pending()) == []
    assert expired.decision == hitl.HITLDecision.TIMEOUT


def test_store_pending_and_all_recent_initialize_lock_and_skip_non_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = hitl._HITLStore()
    store._requests.extend(
        [
            _make_request(
                request_id="r-approved", expires_at=200.0, decision=hitl.HITLDecision.APPROVED
            ),
            _make_request(
                request_id="r-pending", expires_at=200.0, decision=hitl.HITLDecision.PENDING
            ),
        ]
    )
    store._index = {req.request_id: req for req in store._requests}
    store._lock = None

    monkeypatch.setattr(hitl.time, "time", lambda: 100.0)
    pending = run(store.pending())
    assert [r.request_id for r in pending] == ["r-pending"]

    store._lock = None
    recent = run(store.all_recent(limit=2))
    assert [r.request_id for r in recent] == ["r-approved", "r-pending"]


def test_notify_without_hook_and_with_exception(caplog: pytest.LogCaptureFixture) -> None:
    req = _make_request(request_id="n1", expires_at=100.0)

    run(hitl.notify(req))

    async def broken_hook(payload: dict[str, Any]) -> None:
        raise RuntimeError(f"boom {payload['type']}")

    hitl.set_hitl_broadcast_hook(broken_hook)
    with caplog.at_level("DEBUG"):
        run(hitl.notify(req))

    assert "HITL broadcast hatası" in caplog.text


def test_notify_uses_registered_hook() -> None:
    req = _make_request(request_id="n2", expires_at=100.0)
    captured: list[dict[str, Any]] = []

    async def ok_hook(payload: dict[str, Any]) -> None:
        captured.append(payload)

    hitl.set_hitl_broadcast_hook(ok_hook)
    run(hitl.notify(req))

    assert captured[0]["type"] == "hitl_request"
    assert captured[0]["data"]["request_id"] == "n2"


def test_hitl_gate_init_and_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HITL_ENABLED", "YES")
    monkeypatch.setenv("HITL_TIMEOUT_SECONDS", "3")

    gate = hitl.HITLGate()
    assert gate.enabled is True
    assert gate.timeout == 10

    singleton_a = hitl.get_hitl_gate()
    singleton_b = hitl.get_hitl_gate()
    assert singleton_a is singleton_b


def test_request_approval_returns_true_when_disabled() -> None:
    gate = hitl.HITLGate()

    approved = run(gate.request_approval(action="x", description="y"))

    assert approved is True


def test_request_approval_approved_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HITL_ENABLED", "true")
    monkeypatch.setenv("HITL_TIMEOUT_SECONDS", "30")
    gate = hitl.HITLGate()

    async def fast_sleep(_: float) -> None:
        pending = await hitl.get_hitl_store().pending()
        if pending:
            await gate.respond(pending[0].request_id, approved=True, decided_by="alice")

    run(fast_sleep(0))
    monkeypatch.setattr(hitl.asyncio, "sleep", fast_sleep)

    approved = run(
        gate.request_approval(
            action="github_pr_create",
            description="Create PR",
            payload={"repo": "sidar"},
            requested_by="GithubManager",
        )
    )

    assert approved is True


def test_request_approval_rejected_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HITL_ENABLED", "1")
    monkeypatch.setenv("HITL_TIMEOUT_SECONDS", "30")
    gate = hitl.HITLGate()

    async def fast_sleep(_: float) -> None:
        pending = await hitl.get_hitl_store().pending()
        if pending:
            await gate.respond(
                pending[0].request_id,
                approved=False,
                decided_by="bob",
                rejection_reason="riskli işlem",
            )

    run(fast_sleep(0))
    monkeypatch.setattr(hitl.asyncio, "sleep", fast_sleep)

    approved = run(gate.request_approval(action="file_delete", description="Delete file"))

    assert approved is False


def test_request_approval_returns_false_when_request_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HITL_ENABLED", "true")
    monkeypatch.setenv("HITL_TIMEOUT_SECONDS", "30")
    gate = hitl.HITLGate()

    async def remove_request_and_sleep(_: float) -> None:
        store = hitl.get_hitl_store()
        pending = await store.pending()
        if pending:
            store._index.pop(pending[0].request_id, None)

    run(remove_request_and_sleep(0))
    monkeypatch.setattr(hitl.asyncio, "sleep", remove_request_and_sleep)

    approved = run(gate.request_approval(action="danger", description="will disappear"))

    assert approved is False


def test_request_approval_timeout_updates_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HITL_ENABLED", "true")
    monkeypatch.setenv("HITL_TIMEOUT_SECONDS", "10")
    gate = hitl.HITLGate()

    now = [0.0]

    def fake_time() -> float:
        return now[0]

    async def jump_time(_: float) -> None:
        now[0] = 11.0

    monkeypatch.setattr(hitl.time, "time", fake_time)
    monkeypatch.setattr(hitl.asyncio, "sleep", jump_time)

    approved = run(gate.request_approval(action="file_overwrite", description="Overwrite file"))

    assert approved is False
    requests = run(hitl.get_hitl_store().all_recent(limit=1))
    assert requests[0].decision == hitl.HITLDecision.TIMEOUT
    assert requests[0].decided_at == 11.0


def test_request_approval_timeout_branch_skips_timeout_update_when_decision_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HITL_ENABLED", "true")
    monkeypatch.setenv("HITL_TIMEOUT_SECONDS", "10")
    gate = hitl.HITLGate()
    now = [0.0]

    def fake_time() -> float:
        return now[0]

    async def jump_and_decide(_: float) -> None:
        store = hitl.get_hitl_store()
        pending = await store.pending()
        if pending:
            pending[0].decision = hitl.HITLDecision.REJECTED
        now[0] = 11.0

    run(jump_and_decide(0))
    monkeypatch.setattr(hitl.time, "time", fake_time)
    monkeypatch.setattr(hitl.asyncio, "sleep", jump_and_decide)

    approved = run(gate.request_approval(action="file_overwrite", description="Overwrite file"))
    assert approved is False
    requests = run(hitl.get_hitl_store().all_recent(limit=1))
    assert requests[0].decision == hitl.HITLDecision.REJECTED
    assert requests[0].decided_at is None


def test_request_approval_timeout_branch_skips_timeout_update_when_decision_becomes_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HITL_ENABLED", "true")
    monkeypatch.setenv("HITL_TIMEOUT_SECONDS", "10")
    gate = hitl.HITLGate()
    now = [0.0]

    def fake_time() -> float:
        return now[0]

    async def jump_and_approve(_: float) -> None:
        store = hitl.get_hitl_store()
        pending = await store.pending()
        if pending:
            pending[0].decision = hitl.HITLDecision.APPROVED
        now[0] = 11.0

    run(jump_and_approve(0))
    now[0] = 0.0
    monkeypatch.setattr(hitl.time, "time", fake_time)
    monkeypatch.setattr(hitl.asyncio, "sleep", jump_and_approve)

    approved = run(gate.request_approval(action="file_overwrite", description="Overwrite file"))
    assert approved is False
    requests = run(hitl.get_hitl_store().all_recent(limit=1))
    assert requests[0].decision == hitl.HITLDecision.APPROVED
    assert requests[0].decided_at is None


def test_request_approval_timeout_branch_skips_timeout_update_when_request_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HITL_ENABLED", "true")
    monkeypatch.setenv("HITL_TIMEOUT_SECONDS", "10")
    gate = hitl.HITLGate()
    now = [0.0]

    def fake_time() -> float:
        return now[0]

    async def remove_request_and_jump(_: float) -> None:
        store = hitl.get_hitl_store()
        pending = await store.pending()
        if pending:
            store._index.pop(pending[0].request_id, None)
        now[0] = 11.0

    run(remove_request_and_jump(0))
    monkeypatch.setattr(hitl.time, "time", fake_time)
    monkeypatch.setattr(hitl.asyncio, "sleep", remove_request_and_jump)

    approved = run(gate.request_approval(action="file_overwrite", description="Overwrite file"))

    assert approved is False
    latest = run(hitl.get_hitl_store().all_recent(limit=1))[0]
    assert latest.decision == hitl.HITLDecision.PENDING
    assert latest.decided_at is None


def test_respond_none_already_decided_and_rejected_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HITL_ENABLED", "true")
    gate = hitl.HITLGate()
    store = hitl.get_hitl_store()

    assert run(gate.respond("missing", approved=True)) is None

    already = _make_request(request_id="done", expires_at=50.0, decision=hitl.HITLDecision.APPROVED)
    run(store.add(already))
    same = run(gate.respond("done", approved=False))
    assert same is already
    assert same.decision == hitl.HITLDecision.APPROVED

    pending = _make_request(request_id="pending", expires_at=50.0)
    run(store.add(pending))

    monkeypatch.setattr(hitl.time, "time", lambda: 123.0)
    rejected = run(
        gate.respond("pending", approved=False, decided_by="eve", rejection_reason="policy")
    )
    assert rejected.decision == hitl.HITLDecision.REJECTED
    assert rejected.decided_at == 123.0
    assert rejected.decided_by == "eve"
    assert rejected.rejection_reason == "policy"

    pending2 = _make_request(request_id="pending2", expires_at=50.0)
    run(store.add(pending2))
    approved = run(
        gate.respond("pending2", approved=True, decided_by="eve", rejection_reason="ignored")
    )
    assert approved.decision == hitl.HITLDecision.APPROVED
    assert approved.rejection_reason == ""
