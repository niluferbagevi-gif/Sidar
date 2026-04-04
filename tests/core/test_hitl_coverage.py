from __future__ import annotations

import asyncio

import core.hitl as mod


def _make_request(request_id: str = "req-1", *, expires_at: float = 200.0) -> mod.HITLRequest:
    return mod.HITLRequest(
        request_id=request_id,
        action="file_delete",
        description="delete",
        payload={"path": "/tmp/a"},
        requested_by="tester",
        created_at=100.0,
        expires_at=expires_at,
    )


def test_hitl_request_helpers_and_store_basics(monkeypatch) -> None:
    req = _make_request(expires_at=10.0)
    monkeypatch.setattr(mod.time, "time", lambda: 20.0)

    assert req.is_expired() is True
    assert req.to_dict()["decision"] == "pending"

    store = mod._HITLStore(max_size=2)

    async def _run():
        await store.add(_make_request("r1"))
        await store.add(_make_request("r2"))
        await store.add(_make_request("r3"))

        assert await store.get("r1") is None
        assert (await store.get("r2")).request_id == "r2"

        pending = await store.pending()
        assert [r.request_id for r in pending] == ["r2", "r3"]

        recent = await store.all_recent(limit=1)
        assert [r.request_id for r in recent] == ["r3"]

    asyncio.run(_run())


def test_store_pending_marks_expired_as_timeout(monkeypatch) -> None:
    store = mod._HITLStore(max_size=5)

    async def _seed():
        await store.add(_make_request("expired", expires_at=100.0))
        await store.add(_make_request("alive", expires_at=300.0))

    asyncio.run(_seed())
    monkeypatch.setattr(mod.time, "time", lambda: 200.0)

    async def _run():
        pending = await store.pending()
        assert [r.request_id for r in pending] == ["alive"]
        expired = await store.get("expired")
        assert expired.decision == mod.HITLDecision.TIMEOUT

    asyncio.run(_run())


def test_notify_hook_set_success_and_exception_path() -> None:
    req = _make_request("n1")
    calls = []

    async def _ok(payload):
        calls.append(payload)

    mod.set_hitl_broadcast_hook(_ok)
    asyncio.run(mod.notify(req))
    assert calls and calls[0]["type"] == "hitl_request"

    async def _boom(_payload):
        raise RuntimeError("boom")

    mod.set_hitl_broadcast_hook(_boom)
    asyncio.run(mod.notify(req))

    mod._broadcast_hook = None
    asyncio.run(mod.notify(req))


def test_gate_disabled_and_singleton(monkeypatch) -> None:
    monkeypatch.setenv("HITL_ENABLED", "false")
    monkeypatch.setenv("HITL_TIMEOUT_SECONDS", "")

    gate = mod.HITLGate()
    assert gate.enabled is False
    assert gate.timeout == mod._DEFAULT_TIMEOUT
    assert asyncio.run(gate.request_approval(action="a", description="d")) is True

    mod._GATE = None
    g1 = mod.get_hitl_gate()
    g2 = mod.get_hitl_gate()
    assert g1 is g2


def test_gate_request_approval_approved_rejected_timeout_and_missing(monkeypatch) -> None:
    class _Store:
        def __init__(self, responses):
            self.responses = list(responses)
            self.added = []

        async def add(self, req):
            self.added.append(req)

        async def get(self, _request_id):
            if not self.responses:
                return None
            return self.responses.pop(0)

    class _Clock:
        def __init__(self, values):
            self.values = list(values)
            self.last = values[-1] if values else 0.0

        def __call__(self):
            if self.values:
                self.last = self.values.pop(0)
                return self.last
            return self.last

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setenv("HITL_ENABLED", "true")
    monkeypatch.setenv("HITL_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(mod.logger, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod.logger, "warning", lambda *args, **kwargs: None)

    # approved path
    gate = mod.HITLGate()
    approved_req = _make_request("a1")
    approved_req.decision = mod.HITLDecision.APPROVED
    store = _Store([approved_req])
    monkeypatch.setattr(mod, "get_hitl_store", lambda: store)
    monkeypatch.setattr(mod, "notify", lambda _req: asyncio.sleep(0))
    monkeypatch.setattr(mod.time, "time", _Clock([10.0, 10.1]))
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "uid-1")
    assert asyncio.run(gate.request_approval(action="x", description="y")) is True

    # rejected path
    gate = mod.HITLGate()
    rejected_req = _make_request("a2")
    rejected_req.decision = mod.HITLDecision.REJECTED
    store = _Store([rejected_req])
    monkeypatch.setattr(mod, "get_hitl_store", lambda: store)
    monkeypatch.setattr(mod.time, "time", _Clock([20.0, 20.1]))
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "uid-2")
    assert asyncio.run(gate.request_approval(action="x", description="y")) is False

    # current is none path
    gate = mod.HITLGate()
    store = _Store([None])
    monkeypatch.setattr(mod, "get_hitl_store", lambda: store)
    monkeypatch.setattr(mod.time, "time", _Clock([30.0, 30.1]))
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "uid-3")
    assert asyncio.run(gate.request_approval(action="x", description="y")) is False

    # loop timeout branch and pending->TIMEOUT mutation
    gate = mod.HITLGate()
    gate.timeout = 0
    pending_req = _make_request("a4")
    store = _Store([pending_req, pending_req])
    monkeypatch.setattr(mod, "get_hitl_store", lambda: store)
    monkeypatch.setattr(mod.time, "time", _Clock([40.0, 55.1]))
    monkeypatch.setattr(mod.uuid, "uuid4", lambda: "uid-4")
    assert asyncio.run(gate.request_approval(action="x", description="y")) is False
    assert pending_req.decision == mod.HITLDecision.TIMEOUT
    assert pending_req.decided_at == 55.1


def test_gate_respond_paths(monkeypatch) -> None:
    monkeypatch.setenv("HITL_ENABLED", "true")
    gate = mod.HITLGate()

    async def _fake_notify(_req):
        return None

    monkeypatch.setattr(mod, "notify", _fake_notify)
    monkeypatch.setattr(mod.time, "time", lambda: 555.0)

    class _Store:
        def __init__(self, req):
            self.req = req

        async def get(self, _request_id):
            return self.req

    monkeypatch.setattr(mod, "get_hitl_store", lambda: _Store(None))
    assert asyncio.run(gate.respond("missing", approved=True)) is None

    approved = _make_request("done")
    approved.decision = mod.HITLDecision.APPROVED
    monkeypatch.setattr(mod, "get_hitl_store", lambda: _Store(approved))
    assert asyncio.run(gate.respond("done", approved=False)) is approved

    pending = _make_request("p")
    monkeypatch.setattr(mod, "get_hitl_store", lambda: _Store(pending))
    out = asyncio.run(gate.respond("p", approved=False, decided_by="alice", rejection_reason="no"))
    assert out.decision == mod.HITLDecision.REJECTED
    assert out.decided_at == 555.0
    assert out.decided_by == "alice"
    assert out.rejection_reason == "no"

    pending2 = _make_request("p2")
    monkeypatch.setattr(mod, "get_hitl_store", lambda: _Store(pending2))
    out2 = asyncio.run(gate.respond("p2", approved=True, decided_by="bob", rejection_reason="ignore"))
    assert out2.decision == mod.HITLDecision.APPROVED
    assert out2.rejection_reason == ""


def test_get_hitl_store_returns_singleton_store() -> None:
    assert mod.get_hitl_store() is mod._STORE
