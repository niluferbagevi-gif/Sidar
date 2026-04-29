"""
Sidar Project — Human-in-the-Loop (HITL) Onay Geçidi
Yıkıcı/kritik işlemlerin gerçekleşmeden önce insan onayına sunulmasını sağlar.

Mimari:
  - HITLRequest: onay bekleyen işlem kaydı (in-memory deque + opsiyonel DB)
  - HITLGate: iş mantığı katmanı — request üretir, karar bekler
  - web_server.py endpoint'leri bu modülü kullanır:
      POST /api/hitl/request       → yeni onay isteği oluştur
      POST /api/hitl/respond/{id}  → onayla / reddet
      GET  /api/hitl/pending       → bekleyen istekleri listele

Entegrasyon noktaları:
  - managers/code_manager.py  → dosya silme / üzerine yazma
  - managers/github_manager.py → PR oluşturma, dal silme

Yapılandırma (.env):
  HITL_ENABLED=true
  HITL_TIMEOUT_SECONDS=120
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

# ─── Sabitler ────────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT = 120  # saniye
_MAX_QUEUE_SIZE = 200  # bellekte tutulan maks. istek

# ─── Veri modelleri ───────────────────────────────────────────────────────────


class HITLDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


@dataclass
class HITLRequest:
    """Tek bir onay isteği kaydı."""

    request_id: str
    action: str  # "file_delete", "file_overwrite", "github_pr_create" vb.
    description: str  # Kullanıcıya gösterilecek açıklama
    payload: dict[str, Any]  # İşleme özgü meta-veri (yol, repo adı vb.)
    requested_by: str  # Hangi ajan/yönetici tetikledi
    created_at: float
    expires_at: float
    decision: HITLDecision = HITLDecision.PENDING
    decided_at: float | None = None
    decided_by: str = ""
    rejection_reason: str = ""

    def is_expired(self) -> bool:
        return time.time() > self.expires_at and self.decision == HITLDecision.PENDING

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.value
        return d


# ─── Onay isteği deposu ───────────────────────────────────────────────────────


class _HITLStore:
    """Thread-safe in-memory HITL istek deposu."""

    def __init__(self, max_size: int = _MAX_QUEUE_SIZE) -> None:
        self._requests: deque[HITLRequest] = deque(maxlen=max_size)
        self._index: dict[str, HITLRequest] = {}
        self._lock: asyncio.Lock | None = None

    async def add(self, req: HITLRequest) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            # Eski sürülen eleman index'ten kaldırılır (deque maxlen aşılınca)
            if len(self._requests) == self._requests.maxlen:
                oldest = self._requests[0]
                if oldest.decision == HITLDecision.PENDING:
                    logger.warning(
                        "HITL: Kuyruk dolu, bekleyen istek düşürüldü: %s", oldest.request_id
                    )
                else:
                    logger.warning(
                        "HITL: Kuyruk dolu, kararı verilmiş istek düşürüldü: %s (karar=%s)",
                        oldest.request_id,
                        oldest.decision.value,
                    )
                self._index.pop(oldest.request_id, None)
            self._requests.append(req)
            self._index[req.request_id] = req

    async def get(self, request_id: str) -> HITLRequest | None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            return self._index.get(request_id)

    async def pending(self) -> list[HITLRequest]:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            now = time.time()
            result = []
            for r in self._requests:
                if r.decision == HITLDecision.PENDING:
                    if r.expires_at < now:
                        r.decision = HITLDecision.TIMEOUT
                    else:
                        result.append(r)
            return list(result)

    async def all_recent(self, limit: int = 50) -> list[HITLRequest]:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            return list(self._requests)[-limit:]


_STORE = _HITLStore()


def get_hitl_store() -> _HITLStore:
    return _STORE


# ─── Broadcast hook (WebSocket bildirim) ─────────────────────────────────────

_broadcast_hook: Callable[[dict[str, Any]], Awaitable[None]] | None = None


def set_hitl_broadcast_hook(hook: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
    """
    WebSocket yayın fonksiyonunu kaydet.
    web_server.py başlangıcında çağrılır:
        from core.hitl import set_hitl_broadcast_hook
        set_hitl_broadcast_hook(broadcast_fn)
    """
    global _broadcast_hook
    _broadcast_hook = hook


async def _notify(req: HITLRequest) -> None:
    if _broadcast_hook is None:
        return
    try:
        await _broadcast_hook(
            {
                "type": "hitl_request",
                "data": req.to_dict(),
            }
        )
    except Exception as exc:
        logger.warning("HITL broadcast hatası: %s", exc)
        logging.getLogger().warning("HITL broadcast hatası: %s", exc)


async def notify(req: HITLRequest) -> None:
    """HITL isteğini kayıtlı broadcast hook'a iletir."""
    await _notify(req)


