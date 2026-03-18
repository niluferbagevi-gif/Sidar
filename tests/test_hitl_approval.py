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
    return asyncio.get_event_loop().run_until_complete(coro)


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


# ─── Singleton ────────────────────────────────────────────────────────────────

def test_get_hitl_gate_singleton():
    g1 = get_hitl_gate()
    g2 = get_hitl_gate()
    assert g1 is g2


def test_get_hitl_store_singleton():
    s1 = get_hitl_store()
    s2 = get_hitl_store()
    assert s1 is s2