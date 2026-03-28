"""
core/hitl.py için birim testleri.
HITLDecision, HITLRequest, _HITLStore, HITLGate ve get_hitl_gate
fonksiyonlarını kapsar.
"""
from __future__ import annotations

import os
import sys
import time
import asyncio
from unittest.mock import patch


def _get_hitl():
    if "core.hitl" in sys.modules:
        del sys.modules["core.hitl"]
    import core.hitl as hitl
    # Singleton'ları sıfırla
    hitl._GATE = None
    hitl._STORE = hitl._HITLStore()
    hitl._broadcast_hook = None
    return hitl


# ══════════════════════════════════════════════════════════════
# HITLDecision enum
# ══════════════════════════════════════════════════════════════

class TestHITLDecision:
    def test_values(self):
        hitl = _get_hitl()
        assert hitl.HITLDecision.PENDING.value == "pending"
        assert hitl.HITLDecision.APPROVED.value == "approved"
        assert hitl.HITLDecision.REJECTED.value == "rejected"
        assert hitl.HITLDecision.TIMEOUT.value == "timeout"


# ══════════════════════════════════════════════════════════════
# HITLRequest
# ══════════════════════════════════════════════════════════════

class TestHITLRequest:
    def _make(self, **kwargs):
        hitl = _get_hitl()
        now = time.time()
        defaults = dict(
            request_id="req-1",
            action="file_delete",
            description="Dosyayı sil",
            payload={"path": "/foo"},
            requested_by="agent",
            created_at=now,
            expires_at=now + 120,
        )
        defaults.update(kwargs)
        return hitl.HITLRequest(**defaults), hitl

    def test_initial_decision_is_pending(self):
        req, hitl = self._make()
        assert req.decision == hitl.HITLDecision.PENDING

    def test_not_expired_when_fresh(self):
        req, _ = self._make()
        assert req.is_expired() is False

    def test_expired_when_past_deadline(self):
        req, hitl = self._make(expires_at=time.time() - 1)
        assert req.is_expired() is True

    def test_not_expired_when_already_decided(self):
        req, hitl = self._make(expires_at=time.time() - 1)
        req.decision = hitl.HITLDecision.APPROVED
        assert req.is_expired() is False  # only PENDING can expire

    def test_to_dict_contains_required_keys(self):
        req, _ = self._make()
        d = req.to_dict()
        for key in ("request_id", "action", "description", "payload", "decision"):
            assert key in d

    def test_to_dict_decision_is_string(self):
        req, _ = self._make()
        d = req.to_dict()
        assert isinstance(d["decision"], str)
        assert d["decision"] == "pending"