# ─── HITLGate — iş mantığı ───────────────────────────────────────────────────


class HITLGate:
    """
    Kritik işlemler için onay geçidi.

    Kullanım (managers'da):
        gate = get_hitl_gate()
        approved = await gate.request_approval(
            action="file_delete",
            description="Dosya silinecek: /src/main.py",
            payload={"path": "/src/main.py"},
            requested_by="CodeManager",
        )
        if not approved:
            raise PermissionError("İşlem insan onayına takıldı veya reddedildi.")
    """

    def __init__(self) -> None:
        self.enabled = os.getenv("HITL_ENABLED", "false").lower() in ("1", "true", "yes")
        self.timeout = max(
            10, int(os.getenv("HITL_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT)) or _DEFAULT_TIMEOUT)
        )

    async def request_approval(
        self,
        *,
        action: str,
        description: str,
        payload: dict[str, Any] | None = None,
        requested_by: str = "system",
    ) -> bool:
        """
        Onay ister; HITL devre dışıysa doğrudan True döner.

        Returns:
            True  → onaylandı (veya HITL kapalı)
            False → reddedildi veya zaman aşımı
        """
        if not self.enabled:
            return True

        now = time.time()
        req = HITLRequest(
            request_id=str(uuid.uuid4()),
            action=action,
            description=description,
            payload=payload or {},
            requested_by=requested_by,
            created_at=now,
            expires_at=now + self.timeout,
        )

        store = get_hitl_store()
        await store.add(req)
        await notify(req)

        logger.info(
            "HITL onay bekleniyor — action=%s, id=%s, timeout=%ds",
            action,
            req.request_id,
            self.timeout,
        )

        # Onay veya red gelene kadar polling
        deadline = now + self.timeout
        while time.time() < deadline:
            current = await store.get(req.request_id)
            if current is None:
                return False
            if current.decision == HITLDecision.APPROVED:
                logger.info("HITL ONAYLANDI — id=%s", req.request_id)
                return True
            if current.decision in (HITLDecision.REJECTED, HITLDecision.TIMEOUT):
                logger.warning(
                    "HITL REDDEDİLDİ/ZAMAN AŞIMI — id=%s, karar=%s",
                    req.request_id,
                    current.decision.value,
                )
                return False
            await asyncio.sleep(1.0)

        # Zaman aşımı — kaydı güncelle
        current = await store.get(req.request_id)
        if current and current.decision == HITLDecision.PENDING:
            current.decision = HITLDecision.TIMEOUT
            current.decided_at = time.time()
        logger.warning("HITL zaman aşımı — id=%s", req.request_id)
        return False

    async def respond(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str = "operator",
        rejection_reason: str = "",
    ) -> HITLRequest | None:
        """
        Onay veya red kararını kaydet.

        Returns:
            Güncellenen HITLRequest veya None (bulunamadıysa).
        """
        store = get_hitl_store()
        req = await store.get(request_id)
        if req is None:
            return None
        if req.decision != HITLDecision.PENDING:
            return req  # zaten karara bağlanmış

        req.decision = HITLDecision.APPROVED if approved else HITLDecision.REJECTED
        req.decided_at = time.time()
        req.decided_by = decided_by
        req.rejection_reason = rejection_reason if not approved else ""

        await notify(req)
        return req


# ─── Singleton ────────────────────────────────────────────────────────────────

_GATE: HITLGate | None = None


def get_hitl_gate() -> HITLGate:
    """Süreç-geneli tek HITLGate örneğini döndürür."""
    global _GATE
    if _GATE is None:
        _GATE = HITLGate()
    return _GATE
