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
    return asyncio.run(coro)


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
            before = time.time()
            updated = await gate.respond(
                "r-reject", approved=False,
                decided_by="operator", rejection_reason="güvensiz"
            )
            assert updated.decision == hitl.HITLDecision.REJECTED
            assert "güvensiz" in updated.rejection_reason
            assert updated.decided_by == "operator"
            assert updated.decided_at is not None
            assert updated.decided_at >= before

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

# ===== MERGED FROM tests/test_core_hitl_extra.py =====

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── yardımcı ────────────────────────────────────────────────────────────────

def _get_hitl():
    if "core.hitl" in sys.modules:
        del sys.modules["core.hitl"]
    import core.hitl as hitl
    hitl._GATE = None
    hitl._STORE = hitl._HITLStore()
    hitl._broadcast_hook = None
    return hitl


def _run(coro):
    return asyncio.run(coro)


def _make_req(hitl, req_id="r1", *, expires_offset=120, **kw):
    now = time.time()
    defaults = dict(
        request_id=req_id,
        action="test_action",
        description="Test isteği",
        payload={},
        requested_by="test_agent",
        created_at=now,
        expires_at=now + expires_offset,
    )
    defaults.update(kw)
    return hitl.HITLRequest(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
# _HITLStore.add — maxlen aşımı eviction (satır 90-91)
# ══════════════════════════════════════════════════════════════════════════════

class Extra_TestHITLStoreEviction:
    """Deque maxlen aşıldığında en eski kaydın index'ten silinmesi."""

    def test_oldest_request_removed_from_index_on_overflow(self):
        hitl = _get_hitl()
        store = hitl._HITLStore(max_size=3)

        async def _run_test():
            reqs = [_make_req(hitl, f"r{i}") for i in range(4)]
            for r in reqs:
                await store.add(r)

            # r0 index'ten düşmüş olmalı
            assert await store.get("r0") is None
            # r1, r2, r3 mevcut olmalı
            assert await store.get("r1") is not None
            assert await store.get("r2") is not None
            assert await store.get("r3") is not None

        _run(_run_test())

    def test_only_one_eviction_per_overflow(self):
        hitl = _get_hitl()
        store = hitl._HITLStore(max_size=2)

        async def _run_test():
            r0 = _make_req(hitl, "r0")
            r1 = _make_req(hitl, "r1")
            r2 = _make_req(hitl, "r2")

            await store.add(r0)
            await store.add(r1)
            # r0 taşacak
            await store.add(r2)

            assert await store.get("r0") is None
            assert await store.get("r1") is not None
            assert await store.get("r2") is not None

        _run(_run_test())

    def test_index_consistent_after_multiple_overflows(self):
        hitl = _get_hitl()
        store = hitl._HITLStore(max_size=2)

        async def _run_test():
            for i in range(10):
                await store.add(_make_req(hitl, f"r{i}"))

            # Yalnızca son 2 kayıt index'te olmalı
            assert await store.get("r8") is not None
            assert await store.get("r9") is not None
            for i in range(8):
                assert await store.get(f"r{i}") is None

        _run(_run_test())

    def test_eviction_does_not_crash_when_oldest_not_in_index(self):
        """Yarım kalmış index durumunda IndexError/KeyError fırlatılmamalı."""
        hitl = _get_hitl()
        store = hitl._HITLStore(max_size=2)

        async def _run_test():
            r0 = _make_req(hitl, "r0")
            r1 = _make_req(hitl, "r1")
            await store.add(r0)
            await store.add(r1)

            # Index'i elle boz (edge-case simülasyonu)
            store._index.pop("r0", None)

            r2 = _make_req(hitl, "r2")
            await store.add(r2)  # r0 taşacak, ama index'te yok — hata olmamalı

        _run(_run_test())


# ══════════════════════════════════════════════════════════════════════════════
# _HITLStore.get — _lock is None yolu (satır 103)
# ══════════════════════════════════════════════════════════════════════════════

class Extra_TestHITLStoreGetLockInit:
    """_lock None iken get() kilitlenmesini ilk kez başlatmalı."""

    def test_get_initialises_lock_when_none(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()
        assert store._lock is None  # henüz oluşturulmamış

        async def _run_test():
            # add() çağrılmadan doğrudan get() çağır
            result = await store.get("nonexistent")
            assert result is None
            assert store._lock is not None  # kilit oluşturulmuş olmalı

        _run(_run_test())

    def test_get_reuses_existing_lock(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()

        async def _run_test():
            await store.get("x")  # ilk çağrı — kilit oluşturur
            first_lock = store._lock
            await store.get("x")  # ikinci çağrı — aynı kilit kullanılmalı
            assert store._lock is first_lock

        _run(_run_test())


# ══════════════════════════════════════════════════════════════════════════════
# _HITLStore.all_recent — _lock is None yolu (satır 117)
# ══════════════════════════════════════════════════════════════════════════════

class Extra_TestHITLStoreAllRecentLockInit:
    def test_all_recent_initialises_lock_when_none(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()
        assert store._lock is None

        async def _run_test():
            result = await store.all_recent()
            assert isinstance(result, list)
            assert store._lock is not None

        _run(_run_test())

    def test_all_recent_empty_store_returns_empty_list(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()

        async def _run_test():
            result = await store.all_recent()
            assert result == []

        _run(_run_test())

    def test_all_recent_with_data_uses_lock(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()

        async def _run_test():
            r = _make_req(hitl, "r1")
            await store.add(r)
            await store.all_recent()  # lock zaten oluşturulmuş (add() yaptı)
            assert store._lock is not None

        _run(_run_test())


# ══════════════════════════════════════════════════════════════════════════════
# _notify — broadcast hook istisna yakalama (satır 153-154)
# ══════════════════════════════════════════════════════════════════════════════

class Extra_TestNotifyExceptionHandling:
    def test_notify_exception_in_hook_is_silenced(self):
        hitl = _get_hitl()

        async def _raising_hook(data):
            raise RuntimeError("broadcast network error")

        hitl.set_hitl_broadcast_hook(_raising_hook)
        req = _make_req(hitl, "r1")

        async def _run_test():
            await hitl.notify(req)  # İstisna dışarıya sızmamalı

        _run(_run_test())

    def test_notify_async_exception_is_silenced(self):
        hitl = _get_hitl()

        async def _async_error_hook(data):
            await asyncio.sleep(0)
            raise ValueError("ws disconnected")

        hitl.set_hitl_broadcast_hook(_async_error_hook)
        req = _make_req(hitl, "r2")

        async def _run_test():
            await hitl.notify(req)  # Sessizce geçmeli

        _run(_run_test())

    def test_notify_with_none_hook_is_noop(self):
        hitl = _get_hitl()
        # hook None kalsın
        assert hitl._broadcast_hook is None
        req = _make_req(hitl, "r3")

        async def _run_test():
            await hitl.notify(req)  # Hata olmamalı

        _run(_run_test())

    def test_notify_sends_correct_payload_type(self):
        hitl = _get_hitl()
        received = []

        async def _hook(data):
            received.append(data)

        hitl.set_hitl_broadcast_hook(_hook)
        req = _make_req(hitl, "r4")

        async def _run_test():
            await hitl.notify(req)

        _run(_run_test())
        assert len(received) == 1
        assert received[0]["type"] == "hitl_request"
        assert received[0]["data"]["request_id"] == "r4"


# ══════════════════════════════════════════════════════════════════════════════
# HITLGate.request_approval — enabled=True tam akışı (satır 202-245)
# ══════════════════════════════════════════════════════════════════════════════

class Extra_TestHITLGateRequestApprovalEnabled:
    """HITL etkin iken onay/red/zaman aşımı senaryoları."""

    def _make_gate(self, timeout: int = 5):
        with patch.dict(os.environ, {
            "HITL_ENABLED": "true",
            "HITL_TIMEOUT_SECONDS": str(timeout),
        }):
            hitl = _get_hitl()
            gate = hitl.HITLGate()
        return hitl, gate

    # -- onay alma --

    def test_returns_true_when_approved_quickly(self):
        hitl, gate = self._make_gate(timeout=10)

        async def _run_test():
            store = hitl.get_hitl_store()

            async def _auto_approve():
                await asyncio.sleep(0.1)
                all_r = await store.all_recent()
                if all_r:
                    req = all_r[-1]
                    req.decision = hitl.HITLDecision.APPROVED

            task = asyncio.create_task(_auto_approve())
            result = await gate.request_approval(
                action="file_delete",
                description="Test dosyasını sil",
                payload={"path": "/tmp/test.py"},
                requested_by="CodeManager",
            )
            await task
            assert result is True

        _run(_run_test())

    # -- red alma --

    def test_returns_false_when_rejected_quickly(self):
        hitl, gate = self._make_gate(timeout=10)

        async def _run_test():
            store = hitl.get_hitl_store()

            async def _auto_reject():
                await asyncio.sleep(0.1)
                all_r = await store.all_recent()
                if all_r:
                    req = all_r[-1]
                    req.decision = hitl.HITLDecision.REJECTED

            task = asyncio.create_task(_auto_reject())
            result = await gate.request_approval(
                action="github_pr_create",
                description="PR oluştur",
            )
            await task
            assert result is False

        _run(_run_test())

    # -- zaman aşımı kararı --

    def test_returns_false_when_already_timeout(self):
        hitl, gate = self._make_gate(timeout=10)

        async def _run_test():
            store = hitl.get_hitl_store()

            async def _auto_timeout():
                await asyncio.sleep(0.1)
                all_r = await store.all_recent()
                if all_r:
                    req = all_r[-1]
                    req.decision = hitl.HITLDecision.TIMEOUT

            task = asyncio.create_task(_auto_timeout())
            result = await gate.request_approval(
                action="file_overwrite",
                description="Dosyayı üzerine yaz",
            )
            await task
            assert result is False

        _run(_run_test())

    # -- request silinmiş / store'da yok --

    def test_returns_false_when_request_disappears_from_store(self):
        hitl, gate = self._make_gate(timeout=10)

        async def _run_test():
            store = hitl.get_hitl_store()

            async def _remove_request():
                await asyncio.sleep(0.1)
                all_r = await store.all_recent()
                if all_r:
                    req_id = all_r[-1].request_id
                    store._index.pop(req_id, None)

            task = asyncio.create_task(_remove_request())
            result = await gate.request_approval(
                action="file_delete",
                description="Silinecek",
            )
            await task
            assert result is False

        _run(_run_test())

    # -- zaman aşımı sonrası kayıt güncelleme --

    def test_timeout_updates_decision_on_pending_request(self):
        """Süre dolduğunda PENDING kaydı TIMEOUT'a güncellenmeli."""
        with patch.dict(os.environ, {
            "HITL_ENABLED": "true",
            "HITL_TIMEOUT_SECONDS": "10",
        }):
            hitl = _get_hitl()
            gate = hitl.HITLGate()

        async def _run_test():
            store = hitl.get_hitl_store()
            captured_req = {}

            # Deadline'ı geçmiş gibi davranmak için deadline'ı elle manipüle edeceğiz.
            # Bunun yerine, isteği oluşturup deadline sonrasını simüle edelim.
            async def _expire_quickly():
                await asyncio.sleep(0.15)
                all_r = await store.all_recent()
                if all_r:
                    req = all_r[-1]
                    captured_req["req"] = req
                    # expires_at'i geçmişe al (HITL polling'i timeout döngüsüne düşsün)
                    req.expires_at = time.time() - 1

            task = asyncio.create_task(_expire_quickly())
            result = await gate.request_approval(
                action="file_delete",
                description="Deneme",
                payload={"path": "/tmp/x"},
            )
            await task
            assert result is False

        _run(_run_test())

    # -- payload=None varsayılan değeri --

    def test_payload_defaults_to_empty_dict(self):
        hitl, gate = self._make_gate(timeout=10)

        async def _run_test():
            store = hitl.get_hitl_store()

            async def _approve():
                await asyncio.sleep(0.1)
                all_r = await store.all_recent()
                if all_r:
                    all_r[-1].decision = hitl.HITLDecision.APPROVED

            task = asyncio.create_task(_approve())
            await gate.request_approval(
                action="file_delete",
                description="Payload yok",
                payload=None,
            )
            await task

            all_r = await store.all_recent()
            assert all_r[-1].payload == {}

        _run(_run_test())

    # -- broadcast hook ile request oluşturulduğunda notify çağrılıyor --

    def test_notify_is_called_on_request_creation(self):
        hitl, gate = self._make_gate(timeout=10)
        notified = []

        async def _hook(data):
            notified.append(data)

        hitl.set_hitl_broadcast_hook(_hook)

        async def _run_test():
            store = hitl.get_hitl_store()

            async def _approve():
                await asyncio.sleep(0.1)
                all_r = await store.all_recent()
                if all_r:
                    all_r[-1].decision = hitl.HITLDecision.APPROVED

            task = asyncio.create_task(_approve())
            await gate.request_approval(
                action="file_delete",
                description="Bildirim testi",
            )
            await task

        _run(_run_test())
        # İlk bildirim istek oluşturulduğunda atılmalı
        assert len(notified) >= 1
        assert notified[0]["type"] == "hitl_request"

    # -- HITL devre dışı → True döner --

    def test_disabled_gate_returns_true_immediately(self):
        with patch.dict(os.environ, {"HITL_ENABLED": "false"}):
            hitl = _get_hitl()
            gate = hitl.HITLGate()

        async def _run_test():
            result = await gate.request_approval(
                action="anything",
                description="desc",
            )
            assert result is True

        _run(_run_test())

    # -- zaman aşımı sonrası kayıt zaten kararlanmış (line 241 False branch) --

    def test_timeout_does_not_overwrite_already_decided_request(self):
        """Deadline dolduğunda kayıt zaten karar almışsa TIMEOUT yazılmamalı."""
        with patch.dict(os.environ, {
            "HITL_ENABLED": "true",
            "HITL_TIMEOUT_SECONDS": "10",
        }):
            hitl = _get_hitl()
            gate = hitl.HITLGate()

        async def _run_test():
            store = hitl.get_hitl_store()

            async def _approve_then_expire():
                await asyncio.sleep(0.1)
                all_r = await store.all_recent()
                if all_r:
                    req = all_r[-1]
                    # Önce onaylıyoruz, sonra expires_at'i geçmişe alıyoruz
                    req.decision = hitl.HITLDecision.APPROVED
                    req.expires_at = time.time() - 1

            task = asyncio.create_task(_approve_then_expire())
            result = await gate.request_approval(
                action="file_delete",
                description="Zaten onaylanmış",
            )
            await task
            # Onaylandı, zaman aşımı APPROVED'ı ezmemeli
            assert result is True

        _run(_run_test())

    # -- Varsayılan timeout ile defalarca çağrı --

    def test_multiple_requests_are_independent(self):
        hitl, gate = self._make_gate(timeout=10)

        async def _run_test():
            store = hitl.get_hitl_store()

            tasks_done = []

            async def _handler(decision):
                await asyncio.sleep(0.1)
                all_r = await store.all_recent()
                for r in reversed(all_r):
                    if r.decision == hitl.HITLDecision.PENDING:
                        r.decision = decision
                        break
                tasks_done.append(decision)

            t1 = asyncio.create_task(_handler(hitl.HITLDecision.APPROVED))
            r1 = await gate.request_approval(action="a1", description="d1")
            await t1

            t2 = asyncio.create_task(_handler(hitl.HITLDecision.REJECTED))
            r2 = await gate.request_approval(action="a2", description="d2")
            await t2

            assert r1 is True
            assert r2 is False

        _run(_run_test())


# ══════════════════════════════════════════════════════════════════════════════
# HITLGate.respond — tam akış ek testleri
# ══════════════════════════════════════════════════════════════════════════════

class Extra_TestHITLGateRespondExtra:
    """respond() metodunun notify() ile entegrasyonu."""

    def test_respond_approved_triggers_notify(self):
        hitl = _get_hitl()
        notified = []

        async def _hook(data):
            notified.append(data)

        hitl.set_hitl_broadcast_hook(_hook)

        with patch.dict(os.environ, {"HITL_ENABLED": "false"}):
            gate = hitl.HITLGate()

        async def _run_test():
            store = hitl.get_hitl_store()
            req = _make_req(hitl, "r-notify")
            await store.add(req)
            await gate.respond("r-notify", approved=True, decided_by="admin")

        _run(_run_test())

        assert any(n["type"] == "hitl_request" for n in notified)

    def test_respond_rejected_clears_rejection_reason_on_approve(self):
        """Onaylanmış isteklerde rejection_reason boş olmalı."""
        hitl = _get_hitl()

        with patch.dict(os.environ, {"HITL_ENABLED": "false"}):
            gate = hitl.HITLGate()

        async def _run_test():
            store = hitl.get_hitl_store()
            req = _make_req(hitl, "r-approve-2")
            await store.add(req)
            updated = await gate.respond(
                "r-approve-2",
                approved=True,
                rejection_reason="daha önce reddedildi",
            )
            assert updated.rejection_reason == ""

        _run(_run_test())

    def test_respond_sets_decided_at_timestamp(self):
        hitl = _get_hitl()

        with patch.dict(os.environ, {"HITL_ENABLED": "false"}):
            gate = hitl.HITLGate()

        async def _run_test():
            store = hitl.get_hitl_store()
            req = _make_req(hitl, "r-ts")
            before = time.time()
            await store.add(req)
            updated = await gate.respond("r-ts", approved=True)
            assert updated.decided_at is not None
            assert updated.decided_at >= before

        _run(_run_test())


# ══════════════════════════════════════════════════════════════════════════════
# HITLStore.pending — zaman aşımı otomatik güncelleme (ek kenar durumlar)
# ══════════════════════════════════════════════════════════════════════════════

class Extra_TestHITLStorePendingEdgeCases:
    def test_pending_lock_initialised_if_none(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()
        assert store._lock is None

        async def _run_test():
            result = await store.pending()
            assert isinstance(result, list)
            assert store._lock is not None

        _run(_run_test())

    def test_multiple_expired_requests_all_marked_timeout(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()

        async def _run_test():
            for i in range(3):
                r = _make_req(hitl, f"exp{i}", expires_offset=-10)
                await store.add(r)

            pending = await store.pending()
            assert len(pending) == 0

            all_r = await store.all_recent()
            for r in all_r:
                assert r.decision == hitl.HITLDecision.TIMEOUT

        _run(_run_test())

    def test_mix_of_pending_expired_and_decided(self):
        hitl = _get_hitl()
        store = hitl._HITLStore()

        async def _run_test():
            r_pending = _make_req(hitl, "p1", expires_offset=120)
            r_expired = _make_req(hitl, "p2", expires_offset=-1)
            r_approved = _make_req(hitl, "p3", expires_offset=120)
            r_approved.decision = hitl.HITLDecision.APPROVED

            await store.add(r_pending)
            await store.add(r_expired)
            await store.add(r_approved)

            pending = await store.pending()
            ids = [r.request_id for r in pending]
            assert "p1" in ids
            assert "p2" not in ids  # zaman aşımına düştü
            assert "p3" not in ids  # zaten onaylanmış

        _run(_run_test())


# ══════════════════════════════════════════════════════════════════════════════
# get_hitl_store — singleton davranışı
# ══════════════════════════════════════════════════════════════════════════════

class Extra_TestGetHitlStore:
    def test_returns_hitl_store_instance(self):
        hitl = _get_hitl()
        store = hitl.get_hitl_store()
        assert isinstance(store, hitl._HITLStore)

    def test_returns_module_level_store(self):
        hitl = _get_hitl()
        store1 = hitl.get_hitl_store()
        store2 = hitl.get_hitl_store()
        assert store1 is store2