# ══════════════════════════════════════════════════════════════
# _HITLStore
# ══════════════════════════════════════════════════════════════

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestHITLStore:
    def _make_req(self, req_id="r1", *, expires_offset=120):
        hitl = _get_hitl()
        now = time.time()
        return hitl.HITLRequest(
            request_id=req_id,
            action="test_action",
            description="Test",
            payload={},
            requested_by="test",
            created_at=now,
            expires_at=now + expires_offset,
        ), hitl

    def test_add_and_get(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()
        req, _ = self._make_req()

        async def _run_test():
            await store.add(req)
            found = await store.get("r1")
            assert found is req

        _run(_run_test())

    def test_get_nonexistent_returns_none(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()

        async def _run_test():
            result = await store.get("nonexistent")
            assert result is None

        _run(_run_test())

    def test_pending_returns_only_pending(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()
        req1, _ = self._make_req("r1")
        req2, _ = self._make_req("r2")
        req2.decision = hitl.HITLDecision.APPROVED

        async def _run_test():
            await store.add(req1)
            await store.add(req2)
            pending = await store.pending()
            assert len(pending) == 1
            assert pending[0].request_id == "r1"

        _run(_run_test())

    def test_expired_request_set_to_timeout_in_pending(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()
        req, _ = self._make_req("r1", expires_offset=-1)  # already expired

        async def _run_test():
            await store.add(req)
            pending = await store.pending()
            assert req.decision == hitl.HITLDecision.TIMEOUT
            assert req not in pending

        _run(_run_test())

    def test_all_recent_returns_list(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()
        req, _ = self._make_req("r1")

        async def _run_test():
            await store.add(req)
            all_r = await store.all_recent()
            assert len(all_r) == 1

        _run(_run_test())

    def test_all_recent_respects_limit(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()

        async def _run_test():
            for i in range(60):
                now = time.time()
                r = hitl.HITLRequest(
                    request_id=f"r{i}", action="a", description="d",
                    payload={}, requested_by="x",
                    created_at=now, expires_at=now + 120,
                )
                await store.add(r)
            all_r = await store.all_recent(limit=10)
            assert len(all_r) == 10

        _run(_run_test())


# ══════════════════════════════════════════════════════════════
# set_hitl_broadcast_hook / notify
# ══════════════════════════════════════════════════════════════

class TestBroadcastHook:
    def test_set_broadcast_hook(self):
        hitl = _get_hitl()
        calls = []

        async def hook(data):
            calls.append(data)

        hitl.set_hitl_broadcast_hook(hook)
        assert hitl._broadcast_hook is hook

    def test_notify_calls_hook(self):
        hitl = _get_hitl()
        calls = []

        async def hook(data):
            calls.append(data)

        hitl.set_hitl_broadcast_hook(hook)
        now = time.time()
        req = hitl.HITLRequest(
            request_id="r1", action="a", description="d",
            payload={}, requested_by="x",
            created_at=now, expires_at=now + 120,
        )

        async def _run_test():
            await hitl.notify(req)

        _run(_run_test())
        assert len(calls) == 1
        assert calls[0]["type"] == "hitl_request"

    def test_notify_without_hook_is_silent(self):
        hitl = _get_hitl()
        now = time.time()
        req = hitl.HITLRequest(
            request_id="r1", action="a", description="d",
            payload={}, requested_by="x",
            created_at=now, expires_at=now + 120,
        )

        async def _run_test():
            await hitl.notify(req)  # should not raise

        _run(_run_test())


# ══════════════════════════════════════════════════════════════
# HITLGate — disabled
# ══════════════════════════════════════════════════════════════

class TestHITLGateDisabled:
    def test_disabled_request_approval_returns_true(self):
        with patch.dict(os.environ, {"HITL_ENABLED": "false"}):
            hitl = _get_hitl()
            gate = hitl.HITLGate()

        async def _run_test():
            result = await gate.request_approval(action="file_delete", description="test")
            assert result is True

        _run(_run_test())

    def test_enabled_flag_false_by_default(self):
        with patch.dict(os.environ, {"HITL_ENABLED": "false"}):
            hitl = _get_hitl()
            gate = hitl.HITLGate()
        assert gate.enabled is False

    def test_enabled_flag_true_when_set(self):
        with patch.dict(os.environ, {"HITL_ENABLED": "true"}):
            hitl = _get_hitl()
            gate = hitl.HITLGate()
        assert gate.enabled is True

    def test_timeout_default_value(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HITL_TIMEOUT_SECONDS", None)
            hitl = _get_hitl()
            gate = hitl.HITLGate()
        assert gate.timeout == 120


# ══════════════════════════════════════════════════════════════
# HITLGate.respond
# ══════════════════════════════════════════════════════════════

class TestHITLGateRespond:
    def test_respond_approved(self):
        hitl = _get_hitl()
        store = hitl.get_hitl_store()
        now = time.time()
        req = hitl.HITLRequest(
            request_id="r-approve", action="a", description="d",
            payload={}, requested_by="x",
            created_at=now, expires_at=now + 120,
        )

        with patch.dict(os.environ, {"HITL_ENABLED": "false"}):
            gate = hitl.HITLGate()

        async def _run_test():
            await store.add(req)
            updated = await gate.respond("r-approve", approved=True, decided_by="admin")
            assert updated.decision == hitl.HITLDecision.APPROVED
            assert updated.decided_by == "admin"

        _run(_run_test())

    def test_respond_rejected_with_reason(self):
        hitl = _get_hitl()
        store = hitl.get_hitl_store()
        now = time.time()
        req = hitl.HITLRequest(
            request_id="r-reject", action="a", description="d",
            payload={}, requested_by="x",
            created_at=now, expires_at=now + 120,
        )

        with patch.dict(os.environ, {"HITL_ENABLED": "false"}):
            gate = hitl.HITLGate()

        async def _run_test():
            await store.add(req)
            updated = await gate.respond(
                "r-reject", approved=False,
                decided_by="operator", rejection_reason="güvensiz"
            )
            assert updated.decision == hitl.HITLDecision.REJECTED
            assert "güvensiz" in updated.rejection_reason

        _run(_run_test())

    def test_respond_nonexistent_returns_none(self):
        hitl = _get_hitl()
        with patch.dict(os.environ, {"HITL_ENABLED": "false"}):
            gate = hitl.HITLGate()

        async def _run_test():
            result = await gate.respond("nonexistent", approved=True)
            assert result is None

        _run(_run_test())

    def test_respond_already_decided_returns_req_unchanged(self):
        hitl = _get_hitl()
        store = hitl.get_hitl_store()
        now = time.time()
        req = hitl.HITLRequest(
            request_id="r-done", action="a", description="d",
            payload={}, requested_by="x",
            created_at=now, expires_at=now + 120,
            decision=hitl.HITLDecision.APPROVED,
        )

        with patch.dict(os.environ, {"HITL_ENABLED": "false"}):
            gate = hitl.HITLGate()

        async def _run_test():
            await store.add(req)
            result = await gate.respond("r-done", approved=False)
            # Should still be approved (already decided)
            assert result.decision == hitl.HITLDecision.APPROVED

        _run(_run_test())


# ══════════════════════════════════════════════════════════════
# get_hitl_gate singleton
# ══════════════════════════════════════════════════════════════

class TestGetHitlGate:
    def test_returns_hitlgate_instance(self):
        hitl = _get_hitl()
        gate = hitl.get_hitl_gate()
        assert isinstance(gate, hitl.HITLGate)

    def test_same_instance_on_repeated_calls(self):
        hitl = _get_hitl()
        g1 = hitl.get_hitl_gate()
        g2 = hitl.get_hitl_gate()
        assert g1 is g2
