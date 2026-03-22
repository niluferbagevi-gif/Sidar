"""
Tests for core/hitl.py — Human-in-the-Loop onay geçidi modülü.
"""
import asyncio
import time
import pytest

from core.hitl import (
    HITLDecision,
    HITLGate,
    HITLRequest,
    _HITLStore,
    get_hitl_gate,
    get_hitl_store,
)


def _run(coro):
    """Async coroutine'i senkron olarak çalıştır."""
    return asyncio.run(coro)


# ─── HITLRequest ─────────────────────────────────────────────────────────────

class TestHITLRequest:
    def _make_request(self, offset: float = 60.0, decision=HITLDecision.PENDING) -> HITLRequest:
        now = time.time()
        r = HITLRequest(
            request_id="test-id",
            action="file_delete",
            description="Test dosyası siliniyor",
            payload={"path": "/tmp/test.py"},
            requested_by="CodeManager",
            created_at=now,
            expires_at=now + offset,
        )
        r.decision = decision
        return r

    def test_not_expired_when_fresh(self):
        r = self._make_request(offset=60.0)
        assert r.is_expired() is False

    def test_expired_past_deadline(self):
        r = self._make_request(offset=-1.0)  # deadline geçmiş
        assert r.is_expired() is True

    def test_decided_request_not_expired_even_past_deadline(self):
        r = self._make_request(offset=-1.0, decision=HITLDecision.APPROVED)
        # Karar verilmiş; is_expired yalnızca PENDING için True döner
        assert r.is_expired() is False

    def test_to_dict_has_required_keys(self):
        r = self._make_request()
        d = r.to_dict()
        for key in ("request_id", "action", "description", "payload", "decision"):
            assert key in d
        assert d["decision"] == "pending"


# ─── _HITLStore ───────────────────────────────────────────────────────────────

class TestHITLStore:
    def test_add_and_get(self):
        async def _inner():
            store = _HITLStore()
            now = time.time()
            req = HITLRequest(
                request_id="abc-123",
                action="pr_create",
                description="PR oluşturma",
                payload={},
                requested_by="GitHubManager",
                created_at=now,
                expires_at=now + 30,
            )
            await store.add(req)
            found = await store.get("abc-123")
            assert found is not None
            assert found.action == "pr_create"
        _run(_inner())

    def test_pending_list(self):
        async def _inner():
            store = _HITLStore()
            now = time.time()
            for i in range(3):
                r = HITLRequest(
                    request_id=f"id-{i}",
                    action="action",
                    description="desc",
                    payload={},
                    requested_by="test",
                    created_at=now,
                    expires_at=now + 60,
                )
                await store.add(r)
            pending = await store.pending()
            assert len(pending) == 3
        _run(_inner())

    def test_expired_removed_from_pending(self):
        async def _inner():
            store = _HITLStore()
            now = time.time()
            req = HITLRequest(
                request_id="exp-id",
                action="delete",
                description="desc",
                payload={},
                requested_by="test",
                created_at=now - 200,
                expires_at=now - 100,  # geçmişte
            )
            await store.add(req)
            pending = await store.pending()
            assert all(r.request_id != "exp-id" for r in pending)
        _run(_inner())

    def test_get_returns_none_for_missing(self):
        async def _inner():
            store = _HITLStore()
            result = await store.get("nonexistent")
            assert result is None
        _run(_inner())

    def test_pending_initializes_lock_when_store_is_fresh(self):
        async def _inner():
            store = _HITLStore()
            assert store._lock is None
            assert await store.pending() == []
            assert store._lock is not None

        _run(_inner())

    def test_all_recent_initializes_lock_when_store_is_fresh(self):
        async def _inner():
            store = _HITLStore()
            assert store._lock is None
            assert await store.all_recent() == []
            assert store._lock is not None

        _run(_inner())


# ─── HITLGate ─────────────────────────────────────────────────────────────────

class TestHITLGate:
    def test_disabled_gate_always_approves(self):
        async def _inner():
            gate = HITLGate()
            gate.enabled = False
            result = await gate.request_approval(
                action="file_delete",
                description="Test",
                payload={},
                requested_by="test",
            )
            assert result is True
        _run(_inner())

    def test_respond_reject(self):
        async def _inner():
            gate = HITLGate()
            gate.enabled = True
            store = get_hitl_store()
            now = time.time()
            req = HITLRequest(
                request_id="rej-id-unique",
                action="branch_delete",
                description="Dal sil",
                payload={},
                requested_by="GitHub",
                created_at=now,
                expires_at=now + 60,
            )
            await store.add(req)
            updated = await gate.respond(
                "rej-id-unique", approved=False, decided_by="operator",
                rejection_reason="İzin verilmedi"
            )
            assert updated is not None
            assert updated.decision == HITLDecision.REJECTED
            assert updated.rejection_reason == "İzin verilmedi"
        _run(_inner())

    def test_respond_approve(self):
        async def _inner():
            gate = HITLGate()
            gate.enabled = True
            store = get_hitl_store()
            now = time.time()
            req = HITLRequest(
                request_id="approve-id-unique",
                action="overwrite",
                description="Dosya üzerine yaz",
                payload={},
                requested_by="test",
                created_at=now,
                expires_at=now + 60,
            )
            await store.add(req)
            updated = await gate.respond("approve-id-unique", approved=True, decided_by="admin")
            assert updated is not None
            assert updated.decision == HITLDecision.APPROVED
            assert updated.decided_by == "admin"
        _run(_inner())

    def test_respond_not_found(self):
        async def _inner():
            gate = HITLGate()
            result = await gate.respond("ghost-id", approved=True)
            assert result is None
        _run(_inner())


    def test_request_approval_times_out_and_marks_request(self, monkeypatch):
        async def _inner():
            import core.hitl as hitl_mod

            store = _HITLStore()
            monkeypatch.setattr(hitl_mod, "get_hitl_store", lambda: store)

            gate = HITLGate()
            gate.enabled = True
            gate.timeout = 10

            clock = {"now": 1000.0}
            notified = []

            async def _notify(req):
                notified.append(req.request_id)

            async def _sleep(seconds):
                clock["now"] += seconds + 10

            monkeypatch.setattr(hitl_mod, "notify", _notify)
            monkeypatch.setattr(time, "time", lambda: clock["now"])
            monkeypatch.setattr(asyncio, "sleep", _sleep)

            approved = await gate.request_approval(
                action="dangerous_write",
                description="Kritik dosya değişecek",
                payload={"path": "/tmp/demo.py"},
                requested_by="CodeManager",
            )

            assert approved is False
            assert len(notified) == 1

            req = store._requests[-1]
            assert req.decision == HITLDecision.TIMEOUT
            assert req.decided_at == clock["now"]
            assert req.requested_by == "CodeManager"

        _run(_inner())


# ─── Singleton ────────────────────────────────────────────────────────────────

def test_get_hitl_gate_singleton():
    g1 = get_hitl_gate()
    g2 = get_hitl_gate()
    assert g1 is g2


def test_get_hitl_store_singleton():
    s1 = get_hitl_store()
    s2 = get_hitl_store()
    assert s1 is s2


def test_set_hitl_broadcast_hook_and_notify_success():
    import core.hitl as hitl_mod

    async def _inner():
        seen = []
        now = time.time()
        req = HITLRequest(
            request_id="notify-ok",
            action="overwrite",
            description="Hook bildirimi",
            payload={"path": "/tmp/file.py"},
            requested_by="tester",
            created_at=now,
            expires_at=now + 30,
        )

        async def _hook(payload):
            seen.append(payload)

        hitl_mod.set_hitl_broadcast_hook(_hook)
        await hitl_mod.notify(req)

        assert seen == [{"type": "hitl_request", "data": req.to_dict()}]

        hitl_mod.set_hitl_broadcast_hook(None)

    _run(_inner())


def test_notify_swallows_broadcast_errors(caplog):
    import core.hitl as hitl_mod

    async def _inner():
        now = time.time()
        req = HITLRequest(
            request_id="notify-fail",
            action="overwrite",
            description="Hook hatası",
            payload={},
            requested_by="tester",
            created_at=now,
            expires_at=now + 30,
        )

        async def _hook(_payload):
            raise RuntimeError("boom")

        hitl_mod.set_hitl_broadcast_hook(_hook)
        await hitl_mod.notify(req)
        hitl_mod.set_hitl_broadcast_hook(None)

    with caplog.at_level("DEBUG"):
        _run(_inner())

    assert "HITL broadcast hatası" in caplog.text


def test_store_evicts_oldest_entry_when_capacity_is_reached():
    async def _inner():
        store = _HITLStore(max_size=2)
        now = time.time()
        for idx in range(3):
            await store.add(
                HITLRequest(
                    request_id=f"req-{idx}",
                    action="action",
                    description=f"desc-{idx}",
                    payload={},
                    requested_by="tester",
                    created_at=now + idx,
                    expires_at=now + 60 + idx,
                )
            )

        assert await store.get("req-0") is None
        assert (await store.get("req-1")).request_id == "req-1"
        assert (await store.get("req-2")).request_id == "req-2"
        assert [r.request_id for r in await store.all_recent(limit=5)] == ["req-1", "req-2"]

    _run(_inner())


def test_request_approval_returns_true_when_request_is_approved(monkeypatch):
    async def _inner():
        import core.hitl as hitl_mod

        store = _HITLStore()
        monkeypatch.setattr(hitl_mod, "get_hitl_store", lambda: store)

        gate = HITLGate()
        gate.enabled = True
        gate.timeout = 10

        clock = {"now": 2000.0}

        async def _notify(_req):
            return None

        async def _sleep(_seconds):
            req = store._requests[-1]
            req.decision = HITLDecision.APPROVED
            req.decided_by = "operator"
            clock["now"] += 1

        monkeypatch.setattr(hitl_mod, "notify", _notify)
        monkeypatch.setattr(time, "time", lambda: clock["now"])
        monkeypatch.setattr(asyncio, "sleep", _sleep)

        approved = await gate.request_approval(
            action="dangerous_write",
            description="Kritik dosya değişecek",
            payload={"path": "/tmp/demo.py"},
            requested_by="CodeManager",
        )

        assert approved is True
        req = store._requests[-1]
        assert req.decision == HITLDecision.APPROVED
        assert req.decided_by == "operator"

    _run(_inner())


def test_request_approval_returns_false_when_request_disappears(monkeypatch):
    async def _inner():
        import core.hitl as hitl_mod

        store = _HITLStore()
        monkeypatch.setattr(hitl_mod, "get_hitl_store", lambda: store)

        gate = HITLGate()
        gate.enabled = True
        gate.timeout = 10

        clock = {"now": 3000.0}

        async def _notify(_req):
            return None

        async def _sleep(_seconds):
            req = store._requests[-1]
            store._index.pop(req.request_id, None)
            clock["now"] += 1

        monkeypatch.setattr(hitl_mod, "notify", _notify)
        monkeypatch.setattr(time, "time", lambda: clock["now"])
        monkeypatch.setattr(asyncio, "sleep", _sleep)

        approved = await gate.request_approval(
            action="dangerous_write",
            description="İstek kaybolursa reddedilmeli",
            payload={},
            requested_by="CodeManager",
        )

        assert approved is False

    _run(_inner())


def test_request_approval_returns_false_when_request_is_marked_timeout_before_deadline(monkeypatch, caplog):
    async def _inner():
        import core.hitl as hitl_mod

        store = _HITLStore()
        monkeypatch.setattr(hitl_mod, "get_hitl_store", lambda: store)

        gate = HITLGate()
        gate.enabled = True
        gate.timeout = 10

        clock = {"now": 5000.0}

        async def _notify(_req):
            return None

        async def _sleep(_seconds):
            req = store._requests[-1]
            req.decision = HITLDecision.TIMEOUT
            req.decided_at = clock["now"] + 1
            clock["now"] += 1

        monkeypatch.setattr(hitl_mod, "notify", _notify)
        monkeypatch.setattr(time, "time", lambda: clock["now"])
        monkeypatch.setattr(asyncio, "sleep", _sleep)

        approved = await gate.request_approval(
            action="dangerous_write",
            description="Onay verilmezse timeout kararı dönmeli",
            payload={},
            requested_by="CodeManager",
        )

        assert approved is False
        assert store._requests[-1].decision == HITLDecision.TIMEOUT

    with caplog.at_level("WARNING"):
        _run(_inner())

    assert "HITL REDDEDİLDİ/ZAMAN AŞIMI" in caplog.text


def test_request_approval_returns_false_when_request_is_rejected(monkeypatch):
    async def _inner():
        import core.hitl as hitl_mod

        store = _HITLStore()
        monkeypatch.setattr(hitl_mod, "get_hitl_store", lambda: store)

        gate = HITLGate()
        gate.enabled = True
        gate.timeout = 10

        clock = {"now": 4000.0}

        async def _notify(_req):
            return None

        async def _sleep(_seconds):
            req = store._requests[-1]
            req.decision = HITLDecision.REJECTED
            req.rejection_reason = "manuel red"
            clock["now"] += 1

        monkeypatch.setattr(hitl_mod, "notify", _notify)
        monkeypatch.setattr(time, "time", lambda: clock["now"])
        monkeypatch.setattr(asyncio, "sleep", _sleep)

        approved = await gate.request_approval(
            action="dangerous_write",
            description="Red akışı test ediliyor",
            payload={},
            requested_by="CodeManager",
        )

        assert approved is False
        assert store._requests[-1].decision == HITLDecision.REJECTED

    _run(_inner())


def test_respond_returns_existing_request_when_already_decided():
    async def _inner():
        gate = HITLGate()
        store = get_hitl_store()
        now = time.time()
        req = HITLRequest(
            request_id="decided-id-unique",
            action="overwrite",
            description="Zaten onaylandı",
            payload={},
            requested_by="test",
            created_at=now,
            expires_at=now + 60,
            decision=HITLDecision.APPROVED,
            decided_at=now,
            decided_by="admin",
        )
        await store.add(req)

        updated = await gate.respond("decided-id-unique", approved=False, decided_by="operator")

        assert updated is req
        assert updated.decision == HITLDecision.APPROVED
        assert updated.decided_by == "admin"

    _run(_inner())