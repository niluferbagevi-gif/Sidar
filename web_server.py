"""
Sidar Project - Web Arayüzü Sunucusu
FastAPI + WebSocket ile asenkron (async) çift yönlü akış destekli chat arayüzü.

Başlatmak için:
    python web_server.py
    python web_server.py --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import base64
import builtins
import contextlib
import hashlib
import hmac
import importlib
import importlib.util
import inspect
import json
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jwt
import anyio

_ANYIO_CLOSED = anyio.ClosedResourceError

import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi import Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from agent.base_agent import BaseAgent
try:
    from agent.core.contracts import (
        ActionFeedback,
        ExternalTrigger,
        FederationTaskEnvelope,
        FederationTaskResult,
        LEGACY_FEDERATION_PROTOCOL_V1,
        derive_correlation_id,
        normalize_federation_protocol,
    )
except Exception:  # pragma: no cover - testlerde modül enjeksiyonu bozulduğunda güvenli fallback
    LEGACY_FEDERATION_PROTOCOL_V1 = "v1"

    @dataclass
    class ActionFeedback:
        trigger_id: str
        action: str
        status: str
        result_summary: str
        correlation_id: str | None = None
        protocol: str = LEGACY_FEDERATION_PROTOCOL_V1

    @dataclass
    class ExternalTrigger:
        trigger_id: str
        event_type: str
        source: str
        payload: dict[str, Any]
        correlation_id: str | None = None
        protocol: str = LEGACY_FEDERATION_PROTOCOL_V1

    @dataclass
    class FederationTaskEnvelope:
        task_id: str
        source_role: str
        target_role: str
        prompt: str
        correlation_id: str | None = None
        protocol: str = LEGACY_FEDERATION_PROTOCOL_V1

    @dataclass
    class FederationTaskResult:
        task_id: str
        source_role: str
        target_role: str
        output: str
        status: str = "completed"
        correlation_id: str | None = None
        protocol: str = LEGACY_FEDERATION_PROTOCOL_V1

    def normalize_federation_protocol(protocol: str | None) -> str:
        return (protocol or LEGACY_FEDERATION_PROTOCOL_V1).strip() or LEGACY_FEDERATION_PROTOCOL_V1

    def derive_correlation_id(*_args: Any, **_kwargs: Any) -> str:
        return secrets.token_hex(8)
from agent.core.event_stream import get_agent_event_bus
from agent.registry import AgentRegistry
from agent.sidar_agent import SidarAgent
from agent.swarm import SwarmOrchestrator, SwarmTask
from config import Config
from core.ci_remediation import build_ci_failure_context
from core.hitl import get_hitl_gate, get_hitl_store, set_hitl_broadcast_hook
from core.llm_client import LLMAPIError
from core.llm_metrics import (
    get_llm_metrics_collector,
    reset_current_metrics_user_id,
    set_current_metrics_user_id,
)
from managers.system_health import render_llm_metrics_prometheus

logger = logging.getLogger(__name__)
print = builtins.print


def _resolve_vision_components():
    vision_module = importlib.import_module("core.vision")
    build_analyze_prompt = getattr(
        vision_module,
        "build_analyze_prompt",
        lambda analysis_type="general": f"Görseli '{analysis_type}' odaklı analiz et.",
    )
    return vision_module.VisionPipeline, build_analyze_prompt


def _resolve_psutil_module():
    return importlib.import_module("psutil")

# ─────────────────────────────────────────────
#  HITL WebSocket Yayın Kümesi
# ─────────────────────────────────────────────
_hitl_ws_clients: set = set()
_COLLAB_ROOM_RE = re.compile(r"^[a-zA-Z0-9:_./-]{2,96}$")


class _CollaborationParticipant:
    def __init__(
        self,
        websocket: WebSocket,
        user_id: str,
        username: str,
        display_name: str,
        role: str = "user",
        can_write: bool = False,
        write_scopes: list[str] | None = None,
        joined_at: str = "",
    ) -> None:
        normalized_role = _normalize_collaboration_role(role)
        normalized_joined_at = joined_at

        # Eski test yardımcıları/çağrılar 5. pozisyonel argümanı joined_at olarak geçiyor.
        # Bu geriye dönük uyumluluk kolu, "2026-..." benzeri ISO zaman damgalarını
        # role yerine joined_at olarak yorumlar.
        if (
            not joined_at
            and not can_write
            and write_scopes is None
            and isinstance(role, str)
            and role
            and ("T" in role or "+" in role or role.endswith("Z") or role.lower() == "now")
        ):
            normalized_role = "user"
            normalized_joined_at = role

        self.websocket = websocket
        self.user_id = user_id
        self.username = username
        self.display_name = display_name
        self.role = normalized_role
        self.can_write = bool(can_write)
        self.write_scopes = list(write_scopes or [])
        self.joined_at = normalized_joined_at or _collaboration_now_iso()


class _CollaborationRoom:
    def __init__(
        self,
        room_id: str,
        participants: dict[int, _CollaborationParticipant] | None = None,
        messages: list[dict[str, Any]] | None = None,
        telemetry: list[dict[str, Any]] | None = None,
        active_task: asyncio.Task | None = None,
    ) -> None:
        self.room_id = room_id
        self.participants = participants if participants is not None else {}
        self.messages = messages if messages is not None else []
        self.telemetry = telemetry if telemetry is not None else []
        self.active_task = active_task


_collaboration_rooms: dict[str, _CollaborationRoom] = {}
_COLLAB_WRITE_INTENT_RE = re.compile(
    r"(?i)\b("
    r"write|edit|patch|modify|delete|remove|rename|commit|push|create file|save file|"
    r"yaz|düzenle|değiştir|sil|kaldır|yeniden adlandır|commit at|dosya oluştur|dosya kaydet"
    r")\b"
)
_COLLAB_WRITE_ROLES = {"admin", "maintainer", "developer", "editor"}


def _collaboration_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_room_id(room_id: str) -> str:
    normalized = (room_id or "").strip() or "workspace:default"
    if not _COLLAB_ROOM_RE.match(normalized):
        raise HTTPException(status_code=400, detail="Geçersiz room_id")
    return normalized


def _socket_key(websocket: WebSocket) -> int:
    return id(websocket)


def _serialize_collaboration_participant(participant: _CollaborationParticipant) -> dict[str, str]:
    return {
        "user_id": participant.user_id,
        "username": participant.username,
        "display_name": participant.display_name,
        "role": participant.role,
        "can_write": "true" if participant.can_write else "false",
        "write_scopes": list(participant.write_scopes),
        "joined_at": participant.joined_at,
    }


def _normalize_collaboration_role(role: str) -> str:
    allowed_roles = {"admin", "maintainer", "developer", "editor", "user"}
    normalized = (role or "").strip().lower()
    return normalized if normalized in allowed_roles else "user"


def _collaboration_write_scopes_for_role(role: str, room_id: str) -> list[str]:
    normalized_role = _normalize_collaboration_role(role)
    base_dir = Path(getattr(cfg, "BASE_DIR", ".")).resolve()
    if normalized_role == "admin":
        return [str(base_dir)]
    if normalized_role in _COLLAB_WRITE_ROLES:
        return [str(base_dir / "workspaces" / room_id.replace(":", "/"))]
    return []


def _collaboration_command_requires_write(command: str) -> bool:
    return bool(_COLLAB_WRITE_INTENT_RE.search(str(command or "")))


def _mask_collaboration_text(text: str) -> str:
    try:
        dlp_module = importlib.import_module("core.dlp")
        mask_pii = getattr(dlp_module, "mask_pii", None)
        if callable(mask_pii):
            return str(mask_pii(str(text or "")))
    except Exception:
        pass
    return str(text or "")


def _serialize_collaboration_room(room: _CollaborationRoom) -> dict[str, Any]:
    return {
        "room_id": room.room_id,
        "participants": [
            _serialize_collaboration_participant(item)
            for item in sorted(room.participants.values(), key=lambda value: value.display_name.lower())
        ],
        "messages": list(room.messages[-120:]),
        "telemetry": list(room.telemetry[-120:]),
    }


def _append_room_message(room: _CollaborationRoom, payload: dict[str, Any], *, limit: int = 200) -> None:
    room.messages.append(payload)
    if len(room.messages) > limit:
        room.messages = room.messages[-limit:]


def _append_room_telemetry(room: _CollaborationRoom, payload: dict[str, Any], *, limit: int = 200) -> None:
    safe_payload = dict(payload)
    if "content" in safe_payload:
        safe_payload["content"] = _mask_collaboration_text(str(safe_payload.get("content", "") or ""))
    if "error" in safe_payload:
        safe_payload["error"] = _mask_collaboration_text(str(safe_payload.get("error", "") or ""))
    room.telemetry.append(safe_payload)
    if len(room.telemetry) > limit:
        room.telemetry = room.telemetry[-limit:]


def _build_room_message(
    *,
    room_id: str,
    role: str,
    content: str,
    author_name: str,
    author_id: str,
    kind: str = "message",
    request_id: str = "",
) -> dict[str, Any]:
    return {
        "id": secrets.token_hex(8),
        "room_id": room_id,
        "role": role,
        "kind": kind,
        "content": _mask_collaboration_text(content),
        "author_name": author_name,
        "author_id": author_id,
        "request_id": request_id,
        "ts": _collaboration_now_iso(),
    }


async def _broadcast_room_payload(room: _CollaborationRoom, payload: dict[str, Any]) -> None:
    stale: list[int] = []
    for key, participant in list(room.participants.items()):
        try:
            await participant.websocket.send_json(payload)
        except Exception:
            stale.append(key)
    for key in stale:
        room.participants.pop(key, None)


async def _join_collaboration_room(
    websocket: WebSocket,
    *,
    room_id: str,
    user_id: str,
    username: str,
    display_name: str,
    user_role: str = "user",
) -> _CollaborationRoom:
    normalized = _normalize_room_id(room_id)
    current_room_id = str(getattr(websocket, "_sidar_room_id", "") or "")
    if current_room_id and current_room_id != normalized:
        await _leave_collaboration_room(websocket)

    room = _collaboration_rooms.setdefault(normalized, _CollaborationRoom(room_id=normalized))
    write_scopes = _collaboration_write_scopes_for_role(user_role, normalized)
    room.participants[_socket_key(websocket)] = _CollaborationParticipant(
        websocket=websocket,
        user_id=user_id,
        username=username,
        display_name=(display_name or username or user_id or "Anonim").strip()[:80],
        role=_normalize_collaboration_role(user_role),
        can_write=bool(write_scopes),
        write_scopes=write_scopes,
        joined_at=_collaboration_now_iso(),
    )
    setattr(websocket, "_sidar_room_id", normalized)
    await websocket.send_json({"type": "room_state", **_serialize_collaboration_room(room)})
    await _broadcast_room_payload(
        room,
        {
            "type": "presence",
            "room_id": normalized,
            "participants": _serialize_collaboration_room(room)["participants"],
        },
    )
    return room


async def _leave_collaboration_room(websocket: WebSocket) -> None:
    room_id = str(getattr(websocket, "_sidar_room_id", "") or "")
    if not room_id:
        return
    room = _collaboration_rooms.get(room_id)
    setattr(websocket, "_sidar_room_id", "")
    if room is None:
        return
    room.participants.pop(_socket_key(websocket), None)
    if room.participants:
        await _broadcast_room_payload(
            room,
            {
                "type": "presence",
                "room_id": room.room_id,
                "participants": _serialize_collaboration_room(room)["participants"],
            },
        )
        return
    if room.active_task and not room.active_task.done():
        room.active_task.cancel()
    _collaboration_rooms.pop(room_id, None)


def _is_sidar_mention(message: str) -> bool:
    return bool(re.search(r"(^|\s)@sidar\b", message, flags=re.IGNORECASE))


def _strip_sidar_mention(message: str) -> str:
    stripped = re.sub(r"(^|\s)@sidar\b", " ", message, count=1, flags=re.IGNORECASE)
    return " ".join(stripped.split()).strip()


def _build_collaboration_prompt(room: _CollaborationRoom, *, actor_name: str, command: str) -> str:
    transcript: list[str] = []
    for item in room.messages[-10:]:
        transcript.append(
            f"[{item.get('role', 'user')}] {item.get('author_name', 'Anonim')}: {str(item.get('content', '')).strip()[:240]}"
        )
    recent_context = "\n".join(transcript) if transcript else "(henüz ortak geçmiş yok)"
    participants = ", ".join(
        f"{participant.display_name}<{participant.role}>"
        for participant in sorted(room.participants.values(), key=lambda value: value.display_name.lower())
    )
    actor = next(
        (item for item in room.participants.values() if item.display_name == actor_name),
        None,
    )
    actor_role = actor.role if actor else "user"
    actor_scopes = ", ".join(actor.write_scopes) if actor and actor.write_scopes else "read-only"
    return (
        "[COLLABORATION WORKSPACE]\n"
        f"room_id={room.room_id}\n"
        f"participants={participants or 'unknown'}\n"
        f"requesting_user={actor_name}\n"
        f"requesting_role={actor_role}\n"
        f"requesting_write_scopes={actor_scopes}\n"
        "recent_transcript=\n"
        f"{recent_context}\n\n"
        "Kullanıcılar ortak bir çalışma alanında SİDAR ile iş birliği yapıyor. "
        "Yanıtında ekip bağlamını koru ve gerekiyorsa kimin ne istediğini netleştir. "
        "Yazma işlemlerinde sadece requesting_write_scopes kapsamındaki dizinleri kullan.\n\n"
        f"Current command:\n{command}"
    )


def _iter_stream_chunks(text: str, *, size: int = 180) -> list[str]:
    clean = str(text or "")
    if not clean:
        return []
    return [clean[index:index + size] for index in range(0, len(clean), size)]


async def _hitl_broadcast(payload: dict) -> None:
    """HITL olaylarını bağlı tüm admin WebSocket bağlantılarına gönder."""
    dead = set()
    for ws in list(_hitl_ws_clients):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    _hitl_ws_clients.difference_update(dead)


set_hitl_broadcast_hook(_hitl_broadcast)

# ─────────────────────────────────────────────
#  UYGULAMA BAŞLATMA
# ─────────────────────────────────────────────

cfg = Config()
Config.initialize_directories()
_agent: SidarAgent | None = None
# Event loop başlamadan önce asyncio.Lock() oluşturmak Python <3.10'da
# DeprecationWarning üretir. Lazy başlatma ile bu risk tamamen ortadan kalkar.
_agent_lock: asyncio.Lock | None = None
_rag_prewarm_task: asyncio.Task | None = None
_autonomy_cron_task: asyncio.Task | None = None
_autonomy_cron_stop: asyncio.Event | None = None
_nightly_memory_task: asyncio.Task | None = None
_nightly_memory_stop: asyncio.Event | None = None
_shutdown_cleanup_done = False
MAX_FILE_CONTENT_BYTES = 1_048_576  # 1 MB



def _list_child_ollama_pids() -> list[int]:
    """Bu prosesin çocukları arasında ollama süreçlerini bulur."""
    pids: list[int] = []
    try:
        psutil_module = _resolve_psutil_module()
        current = psutil_module.Process(os.getpid())
        for child in current.children(recursive=False):
            with contextlib.suppress(Exception):
                comm = str(child.name() or "").strip().lower()
                args = " ".join(child.cmdline() or []).strip().lower()
                if comm == "ollama" or "ollama serve" in args:
                    pids.append(int(child.pid))
        return sorted(set(pids))
    except Exception:
        if os.name == "nt":
            return []

    try:
        raw = subprocess.check_output(
            ["ps", "-eo", "pid=,ppid=,comm=,args="],
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []

    parent_pid = int(os.getpid())
    for line in raw.decode("utf-8", errors="ignore").splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid_str, ppid_str, comm, args = parts
        if not pid_str.isdigit() or not ppid_str.isdigit():
            continue
        if int(ppid_str) != parent_pid:
            continue
        comm = comm.strip().lower()
        args = args.strip().lower()
        if comm == "ollama" or "ollama serve" in args:
            pids.append(int(pid_str))
    return sorted(set(pids))


def _reap_child_processes_nonblocking() -> int:
    """Zombi child process'leri waitpid(WNOHANG) ile temizle."""
    reaped = 0
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        except Exception:
            break
        if pid <= 0:
            break
        reaped += 1
    return reaped


def _terminate_ollama_child_pids(pids: list[int], *, grace_seconds: float = 0.15) -> None:
    """Ollama child process'lerine önce TERM sonra KILL uygular."""
    for pid in pids:
        with contextlib.suppress(Exception):
            os.kill(pid, signal.SIGTERM)

    if pids and grace_seconds > 0:
        time.sleep(grace_seconds)
        for pid in pids:
            with contextlib.suppress(Exception):
                os.kill(pid, signal.SIGKILL)


def _force_shutdown_local_llm_processes() -> None:
    """Sunucu kapanırken yerel ollama child process'lerini zorla sonlandırır."""
    global _shutdown_cleanup_done
    if _shutdown_cleanup_done:
        return
    _shutdown_cleanup_done = True

    if str(getattr(cfg, "AI_PROVIDER", "") or "").lower() != "ollama":
        _reap_child_processes_nonblocking()
        return

    if not bool(getattr(cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", False)):
        _reap_child_processes_nonblocking()
        return

    pids = _list_child_ollama_pids()
    _terminate_ollama_child_pids(pids)

    reaped = _reap_child_processes_nonblocking()
    if pids or reaped:
        logger.info("Yerel LLM shutdown cleanup: term=%d reap=%d", len(pids), reaped)


atexit.register(_force_shutdown_local_llm_processes)


async def _async_force_shutdown_local_llm_processes() -> None:
    """Lifespan kapanışında event-loop'u bloklamadan cleanup yap."""
    global _shutdown_cleanup_done
    if _shutdown_cleanup_done:
        return
    if str(getattr(cfg, "AI_PROVIDER", "") or "").lower() != "ollama":
        _shutdown_cleanup_done = True
        _reap_child_processes_nonblocking()
        return
    if not bool(getattr(cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", False)):
        _shutdown_cleanup_done = True
        _reap_child_processes_nonblocking()
        return

    pids = _list_child_ollama_pids()
    for pid in pids:
        with contextlib.suppress(Exception):
            os.kill(pid, signal.SIGTERM)
    if pids:
        await asyncio.sleep(0.15)
        for pid in pids:
            with contextlib.suppress(Exception):
                os.kill(pid, signal.SIGKILL)

    _shutdown_cleanup_done = True
    reaped = _reap_child_processes_nonblocking()
    if pids or reaped:
        logger.info("Yerel LLM async shutdown cleanup: term=%d reap=%d", len(pids), reaped)


def _bind_llm_usage_sink(agent: SidarAgent) -> None:
    collector = get_llm_metrics_collector()
    if getattr(collector, "_sidar_usage_sink_bound", False):
        return

    def _sink(event) -> None:
        user_id = getattr(event, "user_id", "")
        if not user_id:
            return

        async def _persist() -> None:
            try:
                await agent.memory.db.record_provider_usage_daily(
                    user_id=user_id,
                    provider=getattr(event, "provider", "unknown"),
                    tokens_used=int(getattr(event, "total_tokens", 0) or 0),
                    requests_inc=1,
                )
            except Exception as exc:
                logger.debug("LLM usage DB yazımı atlandı: %s", exc)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_persist())
        except RuntimeError:
            pass

    if hasattr(collector, "set_usage_sink"):
        collector.set_usage_sink(_sink)
    collector._sidar_usage_sink_bound = True


async def _prewarm_rag_embeddings() -> None:
    """Sunucu açılışında RAG embedding fonksiyonunu arka planda ısıtır."""
    try:
        agent = await _resolve_agent_instance()
        rag = getattr(agent, "rag", None)
        if rag is None:
            logger.info("RAG prewarm atlandı: rag motoru bulunamadı.")
            return

        if not getattr(rag, "_chroma_available", False):
            logger.info("RAG prewarm atlandı: ChromaDB kullanılamıyor.")
            return

        # _init_chroma() ilk kurulumda embedding fonksiyonunu zaten üretir.
        # Burada çağrıyı startup'ta tetikleyerek ilk RAG isteğindeki cold-start
        # gecikmesini kullanıcı yerine sunucu açılışına taşırız.
        logger.info("RAG prewarm başlatıldı (embedding fonksiyonu hazırlanıyor)...")
        await asyncio.to_thread(rag._init_chroma)
        logger.info("RAG prewarm tamamlandı.")
    except Exception as exc:
        logger.warning("RAG prewarm başarısız oldu: %s", exc)


async def get_agent() -> SidarAgent:
    """Singleton ajan — ilk async çağrıda başlatılır (asyncio.Lock ile korunur).
    _agent_lock lifespan başlangıcında başlatılmış olmalıdır."""
    global _agent
    if _agent is not None:
        return _agent
    async with _agent_lock:
        if _agent is None:
            _agent = SidarAgent(cfg)
            await _agent.initialize()
            _bind_llm_usage_sink(_agent)
    return _agent


async def _get_agent_instance() -> SidarAgent:
    """get_agent monkeypatch'lerinin sync/async varyantlarını uyumlu şekilde çözer."""
    maybe_agent = get_agent()
    if inspect.isawaitable(maybe_agent):
        return await maybe_agent
    return maybe_agent


async def _resolve_agent_instance() -> SidarAgent:
    """_get_agent_instance monkeypatch'lerinin sync/async varyantlarını uyumlu çözer."""
    maybe_agent = _get_agent_instance()
    if inspect.isawaitable(maybe_agent):
        return await maybe_agent
    return maybe_agent


async def _collect_agent_response(agent: SidarAgent, prompt: str) -> str:
    """Ajanın stream çıktısını tek metinde birleştir."""
    chunks: list[str] = []
    async for chunk in agent.respond(prompt):
        chunks.append(chunk)
    return "".join(chunks).strip()


async def _dispatch_autonomy_trigger(
    *,
    trigger_source: str,
    event_name: str,
    payload: dict[str, Any],
    meta: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Webhook/cron/federation kaynaklı otonom tetikleyiciyi ajana ilet."""
    agent = _await_if_needed(_resolve_agent_instance())
    if inspect.isawaitable(agent):
        agent = await agent
    trigger = ExternalTrigger(
        trigger_id=f"trigger-{secrets.token_hex(6)}",
        source=trigger_source,
        event_name=event_name,
        payload=payload,
        meta=dict(meta or {}),
    )
    fallback_prompt = (
        str(payload.get("federation_prompt") or "").strip()
        if isinstance(payload, dict)
        else ""
    )
    if not fallback_prompt and isinstance(payload, dict) and payload.get("kind") == "action_feedback":
        fallback_prompt = ActionFeedback(
            feedback_id=str(payload.get("feedback_id") or trigger.trigger_id),
            source_system=str(payload.get("source_system") or trigger.source),
            source_agent=str(payload.get("source_agent") or "external"),
            action_name=str(payload.get("action_name") or trigger.event_name),
            status=str(payload.get("status") or "received"),
            summary=str(payload.get("summary") or "Dış sistem action feedback sinyali alındı."),
            related_task_id=str(payload.get("related_task_id") or ""),
            related_trigger_id=str(payload.get("related_trigger_id") or ""),
            details=dict(payload.get("details") or {}),
            meta=dict(trigger.meta or {}),
            correlation_id=str(payload.get("correlation_id") or trigger.correlation_id),
        ).to_prompt()
    if hasattr(agent, "handle_external_trigger"):
        result = await agent.handle_external_trigger(trigger)
    else:
        summary = await _collect_agent_response(agent, fallback_prompt or trigger.to_prompt())
        result = {
            "trigger_id": trigger.trigger_id,
            "source": trigger.source,
            "event_name": trigger.event_name,
            "summary": summary,
            "status": "success" if summary else "empty",
            "meta": dict(trigger.meta or {}),
            "created_at": time.time(),
            "completed_at": time.time(),
        }
    return {
        "trigger_id": result["trigger_id"],
        "source": result["source"],
        "event_name": result["event_name"],
        "summary": result["summary"],
        "status": result["status"],
        "meta": result.get("meta", {}),
        "created_at": result.get("created_at"),
        "completed_at": result.get("completed_at"),
        "remediation": result.get("remediation"),
    }


def _fallback_ci_failure_context(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """CI remediation import'u stublandığında temel bağlamı yerelde normalize eder."""
    data = dict(payload or {})
    normalized = str(event_name or "").strip().lower()
    failure_conclusions = {"failure", "timed_out", "cancelled", "startup_failure", "action_required"}

    if bool(data.get("ci_failure") or data.get("pipeline_failed")) or normalized in {
        "ci_failure_remediation",
        "ci_pipeline_failed",
        "pipeline_failed",
    }:
        return {
            "kind": "generic_ci_failure",
            "repo": str(data.get("repo") or data.get("repository") or "").strip(),
            "workflow_name": str(data.get("workflow_name") or data.get("pipeline") or data.get("job_name") or "ci_failure").strip(),
            "run_id": str(data.get("run_id") or data.get("pipeline_id") or data.get("build_id") or "").strip(),
            "run_number": str(data.get("run_number") or data.get("pipeline_number") or "").strip(),
            "branch": str(data.get("branch") or data.get("ref") or "").strip(),
            "base_branch": str(data.get("base_branch") or data.get("target_branch") or "main").strip(),
            "sha": str(data.get("sha") or data.get("commit") or "").strip(),
            "conclusion": str(data.get("conclusion") or "failure").strip(),
            "status": str(data.get("status") or "completed").strip(),
            "html_url": str(data.get("html_url") or data.get("pipeline_url") or "").strip(),
            "jobs_url": str(data.get("jobs_url") or "").strip(),
            "logs_url": str(data.get("logs_url") or data.get("log_url") or "").strip(),
            "log_excerpt": str(data.get("log_excerpt") or data.get("logs") or data.get("error") or data.get("details") or "").strip(),
            "failure_summary": str(data.get("failure_summary") or data.get("summary") or data.get("message") or "ci failure").strip(),
            "failed_jobs": list(data.get("failed_jobs") or data.get("jobs") or []),
        }

    repository = dict(data.get("repository") or {})
    repo_name = str(repository.get("full_name") or repository.get("name") or "").strip()

    if normalized == "workflow_run":
        workflow = dict(data.get("workflow_run") or {})
        if (
            str(workflow.get("status") or "").strip().lower() == "completed"
            and str(workflow.get("conclusion") or "").strip().lower() in failure_conclusions
        ):
            pull_requests = list(workflow.get("pull_requests") or [])
            base_branch = ""
            if pull_requests:
                base_branch = str((pull_requests[0] or {}).get("base", {}).get("ref", "") or "").strip()
            return {
                "kind": "workflow_run",
                "repo": repo_name,
                "workflow_name": str(workflow.get("name") or "workflow_run").strip(),
                "run_id": str(workflow.get("id") or "").strip(),
                "run_number": str(workflow.get("run_number") or "").strip(),
                "branch": str(workflow.get("head_branch") or "").strip(),
                "base_branch": base_branch or str(repository.get("default_branch") or "main").strip(),
                "sha": str(workflow.get("head_sha") or "").strip(),
                "conclusion": str(workflow.get("conclusion") or "").strip(),
                "status": str(workflow.get("status") or "").strip(),
                "html_url": str(workflow.get("html_url") or "").strip(),
                "jobs_url": str(workflow.get("jobs_url") or "").strip(),
                "logs_url": str(workflow.get("logs_url") or "").strip(),
                "log_excerpt": str(workflow.get("display_title") or workflow.get("name") or "").strip(),
                "failure_summary": str(workflow.get("conclusion") or "failure").strip(),
                "failed_jobs": list(workflow.get("failed_jobs") or workflow.get("jobs") or []),
            }

    if normalized == "check_run":
        check_run = dict(data.get("check_run") or {})
        if str(check_run.get("conclusion") or "").strip().lower() in failure_conclusions:
            output = dict(check_run.get("output") or {})
            return {
                "kind": "check_run",
                "repo": repo_name,
                "workflow_name": str(check_run.get("name") or "check_run").strip(),
                "run_id": str(check_run.get("id") or "").strip(),
                "run_number": "",
                "branch": str(check_run.get("check_suite", {}).get("head_branch") or "").strip(),
                "base_branch": str(repository.get("default_branch") or "main").strip(),
                "sha": str(check_run.get("head_sha") or "").strip(),
                "conclusion": str(check_run.get("conclusion") or "").strip(),
                "status": str(check_run.get("status") or "").strip(),
                "html_url": str(check_run.get("html_url") or "").strip(),
                "jobs_url": str(check_run.get("details_url") or "").strip(),
                "logs_url": str(check_run.get("details_url") or "").strip(),
                "log_excerpt": "\n\n".join(filter(None, [str(output.get("summary") or "").strip(), str(output.get("text") or "").strip()])),
                "failure_summary": str(output.get("title") or check_run.get("name") or "check failed").strip(),
                "failed_jobs": list(check_run.get("failed_jobs") or check_run.get("jobs") or []),
            }

    if normalized == "check_suite":
        suite = dict(data.get("check_suite") or {})
        if str(suite.get("conclusion") or "").strip().lower() in failure_conclusions:
            return {
                "kind": "check_suite",
                "repo": repo_name,
                "workflow_name": str(suite.get("app", {}).get("name") or "check_suite").strip(),
                "run_id": str(suite.get("id") or "").strip(),
                "run_number": "",
                "branch": str(suite.get("head_branch") or "").strip(),
                "base_branch": str(repository.get("default_branch") or "main").strip(),
                "sha": str(suite.get("head_sha") or "").strip(),
                "conclusion": str(suite.get("conclusion") or "").strip(),
                "status": str(suite.get("status") or "").strip(),
                "html_url": str(suite.get("url") or "").strip(),
                "jobs_url": "",
                "logs_url": "",
                "log_excerpt": str(suite.get("app", {}).get("name") or "check_suite_failure").strip(),
                "failure_summary": str(suite.get("conclusion") or "check suite failure").strip(),
                "failed_jobs": list(suite.get("failed_jobs") or suite.get("jobs") or []),
            }

    return {}


def _resolve_ci_failure_context(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Önce çekirdek yardımcıyı dener; test stub/fallback durumunda yerel normalize eder."""
    context = build_ci_failure_context(event_name, payload)
    if context:
        return dict(context)
    return _fallback_ci_failure_context(event_name, payload)


def _trim_autonomy_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " …[truncated]"


def _build_event_driven_federation_spec(source: str, event_name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    source_key = str(source or "").strip().lower()
    event_key = str(event_name or "").strip().lower()
    data = dict(payload or {})

    if source_key in {"jira", "atlassian", "jira_cloud"}:
        issue = dict(data.get("issue") or data)
        action = str(data.get("action") or data.get("webhookEvent") or event_key or "").strip().lower()
        issue_key = str(issue.get("key") or issue.get("id") or data.get("issue_key") or "").strip()
        summary = str(issue.get("title") or issue.get("summary") or data.get("summary") or "").strip()
        if issue_key and ("created" in action or event_key in {"issue_created", "issue_opened", "jira_issue_created"}):
            project_key = str((issue.get("fields") or {}).get("project", {}).get("key") or data.get("project") or "").strip()
            return {
                "workflow_type": "jira_issue",
                "task_id": f"jira-{issue_key.lower()}",
                "source_system": "jira",
                "source_agent": "issue_webhook",
                "goal": (
                    f"Jira issue {issue_key} için event-driven swarm remediation/uygulama planı çıkar: {summary or 'başlıksız issue'}. "
                    "Coder uygulanabilir teknik yaklaşımı oluştursun, Reviewer risk/QA/handoff değerlendirsin."
                ),
                "context": {
                    "workflow_type": "jira_issue",
                    "issue_key": issue_key,
                    "issue_summary": summary,
                    "project_key": project_key,
                    "issue_status": str((issue.get("fields") or {}).get("status", {}).get("name") or data.get("status") or "").strip(),
                    "issue_type": str((issue.get("fields") or {}).get("issuetype", {}).get("name") or data.get("issue_type") or "").strip(),
                },
                "inputs": [
                    f"issue_key={issue_key}",
                    f"summary={summary}",
                    f"description={_trim_autonomy_text((issue.get('fields') or {}).get('description') or data.get('description') or '', 1000)}",
                ],
                "correlation_id": derive_correlation_id(data.get("correlation_id", ""), issue_key, summary),
            }

    if source_key == "github":
        pr = dict(data.get("pull_request") or {})
        action = str(data.get("action") or event_key or "").strip().lower()
        pr_number = str(pr.get("number") or data.get("number") or "").strip()
        pr_title = str(pr.get("title") or data.get("title") or "").strip()
        if pr_number and action in {"opened", "reopened", "ready_for_review", "synchronize"}:
            repo = str((data.get("repository") or {}).get("full_name") or data.get("repo") or "").strip()
            return {
                "workflow_type": "github_pull_request",
                "task_id": f"github-pr-{pr_number}",
                "source_system": "github",
                "source_agent": "pull_request_webhook",
                "goal": (
                    f"GitHub PR #{pr_number} ({pr_title or 'başlıksız PR'}) için event-driven swarm incelemesi yap. "
                    "Coder değişiklik/patch/test stratejisini çıkarsın, Reviewer merge riski ve QA kapısını değerlendirsin."
                ),
                "context": {
                    "workflow_type": "github_pull_request",
                    "repo": repo,
                    "pr_number": pr_number,
                    "pr_title": pr_title,
                    "base_branch": str((pr.get("base") or {}).get("ref") or data.get("base_branch") or "").strip(),
                    "head_branch": str((pr.get("head") or {}).get("ref") or data.get("branch") or "").strip(),
                    "author": str((pr.get("user") or {}).get("login") or data.get("sender", {}).get("login") or "").strip(),
                },
                "inputs": [
                    f"pr_number={pr_number}",
                    f"title={pr_title}",
                    f"body={_trim_autonomy_text(pr.get('body') or data.get('body') or '', 1000)}",
                ],
                "correlation_id": derive_correlation_id(data.get("correlation_id", ""), pr.get("node_id", ""), pr_number),
            }

    if source_key in {"system_monitor", "monitor", "observability", "system"}:
        severity = str(data.get("severity") or data.get("level") or data.get("status") or "").strip().lower()
        alert_name = str(data.get("alert_name") or data.get("service") or data.get("title") or event_key).strip()
        if severity in {"error", "critical", "fatal"} or event_key in {"system_error", "monitor_alert", "incident", "error_detected"}:
            return {
                "workflow_type": "system_error",
                "task_id": f"system-{secrets.token_hex(4)}",
                "source_system": "system_monitor",
                "source_agent": "alert_webhook",
                "goal": (
                    f"Sistem monitör hatasını değerlendir: {alert_name}. "
                    "Coder muhtemel kök neden ve hotfix adımlarını çıkarsın, Reviewer risk/rollback/QA planını doğrulasın."
                ),
                "context": {
                    "workflow_type": "system_error",
                    "alert_name": alert_name,
                    "severity": severity or "error",
                    "service": str(data.get("service") or "").strip(),
                    "environment": str(data.get("environment") or data.get("env") or "").strip(),
                },
                "inputs": [
                    f"message={_trim_autonomy_text(data.get('message') or data.get('summary') or data.get('error') or '', 1000)}",
                    f"stacktrace={_trim_autonomy_text(data.get('stacktrace') or data.get('details') or '', 1000)}",
                ],
                "correlation_id": derive_correlation_id(data.get("correlation_id", ""), data.get("alert_id", ""), alert_name),
            }

    return None


def _build_swarm_goal_for_role(base_goal: str, role: str, spec: dict[str, Any]) -> str:
    context_blob = json.dumps(spec.get("context") or {}, ensure_ascii=False, sort_keys=True)
    inputs_blob = json.dumps(spec.get("inputs") or [], ensure_ascii=False)
    if role == "coder":
        return (
            f"{base_goal}\n\n"
            "[EVENT_DRIVEN_SWARM:CODER]\n"
            "Bu dış olay için inisiyatif al. Muhtemel kod hedeflerini, uygulanabilir adımları, test/komut planını ve gerekiyorsa açılması gereken follow-up'ları üret.\n"
            f"context={context_blob}\ninputs={inputs_blob}"
        )
    return (
        f"{base_goal}\n\n"
        "[EVENT_DRIVEN_SWARM:REVIEWER]\n"
        "Coder çıktısını kalite kapısı olarak incele. Riskler, QA, rollback, insan onayı ve follow-up aksiyonlarını netleştir.\n"
        f"context={context_blob}\ninputs={inputs_blob}"
    )


async def _run_event_driven_federation_workflow(
    *,
    source: str,
    event_name: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    spec = _build_event_driven_federation_spec(source, event_name, payload)
    if spec is None:
        return None

    orchestrator = SwarmOrchestrator(cfg)
    correlation_id = str(spec.get("correlation_id") or derive_correlation_id(spec.get("task_id", ""), event_name)).strip()
    task_context = {
        **{str(k): str(v) for k, v in dict(spec.get("context") or {}).items()},
        "event_name": str(event_name or ""),
        "event_source": str(source or ""),
        "correlation_id": correlation_id,
        "event_payload_excerpt": _trim_autonomy_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), 1200),
    }
    tasks = [
        SwarmTask(
            task_id=str(spec.get("task_id") or f"event-{secrets.token_hex(4)}"),
            goal=_build_swarm_goal_for_role(str(spec.get("goal") or ""), "coder", spec),
            intent="code",
            context=dict(task_context),
            preferred_agent="coder",
        ),
        SwarmTask(
            task_id=str(spec.get("task_id") or f"event-{secrets.token_hex(4)}"),
            goal=_build_swarm_goal_for_role(str(spec.get("goal") or ""), "reviewer", spec),
            intent="review",
            context=dict(task_context),
            preferred_agent="reviewer",
        ),
    ]
    pipeline = await orchestrator.run_pipeline(tasks, session_id=correlation_id)
    envelope = FederationTaskEnvelope(
        task_id=str(spec.get("task_id") or f"event-{secrets.token_hex(4)}"),
        source_system=str(spec.get("source_system") or source or "external"),
        source_agent=str(spec.get("source_agent") or "event_webhook"),
        target_system="sidar",
        target_agent="supervisor",
        goal=str(spec.get("goal") or ""),
        intent="mixed",
        context={**task_context, "workflow_type": str(spec.get("workflow_type") or "external_event")},
        inputs=[str(item) for item in list(spec.get("inputs") or [])],
        meta={"initiative": "event_driven_swarm", "event_name": str(event_name or "")},
        correlation_id=correlation_id,
    )
    coder_result = pipeline[0] if pipeline else None
    reviewer_result = pipeline[-1] if pipeline else None
    reviewer_summary = _trim_autonomy_text(getattr(reviewer_result, "summary", "") or getattr(coder_result, "summary", "") or "", 2400)
    fed_result = FederationTaskResult(
        task_id=envelope.task_id,
        source_system="sidar",
        source_agent="supervisor",
        target_system=envelope.source_system,
        target_agent=envelope.source_agent,
        status=(getattr(reviewer_result, "status", "") or getattr(coder_result, "status", "") or "failed"),
        summary=reviewer_summary or "Event-driven swarm sonucu üretilemedi.",
        protocol=envelope.protocol,
        evidence=[_trim_autonomy_text(getattr(item, "summary", "") or "", 800) for item in pipeline if getattr(item, "summary", "")],
        next_actions=[
            f"coder_status={getattr(coder_result, 'status', 'n/a')}",
            f"reviewer_status={getattr(reviewer_result, 'status', 'n/a')}",
            f"workflow_type={spec.get('workflow_type', 'external_event')}",
        ],
        meta={
            "workflow_type": str(spec.get("workflow_type") or "external_event"),
            "initiative": "event_driven_swarm",
            "correlation_id": correlation_id,
            "event_name": str(event_name or ""),
        },
        correlation_id=correlation_id,
    )
    federation_prompt = (
        envelope.to_prompt()
        + "\n\n[SWARM_PIPELINE_RESULT]\n"
        + f"workflow_type={spec.get('workflow_type', 'external_event')}\n"
        + f"coder_summary={_trim_autonomy_text(getattr(coder_result, 'summary', '') or '', 1200)}\n"
        + f"reviewer_summary={reviewer_summary or '-'}"
    )
    return {
        "workflow_type": str(spec.get("workflow_type") or "external_event"),
        "correlation_id": correlation_id,
        "federation_task": asdict(envelope),
        "federation_result": asdict(fed_result),
        "pipeline": [asdict(item) for item in pipeline],
        "federation_prompt": federation_prompt,
    }


def _embed_event_driven_federation_payload(base_payload: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "federation_task",
        "federation_task": dict(workflow.get("federation_task") or {}),
        "federation_prompt": str(workflow.get("federation_prompt") or ""),
        "event_payload": dict(base_payload or {}),
        "event_driven_federation": dict(workflow or {}),
        "task_id": str((workflow.get("federation_task") or {}).get("task_id", "") or ""),
        "source_system": str((workflow.get("federation_task") or {}).get("source_system", "") or ""),
        "source_agent": str((workflow.get("federation_task") or {}).get("source_agent", "") or ""),
        "target_agent": str((workflow.get("federation_task") or {}).get("target_agent", "") or ""),
        "correlation_id": str(workflow.get("correlation_id") or ""),
    }


async def _autonomous_cron_loop(stop_event: asyncio.Event) -> None:
    """Yapılandırılmış aralıklarla otonom değerlendirme tetikler."""
    interval = max(30, int(getattr(cfg, "AUTONOMOUS_CRON_INTERVAL_SECONDS", 900) or 900))
    prompt = str(
        getattr(
            cfg,
            "AUTONOMOUS_CRON_PROMPT",
            "Sistemdeki bekleyen otonom iş fırsatlarını değerlendir ve gerekli aksiyon planını çıkar.",
        )
        or ""
    ).strip()
    if not prompt:
        logger.info("Autonomous cron prompt boş; cron loop başlatılmadı.")
        return

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except TimeoutError:
            try:
                result = await _dispatch_autonomy_trigger(
                    trigger_source="cron",
                    event_name="scheduled_tick",
                    payload={"prompt": prompt, "interval_seconds": interval},
                    meta={"mode": "autonomous_cron"},
                )
                logger.info("Autonomous cron tetiklendi: %s", result["trigger_id"])
            except Exception as exc:
                logger.warning("Autonomous cron tetikleme hatası: %s", exc)


async def _nightly_memory_loop(stop_event: asyncio.Event) -> None:
    """Sistem idle iken gece hafıza konsolidasyonu ve RAG pruning çalıştırır."""
    if not bool(getattr(cfg, "ENABLE_NIGHTLY_MEMORY_PRUNING", False)):
        logger.info("Nightly memory pruning devre dışı; döngü başlatılmadı.")
        return

    interval = max(300, int(getattr(cfg, "NIGHTLY_MEMORY_INTERVAL_SECONDS", 86400) or 86400))
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except TimeoutError:
            try:
                agent = await _resolve_agent_instance()
                report = await agent.run_nightly_memory_maintenance(reason="nightly_loop")
                logger.info("Nightly memory maintenance sonucu: %s", report.get("status", "unknown"))
            except Exception as exc:
                logger.warning("Nightly memory maintenance hatası: %s", exc)


# ─────────────────────────────────────────────
#  FASTAPI UYGULAMASI
# ─────────────────────────────────────────────

@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    global _rag_prewarm_task, _agent_lock, _redis_lock, _local_rate_lock
    global _autonomy_cron_task, _autonomy_cron_stop, _nightly_memory_task, _nightly_memory_stop
    # Kilitleri event loop ayaktayken kesin olarak başlat (lazy başlatma race-condition'ı önler)
    _agent_lock = asyncio.Lock()
    _redis_lock = asyncio.Lock()
    _local_rate_lock = asyncio.Lock()
    # Config doğrulamasını thread'de çalıştır — sync httpx Ollama çağrısı event loop'u bloklamaz (O-4)
    await asyncio.to_thread(Config.validate_critical_settings)
    await asyncio.to_thread(_reload_persisted_marketplace_plugins)
    _rag_prewarm_task = asyncio.create_task(_prewarm_rag_embeddings())
    if bool(getattr(cfg, "ENABLE_AUTONOMOUS_CRON", False)):
        _autonomy_cron_stop = asyncio.Event()
        _autonomy_cron_task = asyncio.create_task(_autonomous_cron_loop(_autonomy_cron_stop))
    if bool(getattr(cfg, "ENABLE_NIGHTLY_MEMORY_PRUNING", False)):
        _nightly_memory_stop = asyncio.Event()
        _nightly_memory_task = asyncio.create_task(_nightly_memory_loop(_nightly_memory_stop))
    try:
        yield
    finally:
        if _autonomy_cron_stop is not None:
            _autonomy_cron_stop.set()
        if _autonomy_cron_task and not _autonomy_cron_task.done():
            _autonomy_cron_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _autonomy_cron_task
        if _nightly_memory_stop is not None:
            _nightly_memory_stop.set()
        if _nightly_memory_task and not _nightly_memory_task.done():
            _nightly_memory_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _nightly_memory_task
        if _rag_prewarm_task and not _rag_prewarm_task.done():
            _rag_prewarm_task.cancel()
            try:
                await _rag_prewarm_task
            except asyncio.CancelledError:
                pass
        await _close_redis_client()
        await _async_force_shutdown_local_llm_processes()




def _build_user_from_jwt_payload(payload: dict):
    user_id = str(payload.get("sub", "") or "").strip()
    username = str(payload.get("username", "") or "").strip()
    role = str(payload.get("role", "user") or "user").strip() or "user"
    tenant_id = str(payload.get("tenant_id", "default") or "default").strip() or "default"
    if not user_id or not username:
        return None
    return SimpleNamespace(id=user_id, username=username, role=role, tenant_id=tenant_id)


def _get_jwt_secret() -> str:
    """Config'ten JWT secret'ı oku. Ayarlanmamışsa CRITICAL uyarısı ver."""
    key = str(getattr(cfg, "JWT_SECRET_KEY", "") or "")
    if not key:
        logger.critical(
            "JWT_SECRET_KEY yapılandırılmamış! Geliştirme ortamında geçici bir "
            "anahtar kullanılıyor. Üretim ortamında .env dosyasına güçlü bir "
            "JWT_SECRET_KEY değeri eklemelisiniz."
        )
        key = "sidar-dev-secret"
    return key


async def _resolve_user_from_token(_agent: SidarAgent, token: str):
    secret_key = _get_jwt_secret()
    algorithm = str(getattr(cfg, "JWT_ALGORITHM", "HS256") or "HS256")
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        return _build_user_from_jwt_payload(payload)
    except jwt.PyJWTError:
        pass
    # Fallback: DB token lookup (opak / oturum tabanlı token desteği)
    if _agent and hasattr(_agent, "memory") and hasattr(_agent.memory, "db"):
        db_user = await _agent.memory.db.get_user_by_token(token)
        if db_user:
            return db_user
    return None


async def _issue_auth_token(agent: SidarAgent, user) -> str:
    del agent  # Stateless JWT üretiminde DB bağımlılığı yok.
    secret_key = _get_jwt_secret()
    algorithm = str(getattr(cfg, "JWT_ALGORITHM", "HS256") or "HS256")
    ttl_days = max(1, int(getattr(cfg, "JWT_TTL_DAYS", 7) or 7))
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "username": str(user.username),
        "role": str(getattr(user, "role", "user") or "user"),
        "tenant_id": str(getattr(user, "tenant_id", "default") or "default"),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=ttl_days)).timestamp()),
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


app = FastAPI(
    title="Sidar Web UI & REST API",
    description=(
        "Sidar AI Ajanı için Web Arayüzü ve REST API uç noktaları. "
        "RAG, GitHub, Görev Yönetimi ve Sistem İzleme API'lerini içerir."
    ),
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=_app_lifespan,
)


def _register_exception_handlers(application: FastAPI) -> None:
    if not hasattr(application, "exception_handler"):
        return

    @application.exception_handler(HTTPException)
    async def _http_exception_handler(_request: Request, exc: HTTPException):
        detail = getattr(exc, "detail", "İstek işlenemedi.")
        if isinstance(detail, dict):
            content = {"success": False, **detail}
            content.setdefault("error", "İstek işlenemedi.")
        else:
            content = {"success": False, "error": str(detail or "İstek işlenemedi.")}
        return JSONResponse(content, status_code=getattr(exc, "status_code", 500))

    @application.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(
            "İşlenmeyen web hatası: path=%s error=%s",
            getattr(request.url, "path", "?"),
            exc,
        )
        return JSONResponse(
            {"success": False, "error": "İç sunucu hatası", "detail": str(exc)},
            status_code=500,
        )


_register_exception_handlers(app)


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    """Bearer token ile stateless JWT kullanıcı doğrulaması uygular."""
    open_paths = {
        "/", "/health", "/healthz", "/docs", "/redoc", "/openapi.json",
        "/auth/login", "/auth/register",
        "/files", "/file-content",
    }
    if (
        request.method == "OPTIONS"
        or request.url.path in open_paths
        or request.url.path.startswith("/api/plugin-marketplace/")
        or request.url.path.startswith("/static/")
        or request.url.path.startswith("/vendor/")
        or request.url.path == "/favicon.ico"
    ):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Yetkisiz erişim"}, status_code=401)

    token = auth_header[7:].strip()
    if not token:
        return JSONResponse({"error": "Geçersiz token"}, status_code=401)

    user = await _resolve_user_from_token(None, token)
    if not user:
        return JSONResponse({"error": "Oturum geçersiz veya süresi dolmuş"}, status_code=401)

    agent = await _await_if_needed(_resolve_agent_instance())
    request.state.user = user
    set_active_user = getattr(agent.memory, "set_active_user", None)
    if callable(set_active_user):
        await set_active_user(user.id, user.username)
    token = set_current_metrics_user_id(user.id)
    try:
        return await call_next(request)
    finally:
        reset_current_metrics_user_id(token)


# ─────────────────────────────────────────────
#  OBSERVABILITY (OpenTelemetry)
# ─────────────────────────────────────────────
def _setup_tracing() -> None:
    if hasattr(cfg, "init_telemetry"):
        cfg.init_telemetry(
            service_name=getattr(cfg, "OTEL_SERVICE_NAME", "sidar-web"),
            fastapi_app=app,
            logger_obj=logger,
            trace_module=trace,
            otlp_exporter_cls=OTLPSpanExporter,
            tracer_provider_cls=TracerProvider,
            resource_cls=Resource,
            batch_span_processor_cls=BatchSpanProcessor,
            fastapi_instrumentor_cls=FastAPIInstrumentor,
            httpx_instrumentor_cls=HTTPXClientInstrumentor,
        )
        return

    if not getattr(cfg, "ENABLE_TRACING", False):
        return
    if trace is None:
        logger.warning("OpenTelemetry trace modülü bulunamadı; tracing kapalı.")
        return
    resource = Resource.create({"service.name": getattr(cfg, "OTEL_SERVICE_NAME", "sidar-web")})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=cfg.OTEL_EXPORTER_ENDPOINT, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    with contextlib.suppress(Exception):
        HTTPXClientInstrumentor().instrument()
    logger.info("✅ OpenTelemetry aktif: %s", cfg.OTEL_EXPORTER_ENDPOINT)


_setup_tracing()

def _get_request_user(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Yetkisiz erişim")
    return user


def _is_admin_user(user) -> bool:
    role = str(getattr(user, "role", "") or "").strip().lower()
    username = str(getattr(user, "username", "") or "").strip()
    return role == "admin" or username == "default_admin"


def _require_admin_user(user=Depends(_get_request_user)):
    if not _is_admin_user(user):
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekiyor")
    return user


def _require_metrics_access(request: Request, user=Depends(_get_request_user)):
    """Metrics endpoint'lerine erişim: admin kullanıcı VEYA geçerli METRICS_TOKEN."""
    metrics_token = str(getattr(cfg, "METRICS_TOKEN", "") or "").strip()
    if metrics_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and auth_header[7:].strip() == metrics_token:
            return user
    if _is_admin_user(user):
        return user
    raise HTTPException(status_code=403, detail="Metrics erişimi için admin yetkisi veya METRICS_TOKEN gerekiyor")


def _get_user_tenant(user) -> str:
    return str(getattr(user, "tenant_id", "default") or "default").strip() or "default"


def _serialize_policy(record) -> dict:
    return {
        "id": int(getattr(record, "id", 0) or 0),
        "user_id": str(getattr(record, "user_id", "") or ""),
        "tenant_id": str(getattr(record, "tenant_id", "default") or "default"),
        "resource_type": str(getattr(record, "resource_type", "") or ""),
        "resource_id": str(getattr(record, "resource_id", "*") or "*"),
        "action": str(getattr(record, "action", "") or ""),
        "effect": str(getattr(record, "effect", "allow") or "allow"),
        "created_at": str(getattr(record, "created_at", "") or ""),
        "updated_at": str(getattr(record, "updated_at", "") or ""),
    }


def _resolve_policy_from_request(request: Request) -> tuple[str, str, str]:
    path = request.url.path
    if path.startswith("/rag/"):
        action = "read" if request.method == "GET" else "write"
        resource_id = path.rsplit("/", 1)[-1] if request.method == "DELETE" else "*"
        return ("rag", action, resource_id)
    if path.startswith("/github-") or path == "/set-repo":
        action = "read" if request.method == "GET" else "write"
        return ("github", action, "*")
    if path.startswith("/api/agents/register"):
        return ("agents", "register", "*")
    if path.startswith("/api/swarm/"):
        return ("swarm", "execute", "*")
    if path.startswith("/admin/"):
        return ("admin", "manage", "*")
    if path.startswith("/ws/"):
        return ("swarm", "execute", "*")
    return ("", "", "")


def _build_audit_resource(resource_type: str, resource_id: str) -> str:
    r_type = (resource_type or "").strip().lower()
    r_id = (resource_id or "*").strip() or "*"
    if not r_type:
        return ""
    return f"{r_type}:{r_id}"


def _schedule_access_audit_log(
    *,
    user: Any,
    resource_type: str,
    action: str,
    resource_id: str,
    ip_address: str,
    allowed: bool,
) -> None:
    resource = _build_audit_resource(resource_type, resource_id)
    if not resource:
        return

    async def _persist() -> None:
        try:
            agent = await _resolve_agent_instance()
            recorder = getattr(agent.memory.db, "record_audit_log", None)
            if recorder is None:
                return
            await recorder(
                user_id=str(getattr(user, "id", "") or ""),
                tenant_id=_get_user_tenant(user),
                action=action,
                resource=resource,
                ip_address=ip_address,
                allowed=allowed,
            )
        except Exception as exc:
            logger.debug("ACL audit log yazımı atlandı: %s", exc)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_persist())
    except RuntimeError:
        logger.debug("ACL audit log planlanamadı: event loop yok.")


class _RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    tenant_id: str = Field(default="default", min_length=1, max_length=64)


class _LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class _PromptUpsertRequest(BaseModel):
    role_name: str = Field(..., min_length=1, max_length=64)
    prompt_text: str = Field(..., min_length=1)
    activate: bool = Field(default=True)


class _PromptActivateRequest(BaseModel):
    prompt_id: int = Field(..., gt=0)


class _PolicyUpsertRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    tenant_id: str = Field(default="default", min_length=1, max_length=64)
    resource_type: str = Field(..., min_length=1, max_length=64)
    resource_id: str = Field(default="*", min_length=1, max_length=256)
    action: str = Field(..., min_length=1, max_length=64)
    effect: str = Field(default="allow", min_length=1, max_length=8)


class _AgentPluginRegisterRequest(BaseModel):
    role_name: str = Field(..., min_length=2, max_length=64)
    source_code: str = Field(..., min_length=1)
    class_name: str | None = Field(default=None, min_length=1, max_length=128)
    capabilities: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=512)
    version: str = Field(default="1.0.0", max_length=32)


class _PluginMarketplaceInstallRequest(BaseModel):
    plugin_id: str = Field(..., min_length=2, max_length=64)


class _SwarmTaskRequest(BaseModel):
    goal: str = Field(..., min_length=1)
    intent: str = Field(default="mixed", min_length=1, max_length=64)
    context: dict[str, str] = Field(default_factory=dict)
    preferred_agent: str | None = Field(default=None, max_length=64)


class _SwarmExecuteRequest(BaseModel):
    mode: str = Field(default="parallel", pattern="^(parallel|pipeline)$")
    tasks: list[_SwarmTaskRequest] = Field(..., min_length=1)
    session_id: str = Field(default="", max_length=128)
    max_concurrency: int = Field(default=4, ge=1, le=16)


def _serialize_prompt(record) -> dict:
    prompt_id = getattr(record, "id", 0)
    try:
        serialized_id = int(prompt_id)
    except (TypeError, ValueError):
        serialized_id = str(prompt_id or "")

    return {
        "id": serialized_id,
        "role_name": str(getattr(record, "role_name", "") or ""),
        "prompt_text": str(getattr(record, "prompt_text", "") or ""),
        "version": int(getattr(record, "version", 1) or 1),
        "is_active": bool(getattr(record, "is_active", False)),
        "created_at": str(getattr(record, "created_at", "") or ""),
        "updated_at": str(getattr(record, "updated_at", "") or ""),
    }


def _serialize_swarm_result(record) -> dict:
    return {
        "task_id": str(getattr(record, "task_id", "") or ""),
        "agent_role": str(getattr(record, "agent_role", "") or ""),
        "status": str(getattr(record, "status", "") or ""),
        "summary": str(getattr(record, "summary", "") or ""),
        "elapsed_ms": int(getattr(record, "elapsed_ms", 0) or 0),
        "evidence": list(getattr(record, "evidence", []) or []),
        "handoffs": list(getattr(record, "handoffs", []) or []),
        "graph": dict(getattr(record, "graph", {}) or {}),
    }


def _serialize_campaign(record) -> dict[str, Any]:
    return {
        "id": int(getattr(record, "id", 0) or 0),
        "tenant_id": str(getattr(record, "tenant_id", "default") or "default"),
        "name": str(getattr(record, "name", "") or ""),
        "channel": str(getattr(record, "channel", "") or ""),
        "objective": str(getattr(record, "objective", "") or ""),
        "status": str(getattr(record, "status", "draft") or "draft"),
        "owner_user_id": str(getattr(record, "owner_user_id", "") or ""),
        "budget": float(getattr(record, "budget", 0.0) or 0.0),
        "metadata_json": str(getattr(record, "metadata_json", "{}") or "{}"),
        "created_at": str(getattr(record, "created_at", "") or ""),
        "updated_at": str(getattr(record, "updated_at", "") or ""),
    }


def _serialize_content_asset(record) -> dict[str, Any]:
    return {
        "id": int(getattr(record, "id", 0) or 0),
        "campaign_id": int(getattr(record, "campaign_id", 0) or 0),
        "tenant_id": str(getattr(record, "tenant_id", "default") or "default"),
        "asset_type": str(getattr(record, "asset_type", "") or ""),
        "title": str(getattr(record, "title", "") or ""),
        "content": str(getattr(record, "content", "") or ""),
        "channel": str(getattr(record, "channel", "") or ""),
        "metadata_json": str(getattr(record, "metadata_json", "{}") or "{}"),
        "created_at": str(getattr(record, "created_at", "") or ""),
        "updated_at": str(getattr(record, "updated_at", "") or ""),
    }


def _serialize_operation_checklist(record) -> dict[str, Any]:
    campaign_id = getattr(record, "campaign_id", None)
    return {
        "id": int(getattr(record, "id", 0) or 0),
        "campaign_id": None if campaign_id is None else int(campaign_id),
        "tenant_id": str(getattr(record, "tenant_id", "default") or "default"),
        "title": str(getattr(record, "title", "") or ""),
        "items_json": str(getattr(record, "items_json", "[]") or "[]"),
        "status": str(getattr(record, "status", "pending") or "pending"),
        "owner_user_id": str(getattr(record, "owner_user_id", "") or ""),
        "created_at": str(getattr(record, "created_at", "") or ""),
        "updated_at": str(getattr(record, "updated_at", "") or ""),
    }


_PLUGIN_ROLE_RE = re.compile(r"^[a-zA-Z0-9_-]{2,64}$")


def _validate_plugin_role_name(role_name: str) -> str:
    normalized = (role_name or "").strip().lower()
    if not _PLUGIN_ROLE_RE.match(normalized):
        raise HTTPException(status_code=400, detail="Geçersiz role_name")
    return normalized


def _sanitize_capabilities(capabilities: list[str] | None) -> list[str]:
    if not capabilities:
        return []
    return [c.strip() for c in capabilities if str(c).strip()]


def _plugin_source_filename(module_label: str) -> str:
    safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", (module_label or "").strip()) or "plugin"
    return f"<sidar-plugin:{safe_label}>"


def _load_plugin_agent_class(source_code: str, class_name: str | None, module_label: str) -> type[BaseAgent]:
    def _is_baseagent_derived(candidate: Any) -> bool:
        if not inspect.isclass(candidate):
            return False
        try:
            if issubclass(candidate, BaseAgent):
                return candidate is not BaseAgent
        except TypeError:
            return False
        # Bazı ortamlarda BaseAgent birden fazla modül kimliğiyle yüklenebilir.
        # Bu durumda isim bazlı MRO kontrolü ile eşdeğer türevleri yakalayalım.
        return any(getattr(base, "__name__", "") == "BaseAgent" for base in inspect.getmro(candidate)[1:])

    namespace = {"__name__": module_label}
    try:
        exec(compile(source_code, _plugin_source_filename(module_label), "exec"), namespace)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Plugin kodu derlenemedi/çalıştırılamadı: {exc}") from exc

    if class_name:
        candidate = namespace.get(class_name)
        if not inspect.isclass(candidate):
            raise HTTPException(status_code=400, detail=f"Belirtilen sınıf bulunamadı: {class_name}")
        if not _is_baseagent_derived(candidate):
            raise HTTPException(status_code=400, detail="Plugin sınıfı BaseAgent türetmelidir")
        return candidate

    discovered: list[type[BaseAgent]] = []
    for obj in namespace.values():
        if _is_baseagent_derived(obj):
            discovered.append(obj)

    if not discovered:
        raise HTTPException(status_code=400, detail="Plugin içinde BaseAgent türevi bir sınıf bulunamadı")
    return discovered[0]


def _persist_and_import_plugin_file(filename: str, data: bytes, module_label: str) -> Path:
    safe_name = Path(filename or "plugin.py").name
    if not safe_name.endswith(".py"):
        safe_name = f"{safe_name}.py"

    plugins_dir = Path("plugins")
    plugins_dir.mkdir(parents=True, exist_ok=True)
    plugin_path = plugins_dir / safe_name
    plugin_path.write_bytes(data)

    spec = importlib.util.spec_from_file_location(module_label, plugin_path)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=400, detail="Plugin modülü import edilemedi")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Plugin dosyası import edilemedi: {exc}") from exc
    return plugin_path


PLUGIN_SOURCE_DIR = Path(__file__).parent / "plugins"


PLUGIN_MARKETPLACE_CATALOG: dict[str, dict[str, Any]] = {
    "aws_management": {
        "plugin_id": "aws_management",
        "name": "AWS Operations Agent",
        "summary": "EC2, S3 ve CloudWatch keşfi için hot-load edilebilen AWS operasyon ajanı.",
        "description": (
            "AWS CLI veya boto3 kuruluysa temel envanter ve operasyon komutlarını "
            "yerinde çalıştırır; yoksa gerekli kurulum adımlarını açıklar."
        ),
        "role_name": "aws_management",
        "class_name": "AWSManagementAgent",
        "capabilities": ["aws_management", "cloud_ops", "infra_observability"],
        "version": "1.0.0",
        "category": "Cloud",
        "entrypoint": PLUGIN_SOURCE_DIR / "aws_management_agent.py",
    },
    "slack_notifications": {
        "plugin_id": "slack_notifications",
        "name": "Slack Notification Agent",
        "summary": "Webhook veya bot token ile Slack bildirimleri gönderen ajan.",
        "description": (
            "Slack webhook/bot ayarlarını kullanarak anlık durum güncellemesi, "
            "incident bildirimi ve kanal mesajı akışlarını tetikler."
        ),
        "role_name": "slack_notifications",
        "class_name": "SlackNotificationAgent",
        "capabilities": ["slack_notification", "notifications", "ops_alerting"],
        "version": "1.0.0",
        "category": "Collaboration",
        "entrypoint": PLUGIN_SOURCE_DIR / "slack_notification_agent.py",
    },
}


def _plugin_marketplace_state_path() -> Path:
    plugins_dir = Path("plugins")
    plugins_dir.mkdir(parents=True, exist_ok=True)
    return plugins_dir / ".marketplace_state.json"


def _read_plugin_marketplace_state() -> dict[str, Any]:
    path = _plugin_marketplace_state_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Plugin marketplace state okunamadı: %s", path)
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _write_plugin_marketplace_state(state: dict[str, Any]) -> None:
    path = _plugin_marketplace_state_path()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _get_plugin_marketplace_entry(plugin_id: str) -> dict[str, Any]:
    normalized = (plugin_id or "").strip().lower()
    entry = PLUGIN_MARKETPLACE_CATALOG.get(normalized)
    if not entry:
        raise HTTPException(status_code=404, detail="Plugin marketplace girdisi bulunamadı")
    return entry


def _serialize_marketplace_plugin(plugin_id: str, *, installed_state: dict[str, Any] | None = None) -> dict[str, Any]:
    entry = _get_plugin_marketplace_entry(plugin_id)
    state = installed_state or _read_plugin_marketplace_state().get(plugin_id, {})
    spec = AgentRegistry.get(str(entry["role_name"]))
    installed = bool(state)
    entrypoint = Path(entry["entrypoint"])
    return {
        "plugin_id": str(entry["plugin_id"]),
        "name": str(entry["name"]),
        "summary": str(entry["summary"]),
        "description": str(entry["description"]),
        "category": str(entry["category"]),
        "role_name": str(entry["role_name"]),
        "class_name": str(entry["class_name"]),
        "capabilities": list(entry.get("capabilities", []) or []),
        "version": str(entry["version"]),
        "entrypoint": str(entrypoint),
        "entrypoint_exists": bool(entrypoint.exists()),
        "installed": installed,
        "installed_at": str(state.get("installed_at", "") or ""),
        "last_reloaded_at": str(state.get("last_reloaded_at", "") or ""),
        "live_registered": spec is not None,
        "agent": None if spec is None else {
            "role_name": str(getattr(spec, "role_name", entry["role_name"])),
            "description": str(getattr(spec, "description", entry["description"])),
            "capabilities": list(getattr(spec, "capabilities", entry.get("capabilities", [])) or []),
            "version": str(getattr(spec, "version", entry["version"])),
            "is_builtin": bool(getattr(spec, "is_builtin", False)),
        },
    }


def _install_marketplace_plugin(plugin_id: str, *, persist: bool = True) -> dict[str, Any]:
    entry = _get_plugin_marketplace_entry(plugin_id)
    source_path = Path(entry["entrypoint"])
    if not source_path.exists():
        raise HTTPException(status_code=500, detail=f"Plugin kaynağı bulunamadı: {source_path}")
    source_code = source_path.read_text(encoding="utf-8")
    AgentRegistry.unregister(str(entry["role_name"]))
    agent_meta = _register_plugin_agent(
        role_name=str(entry["role_name"]),
        source_code=source_code,
        class_name=str(entry["class_name"]),
        capabilities=list(entry.get("capabilities", []) or []),
        description=str(entry["description"]),
        version=str(entry["version"]),
    )
    if persist:
        state = _read_plugin_marketplace_state()
        now = datetime.now(timezone.utc).isoformat()
        previous = dict(state.get(plugin_id, {}) or {})
        previous.update({
            "installed_at": previous.get("installed_at") or now,
            "last_reloaded_at": now,
            "role_name": str(entry["role_name"]),
            "entrypoint": str(source_path),
        })
        state[plugin_id] = previous
        _write_plugin_marketplace_state(state)
    return {
        "success": True,
        "plugin": _serialize_marketplace_plugin(plugin_id),
        "agent": agent_meta,
    }


def _uninstall_marketplace_plugin(plugin_id: str) -> dict[str, Any]:
    entry = _get_plugin_marketplace_entry(plugin_id)
    removed = AgentRegistry.unregister(str(entry["role_name"]))
    state = _read_plugin_marketplace_state()
    state.pop(plugin_id, None)
    _write_plugin_marketplace_state(state)
    return {
        "success": True,
        "removed": removed,
        "plugin": _serialize_marketplace_plugin(plugin_id),
    }


def _reload_persisted_marketplace_plugins() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for plugin_id in list(_read_plugin_marketplace_state().keys()):
        if plugin_id not in PLUGIN_MARKETPLACE_CATALOG:
            continue
        try:
            results.append(_install_marketplace_plugin(plugin_id))
        except HTTPException as exc:
            logger.warning("Marketplace plugin '%s' yeniden yüklenemedi: %s", plugin_id, exc.detail)
        except Exception as exc:
            logger.warning("Marketplace plugin '%s' yeniden yüklenemedi: %s", plugin_id, exc)
    return results


def _register_plugin_agent(
    *,
    role_name: str,
    source_code: str,
    class_name: str | None,
    capabilities: list[str] | None,
    description: str,
    version: str,
) -> dict:
    normalized_role = _validate_plugin_role_name(role_name)
    module_label = f"sidar_plugin_{normalized_role}_{secrets.token_hex(4)}"
    plugin_cls = _load_plugin_agent_class(source_code, class_name, module_label)
    plugin_description = (description or "").strip() or (plugin_cls.__doc__ or "").strip().split("\n")[0]

    AgentRegistry.register_type(
        role_name=normalized_role,
        agent_class=plugin_cls,
        capabilities=_sanitize_capabilities(capabilities),
        description=plugin_description,
        version=(version or "1.0.0").strip() or "1.0.0",
        is_builtin=False,
    )
    spec = AgentRegistry.get(normalized_role)
    return {
        "role_name": normalized_role,
        "class_name": plugin_cls.__name__,
        "capabilities": list(spec.capabilities if spec else []),
        "description": str(spec.description if spec else plugin_description),
        "version": str(spec.version if spec else version),
        "is_builtin": bool(spec.is_builtin if spec else False),
    }


@app.post("/auth/register")
async def register_user(payload: _RegisterRequest):
    username = payload.username.strip()
    password = payload.password
    tenant_id = payload.tenant_id.strip() or "default"
    if len(username) < 3 or len(password) < 6:
        raise HTTPException(status_code=400, detail="Geçersiz kullanıcı adı veya şifre")

    agent = await _resolve_agent_instance()
    try:
        user = await agent.memory.db.register_user(username=username, password=password, tenant_id=tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Kullanıcı oluşturulamadı: {exc}") from exc

    token = await _issue_auth_token(agent, user)
    return JSONResponse({"user": {"id": user.id, "username": user.username, "role": user.role}, "access_token": token})


@app.post("/auth/login")
async def login_user(payload: _LoginRequest):
    username = payload.username.strip()
    password = payload.password
    agent = await _resolve_agent_instance()
    try:
        user = await agent.memory.db.authenticate_user(username=username, password=password)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Veritabanı hatası nedeniyle giriş yapılamadı") from exc
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya şifre hatalı")

    token = await _issue_auth_token(agent, user)
    return JSONResponse({"user": {"id": user.id, "username": user.username, "role": user.role}, "access_token": token})


@app.get("/auth/me")
async def auth_me(request: Request, user=Depends(_get_request_user)):
    return JSONResponse({"id": user.id, "username": user.username, "role": user.role})


@app.get("/admin/stats")
async def admin_stats(_user=Depends(_require_admin_user)):
    agent = await _resolve_agent_instance()
    stats = await agent.memory.db.get_admin_stats()
    return JSONResponse(stats)


@app.get("/admin/prompts")
async def admin_list_prompts(role_name: str = "", _user=Depends(_require_admin_user)):
    agent = await _resolve_agent_instance()
    prompts = await agent.memory.db.list_prompts(role_name=role_name.strip() or None)
    return JSONResponse({"items": [_serialize_prompt(p) for p in prompts]})


@app.get("/admin/prompts/active")
async def admin_active_prompt(role_name: str = "system", _user=Depends(_require_admin_user)):
    agent = await _resolve_agent_instance()
    active = await agent.memory.db.get_active_prompt(role_name)
    if not active:
        raise HTTPException(status_code=404, detail="Aktif prompt bulunamadı")
    return JSONResponse(_serialize_prompt(active))


@app.post("/admin/prompts")
async def admin_upsert_prompt(payload: _PromptUpsertRequest, _user=Depends(_require_admin_user)):
    role_name = (payload.role_name or "").strip().lower()
    prompt_text = (payload.prompt_text or "").strip()
    if not role_name or not prompt_text:
        raise HTTPException(status_code=400, detail="role_name ve prompt_text zorunludur")

    agent = await _await_if_needed(_resolve_agent_instance())
    record = await agent.memory.db.upsert_prompt(role_name=role_name, prompt_text=prompt_text, activate=bool(payload.activate))
    if role_name == "system" and bool(record.is_active):
        agent.system_prompt = record.prompt_text
    return JSONResponse(_serialize_prompt(record))


@app.post("/admin/prompts/activate")
async def admin_activate_prompt(payload: _PromptActivateRequest, _user=Depends(_require_admin_user)):
    agent = await _await_if_needed(_resolve_agent_instance())
    active = await agent.memory.db.activate_prompt(payload.prompt_id)
    if not active:
        raise HTTPException(status_code=404, detail="Prompt kaydı bulunamadı")
    if active.role_name == "system":
        agent.system_prompt = active.prompt_text
    return JSONResponse(_serialize_prompt(active))


@app.get("/admin/policies/{user_id}")
async def admin_list_policies(user_id: str, tenant_id: str = "", _user=Depends(_require_admin_user)):
    agent = await _resolve_agent_instance()
    records = await agent.memory.db.list_access_policies(user_id=user_id, tenant_id=tenant_id.strip() or None)
    return JSONResponse({"items": [_serialize_policy(r) for r in records]})


@app.post("/admin/policies")
async def admin_upsert_policy(payload: _PolicyUpsertRequest, _user=Depends(_require_admin_user)):
    agent = await _resolve_agent_instance()
    await agent.memory.db.upsert_access_policy(
        user_id=payload.user_id.strip(),
        tenant_id=payload.tenant_id.strip() or "default",
        resource_type=payload.resource_type.strip().lower(),
        resource_id=payload.resource_id.strip() or "*",
        action=payload.action.strip().lower(),
        effect=payload.effect.strip().lower(),
    )
    records = await agent.memory.db.list_access_policies(user_id=payload.user_id.strip(), tenant_id=payload.tenant_id.strip() or "default")
    return JSONResponse({"success": True, "items": [_serialize_policy(r) for r in records]})


@app.post("/api/agents/register")
async def register_agent_plugin(payload: _AgentPluginRegisterRequest, _user=Depends(_require_admin_user)):
    result = _register_plugin_agent(
        role_name=payload.role_name,
        source_code=payload.source_code,
        class_name=payload.class_name,
        capabilities=payload.capabilities,
        description=payload.description,
        version=payload.version,
    )
    return JSONResponse({"success": True, "agent": result})


@app.post("/api/agents/register-file")
async def register_agent_plugin_file(
    file: UploadFile = File(...),
    role_name: str = "",
    class_name: str = "",
    capabilities: str = "",
    description: str = "",
    version: str = "1.0.0",
    _user=Depends(_require_admin_user),
):
    data = await file.read()
    await file.close()
    if not data:
        raise HTTPException(status_code=400, detail="Yüklü dosya boş")
    if len(data) > MAX_FILE_CONTENT_BYTES:
        raise HTTPException(status_code=413, detail="Dosya çok büyük")
    try:
        source_code = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Plugin dosyası UTF-8 olmalıdır") from exc

    parsed_capabilities = [c.strip() for c in capabilities.split(",") if c.strip()]
    target_role_name = role_name.strip() or Path(file.filename or "").stem
    module_label = f"sidar_uploaded_plugin_{secrets.token_hex(4)}"
    _persist_and_import_plugin_file(file.filename or target_role_name, data, module_label)
    result = _register_plugin_agent(
        role_name=target_role_name,
        source_code=source_code,
        class_name=class_name.strip() or None,
        capabilities=parsed_capabilities,
        description=description,
        version=version,
    )
    return JSONResponse({"success": True, "agent": result})


@app.get("/api/plugin-marketplace/catalog")
async def plugin_marketplace_catalog(_user=Depends(_require_admin_user)):
    state = _read_plugin_marketplace_state()
    items = [
        _serialize_marketplace_plugin(plugin_id, installed_state=state.get(plugin_id, {}))
        for plugin_id in sorted(PLUGIN_MARKETPLACE_CATALOG)
    ]
    return JSONResponse({"items": items})


@app.post("/api/plugin-marketplace/install")
async def install_plugin_marketplace_item(
    payload: _PluginMarketplaceInstallRequest,
    _user=Depends(_require_admin_user),
):
    return JSONResponse(_install_marketplace_plugin(payload.plugin_id))


@app.post("/api/plugin-marketplace/reload")
async def reload_plugin_marketplace_item(
    payload: _PluginMarketplaceInstallRequest,
    _user=Depends(_require_admin_user),
):
    return JSONResponse(_install_marketplace_plugin(payload.plugin_id))


@app.delete("/api/plugin-marketplace/install/{plugin_id}")
async def uninstall_plugin_marketplace_item(plugin_id: str, _user=Depends(_require_admin_user)):
    return JSONResponse(_uninstall_marketplace_plugin(plugin_id))


@app.post("/api/swarm/execute")
async def execute_swarm(payload: _SwarmExecuteRequest, user=Depends(_get_request_user)):
    agent = await _resolve_agent_instance()
    orchestrator = SwarmOrchestrator(getattr(agent, "cfg", cfg))
    session_id = payload.session_id.strip() or f"swarm-{getattr(user, 'id', 'anon')}"
    tasks = [
        SwarmTask(
            goal=item.goal.strip(),
            intent=item.intent.strip() or "mixed",
            context=dict(item.context or {}),
            preferred_agent=(item.preferred_agent or "").strip() or None,
        )
        for item in payload.tasks
        if item.goal.strip()
    ]
    if not tasks:
        raise HTTPException(status_code=400, detail="En az bir geçerli task gereklidir")

    if payload.mode == "pipeline":
        results = await orchestrator.run_pipeline(tasks, session_id=session_id)
    else:
        results = await orchestrator.run_parallel(
            tasks,
            session_id=session_id,
            max_concurrency=payload.max_concurrency,
        )

    return JSONResponse({
        "success": True,
        "mode": payload.mode,
        "session_id": session_id,
        "task_count": len(tasks),
        "results": [_serialize_swarm_result(item) for item in results],
    })


# ─────────────────────────────────────────────
#  HITL — Human-in-the-Loop Onay Geçidi
# ─────────────────────────────────────────────

class _HITLRespondRequest(BaseModel):
    approved: bool
    decided_by: str = "operator"
    rejection_reason: str = ""


@app.get("/api/hitl/pending")
async def hitl_pending(user=Depends(_get_request_user)):
    """Bekleyen HITL onay isteklerini listeler."""
    store = get_hitl_store()
    pending = await store.pending()
    return JSONResponse({"pending": [r.to_dict() for r in pending], "count": len(pending)})


@app.post("/api/hitl/request")
async def hitl_create_request(payload: dict, user=Depends(_get_request_user)):
    """Yeni bir HITL onay isteği oluşturur (iç API / test amaçlı)."""
    gate = get_hitl_gate()
    action = str(payload.get("action", "manual")).strip()
    description = str(payload.get("description", "Manuel onay isteği")).strip()
    hitl_payload = dict(payload.get("payload") or {})
    requested_by = str(payload.get("requested_by", getattr(user, "username", "api"))).strip()

    import time
    import uuid

    from core.hitl import HITLRequest, notify
    from core.hitl import get_hitl_store as _store
    now = time.time()
    req = HITLRequest(
        request_id=str(uuid.uuid4()),
        action=action,
        description=description,
        payload=hitl_payload,
        requested_by=requested_by,
        created_at=now,
        expires_at=now + gate.timeout,
    )
    await _store().add(req)
    await notify(req)
    return JSONResponse({"request_id": req.request_id, "expires_at": req.expires_at})


@app.post("/api/hitl/respond/{request_id}")
async def hitl_respond(request_id: str, payload: _HITLRespondRequest, user=Depends(_get_request_user)):
    """Bir HITL isteğini onayla veya reddet."""
    gate = get_hitl_gate()
    decided_by = payload.decided_by or getattr(user, "username", "operator")
    req = await gate.respond(
        request_id,
        approved=payload.approved,
        decided_by=decided_by,
        rejection_reason=payload.rejection_reason,
    )
    if req is None:
        raise HTTPException(status_code=404, detail="HITL isteği bulunamadı")
    return JSONResponse({"request_id": req.request_id, "decision": req.decision.value})


@app.middleware("http")
async def access_policy_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    user = getattr(request.state, "user", None)
    if not user:
        return await call_next(request)
    resource_type, action, resource_id = _resolve_policy_from_request(request)
    if not resource_type:
        return await call_next(request)
    client_ip = _get_client_ip(request)
    if _is_admin_user(user):
        _schedule_access_audit_log(
            user=user,
            resource_type=resource_type,
            action=action,
            resource_id=resource_id,
            ip_address=client_ip,
            allowed=True,
        )
        return await call_next(request)

    allowed = False
    try:
        agent = await _resolve_agent_instance()
        checker = getattr(agent.memory.db, "check_access_policy", None)
        if checker is None:
            allowed = True
        else:
            allowed = await checker(
                user_id=str(getattr(user, "id", "") or ""),
                tenant_id=_get_user_tenant(user),
                resource_type=resource_type,
                action=action,
                resource_id=resource_id,
            )
    except Exception as exc:
        logger.warning("ACL kontrolü başarısız (%s), erişim reddedildi.", exc)
        allowed = False

    _schedule_access_audit_log(
        user=user,
        resource_type=resource_type,
        action=action,
        resource_id=resource_id,
        ip_address=client_ip,
        allowed=allowed,
    )
    if not allowed:
        return JSONResponse(status_code=403, content={"error": "Yetki yok", "resource": resource_type, "action": action})
    return await call_next(request)


# ─────────────────────────────────────────────
#  RATE LIMITING (Redis + local fallback)
# ─────────────────────────────────────────────
RATE_LIMIT_MAX_REQUESTS = 120
RATE_LIMIT_WINDOW_SEC = 60
_RATE_LIMIT = cfg.RATE_LIMIT_CHAT
_RATE_LIMIT_MUTATIONS = cfg.RATE_LIMIT_MUTATIONS
_RATE_LIMIT_GET_IO = cfg.RATE_LIMIT_GET_IO
_RATE_WINDOW = cfg.RATE_LIMIT_WINDOW
_RATE_GET_IO_PATHS = (
    "/git-info", "/git-branches", "/files", "/file-content",
    "/github-prs", "/github-repos", "/todo", "/rag/", "/sessions",
)

_redis_client: Redis | None = None
_redis_lock: asyncio.Lock | None = None
_local_rate_limits: dict[str, list[float]] = {}
_local_rate_lock: asyncio.Lock | None = None

# Test temizliği için takma ad; _local_rate_limits ile aynı sözlük nesnesini paylaşır
_rate_data: dict[str, list[float]] = _local_rate_limits

_start_time = time.monotonic()  # Sunucu başlangıç zamanı (/metrics için)


async def _get_redis() -> Redis | None:
    global _redis_client, _redis_lock
    if _redis_client is None:
        if _redis_lock is None:
            _redis_lock = asyncio.Lock()
        async with _redis_lock:
            if _redis_client is None:
                try:
                    client = Redis.from_url(
                        cfg.REDIS_URL,
                        encoding="utf-8",
                        decode_responses=True,
                        max_connections=max(1, int(getattr(cfg, "REDIS_MAX_CONNECTIONS", 50) or 50)),
                    )
                    await client.ping()
                    _redis_client = client
                except Exception as exc:
                    logger.warning("Redis bağlantısı kurulamadı (%s). Local rate limit fallback kullanılacak.", exc)
                    _redis_client = None
    return _redis_client


async def _local_is_rate_limited(key: str, limit: int, window_sec: int) -> bool:
    global _local_rate_lock
    if _local_rate_lock is None:
        _local_rate_lock = asyncio.Lock()

    now = time.time()
    async with _local_rate_lock:
        timestamps = _local_rate_limits.get(key, [])
        valid = [t for t in timestamps if now - t < window_sec]
        if len(valid) >= limit:
            _local_rate_limits[key] = valid
            return True
        valid.append(now)
        _local_rate_limits[key] = valid
        return False


async def _is_rate_limited(key: str, limit: int, window_sec: int = 60) -> bool:
    """Testler ve doğrudan çağrılar için yerel hız sınırlayıcıya basit erişim noktası."""
    return await _local_is_rate_limited(key, limit, window_sec)


async def _redis_is_rate_limited(namespace: str, key: str, limit: int, window_sec: int) -> bool:
    redis = await _get_redis()
    bucket = int(time.time() // window_sec)
    redis_key = f"sidar:rl:{namespace}:{key}:{bucket}"

    if redis is None:
        return await _local_is_rate_limited(redis_key, limit, window_sec)

    try:
        count = await redis.incr(redis_key)
        if count == 1:
            await redis.expire(redis_key, window_sec + 2)
        return count > limit
    except Exception as exc:
        logger.warning("Redis rate limit komutu başarısız (%s). Local fallback kullanılacak.", exc)
        return await _local_is_rate_limited(redis_key, limit, window_sec)


def _get_client_ip(request: Request) -> str:
    """İstemci IP'sini döndürür.

    Proxy başlıkları (X-Forwarded-For, X-Real-IP) yalnızca direkt bağlantının
    Config.TRUSTED_PROXIES listesindeki bir adresten gelmesi durumunda okunur.
    Bu sayede saldırganın bu başlıkları taklit ederek rate-limit'i atlatması engellenir.
    """
    direct_ip = request.client.host if request.client else "unknown"
    if direct_ip in Config.TRUSTED_PROXIES:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            first_ip = xff.split(",")[0].strip()
            if first_ip:
                return first_ip
        xri = request.headers.get("X-Real-IP", "")
        if xri:
            return xri.strip()
    return direct_ip


@app.middleware("http")
async def ddos_rate_limit_middleware(request: Request, call_next):
    if (
        request.url.path.startswith("/ui/")
        or request.url.path.startswith("/static/")
        or request.url.path in ("/health", "/healthz", "/readyz")
    ):
        return await call_next(request)

    client_ip = _get_client_ip(request)
    if await _redis_is_rate_limited("ddos", client_ip, RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SEC):
        return JSONResponse(
            status_code=429,
            content={"error": "⚠ Rate Limit Aşıldı: Sunucuyu korumak için geçici olarak engellendiniz. Lütfen 1 dakika bekleyip tekrar deneyin."},
        )

    return await call_next(request)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = _get_client_ip(request)

    if request.url.path == "/ws/chat":
        if await _redis_is_rate_limited("chat", client_ip, _RATE_LIMIT, _RATE_WINDOW):
            return JSONResponse({"error": "Çok fazla istek. Lütfen bir dakika bekleyin."}, status_code=429)
    elif request.method in ("POST", "DELETE"):
        if await _redis_is_rate_limited("mut", client_ip, _RATE_LIMIT_MUTATIONS, _RATE_WINDOW):
            return JSONResponse({"error": "Çok fazla işlem isteği. Lütfen bir dakika bekleyin."}, status_code=429)
    elif request.method == "GET":
        if any(request.url.path.startswith(p) for p in _RATE_GET_IO_PATHS):
            if await _redis_is_rate_limited("get", client_ip, _RATE_LIMIT_GET_IO, _RATE_WINDOW):
                return JSONResponse({"error": "Çok fazla sorgu isteği. Lütfen bir dakika bekleyin."}, status_code=429)

    response = await call_next(request)
    return response


async def _close_redis_client() -> None:
    global _redis_client
    if _redis_client is not None:
        try:
            closer = getattr(_redis_client, "aclose", None)
            if closer is None:
                close_fn = getattr(_redis_client, "close", None)
                if callable(close_fn):
                    await _await_if_needed(close_fn())
            else:
                await _await_if_needed(closer())
        except RuntimeError as exc:
            # Bazı test teardown senaryolarında (özellikle lifespan kapanışında)
            # redis istemcisinin bağlı olduğu event loop kapanmış olabilir.
            # Bu durumda sessizce temizleyip kapanış akışını bozmamayı tercih ediyoruz.
            if "Event loop is closed" not in str(exc):
                raise
            logger.debug("Redis istemcisi event loop kapandıktan sonra kapatılmaya çalışıldı: %s", exc)
        _redis_client = None


# CORS: localhost/loopback kökenlerine porttan bağımsız izin ver.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$",
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

# React SPA yalnızca web_ui_react/dist üzerinden sunulur.
REACT_DIST_DIR = Path(__file__).parent / "web_ui_react" / "dist"
WEB_DIR = REACT_DIST_DIR


def _make_static_files(directory: Path):
    """FastAPI StaticFiles nesnesini dist dizini eksik olsa bile güvenli üret."""
    try:
        return StaticFiles(directory=directory, check_dir=False)
    except TypeError:
        return StaticFiles(directory=directory)


def _mount_frontend_static_routes(target_app: FastAPI, web_dir: Path) -> None:
    """Frontend statik dosya rotalarını uygular."""
    target_app.mount("/static", _make_static_files(web_dir), name="static")
    assets_dir = web_dir / "assets"
    if assets_dir.exists():
        target_app.mount("/assets", _make_static_files(assets_dir), name="assets")


# React build çıktısı /static altında servis edilir.
_mount_frontend_static_routes(app, WEB_DIR)



# ─────────────────────────────────────────────
#  ROTALAR
# ─────────────────────────────────────────────

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Tarayıcının favicon isteğini 404 hatası vermeden sessizce (204) geçiştirir."""
    return Response(status_code=204)


@app.get("/vendor/{file_path:path}", include_in_schema=False)
async def serve_vendor(file_path: str):
    """React dist altındaki vendor kütüphanelerini servis eder."""
    vendor_dir = (WEB_DIR / "vendor").resolve()
    safe_path = (vendor_dir / file_path).resolve()
    if not str(safe_path).startswith(str(vendor_dir)):
        return Response(status_code=403)
    if not safe_path.exists():
        return Response(status_code=404)
    return FileResponse(safe_path)


@app.get("/", response_class=HTMLResponse)
async def index():
    """Ana sayfa — React SPA build çıktısı."""
    html_file = WEB_DIR / "index.html"
    if not html_file.exists():
        return HTMLResponse(
            "<h1>Hata: React dist bulunamadı. web_ui_react içinde npm run build çalıştırın.</h1>",
            status_code=500,
        )
    grafana_url = str(getattr(cfg, "GRAFANA_URL", "http://localhost:3000") or "http://localhost:3000")
    config_script = (
        f'<script>window.__SIDAR_CONFIG__ = {{"grafanaUrl": {json.dumps(grafana_url)}}};</script>'
    )
    html = html_file.read_text(encoding="utf-8")
    html = html.replace("</head>", f"{config_script}\n</head>", 1)
    return HTMLResponse(html)


async def _ws_close_policy_violation(websocket: WebSocket, reason: str) -> None:
    if hasattr(websocket, "close"):
        await websocket.close(code=1008, reason=reason)


async def _ws_stream_agent_text_response(websocket: WebSocket, agent: SidarAgent, prompt: str) -> None:
    """Agent text çıktısını voice/chat benzeri websocket istemcisine aktar."""
    tool_sentinel = re.compile(r"^\x00TOOL:([^\x00]+)\x00$")
    thought_sentinel = re.compile(r"^\x00THOUGHT:([^\x00]+)\x00$")
    voice_pipeline = getattr(websocket, "_sidar_voice_pipeline", None)
    duplex_state = getattr(websocket, "_sidar_voice_duplex_state", None)
    pending_voice_text = ""

    async def _emit_voice_segments(*, flush: bool = False) -> None:
        nonlocal pending_voice_text
        if not voice_pipeline or not getattr(voice_pipeline, "enabled", False):
            return
        if hasattr(voice_pipeline, "buffer_assistant_text"):
            _turn_id, packets = voice_pipeline.buffer_assistant_text(
                duplex_state,
                pending_voice_text,
                flush=flush,
            )
            pending_voice_text = ""
        else:
            ready_segments, remainder = voice_pipeline.extract_ready_segments(pending_voice_text, flush=flush)
            pending_voice_text = remainder
            packets = [
                {"assistant_turn_id": 0, "audio_sequence": idx, "text": segment}
                for idx, segment in enumerate(ready_segments, start=1)
            ]
        for packet in packets:
            segment = str(packet.get("text", "") or "").strip()
            if not segment:
                continue
            tts_result = await voice_pipeline.synthesize_text(segment)
            if not tts_result.get("success"):
                continue
            audio_bytes = bytes(tts_result.get("audio_bytes") or b"")
            if not audio_bytes:
                continue
            await websocket.send_json(
                {
                    "audio_chunk": base64.b64encode(audio_bytes).decode("ascii"),
                    "audio_text": segment,
                    "audio_mime_type": tts_result.get("mime_type", "audio/wav"),
                    "audio_provider": tts_result.get("provider", ""),
                    "audio_voice": tts_result.get("voice", ""),
                    "assistant_turn_id": int(packet.get("assistant_turn_id", 0) or 0),
                    "audio_sequence": int(packet.get("audio_sequence", 0) or 0),
                }
            )

    async for chunk in agent.respond(prompt):
        m_tool = tool_sentinel.match(chunk)
        m_thought = thought_sentinel.match(chunk)
        if m_tool:
            await websocket.send_json({"tool_call": m_tool.group(1)})
        elif m_thought:
            await websocket.send_json({"thought": m_thought.group(1)})
        else:
            await websocket.send_json({"chunk": chunk})
            if voice_pipeline and getattr(voice_pipeline, "enabled", False):
                pending_voice_text += chunk
                await _emit_voice_segments()

    await _emit_voice_segments(flush=True)


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    Çift yönlü WebSocket chat arayüzü.
    Kullanıcı mesajlarını alır, asenkron LLM yanıtlarını stream eder
    ve anlık iptal (cancel) isteklerini yönetir.

    Kimlik Doğrulama (tercih sırası):
    1. Sec-WebSocket-Protocol başlığı (güvenli — token HTTP upgrade aşamasında taşınır)
    2. İlk JSON mesajı { action: 'auth', token: '...' } (geriye dönük uyumluluk)
    """
    # Sec-WebSocket-Protocol başlığından token'ı oku (JSON payload'dan daha güvenli)
    proto_header = websocket.headers.get("sec-websocket-protocol", "").strip()
    header_token = proto_header or ""

    if header_token:
        # Subprotocol echo-back zorunlu; aksi hâlde tarayıcı bağlantıyı kapatır
        await websocket.accept(subprotocol=header_token)
    else:
        await websocket.accept()

    agent = await _resolve_agent_instance()
    active_task: asyncio.Task | None = None
    ws_user_id = ""
    ws_username = ""
    ws_user_role = "user"
    ws_authenticated = False
    joined_room_id = ""

    # Başlık token'ı varsa bağlantı açılır açılmaz doğrula
    if header_token:
        ws_user = await _await_if_needed(_resolve_user_from_token(agent, header_token))
        if not ws_user:
            await _ws_close_policy_violation(websocket, "Invalid or expired token")
            return
        ws_user_id = ws_user.id
        ws_username = ws_user.username
        ws_user_role = _normalize_collaboration_role(getattr(ws_user, "role", "user"))
        ws_authenticated = True
        await agent.memory.set_active_user(ws_user_id, ws_username)
        with contextlib.suppress(Exception):
            await websocket.send_json({'auth_ok': True})

    async def generate_response(msg: str) -> None:
        sub_id = None
        status_task = None
        stop_status = asyncio.Event()
        ctx_token = set_current_metrics_user_id(ws_user_id) if ws_user_id else None
        try:
            if len(agent.memory) == 0:
                title = msg[:30] + "..." if len(msg) > 30 else msg
                if hasattr(agent.memory, "aupdate_title"):
                    await _await_if_needed(agent.memory.aupdate_title(title))
                else:
                    await _await_if_needed(agent.memory.update_title(title))

            event_bus = get_agent_event_bus()
            sub_id, status_queue = event_bus.subscribe()

            async def _status_pump() -> None:
                while not stop_status.is_set():
                    try:
                        evt = await asyncio.wait_for(status_queue.get(), timeout=0.5)
                    except TimeoutError:
                        continue
                    await websocket.send_json({'status': f"{evt.source}: {evt.message}"})

            status_task = asyncio.create_task(_status_pump())

            _TOOL_SENTINEL = re.compile(r'^\x00TOOL:([^\x00]+)\x00$')
            _THOUGHT_SENTINEL = re.compile(r'^\x00THOUGHT:([^\x00]+)\x00$')

            async for chunk in agent.respond(msg):
                m_tool = _TOOL_SENTINEL.match(chunk)
                m_thought = _THOUGHT_SENTINEL.match(chunk)

                if m_tool:
                    await websocket.send_json({'tool_call': m_tool.group(1)})
                elif m_thought:
                    await websocket.send_json({'thought': m_thought.group(1)})
                else:
                    await websocket.send_json({'chunk': chunk})

            await websocket.send_json({'done': True})
        except asyncio.CancelledError:
            pass
        except LLMAPIError as exc:
            logger.warning("LLM sağlayıcı hatası: provider=%s status=%s retryable=%s", exc.provider, exc.status_code, exc.retryable)
            try:
                await websocket.send_json({'chunk': f"\n[LLM Hatası] {exc.provider} ({exc.status_code or 'n/a'}): {exc}", 'done': True})
            except Exception:
                pass
        except Exception as exc:
            logger.exception("Agent respond hatası: %s", exc)
            try:
                await websocket.send_json({'chunk': f'\n[Sistem Hatası] {exc}', 'done': True})
            except Exception:
                pass
        finally:
            stop_status.set()
            if status_task is not None:
                status_task.cancel()
                with contextlib.suppress(Exception):
                    await status_task
            if sub_id is not None:
                get_agent_event_bus().unsubscribe(sub_id)
            if ctx_token is not None:
                reset_current_metrics_user_id(ctx_token)

    async def generate_room_response(room: _CollaborationRoom, *, actor_name: str, msg: str) -> None:
        sub_id = None
        status_task = None
        stop_status = asyncio.Event()
        request_id = secrets.token_hex(6)
        collaboration_prompt = _build_collaboration_prompt(room, actor_name=actor_name, command=msg)
        ctx_token = set_current_metrics_user_id(ws_user_id) if ws_user_id else None
        try:
            event_bus = get_agent_event_bus()
            sub_id, status_queue = event_bus.subscribe()

            async def _status_pump() -> None:
                while not stop_status.is_set():
                    try:
                        evt = await asyncio.wait_for(status_queue.get(), timeout=0.5)
                    except TimeoutError:
                        continue
                    payload = {
                        "id": secrets.token_hex(8),
                        "room_id": room.room_id,
                        "kind": "status",
                        "source": evt.source,
                        "content": _mask_collaboration_text(evt.message),
                        "ts": _collaboration_now_iso(),
                    }
                    _append_room_telemetry(room, payload)
                    await _broadcast_room_payload(room, {"type": "collaboration_event", "event": payload})

            status_task = asyncio.create_task(_status_pump())
            await _broadcast_room_payload(
                room,
                {
                    "type": "assistant_stream_start",
                    "room_id": room.room_id,
                    "request_id": request_id,
                    "author_name": "SİDAR",
                },
            )
            result = await agent._try_multi_agent(collaboration_prompt)
            for chunk in _iter_stream_chunks(result):
                await _broadcast_room_payload(
                    room,
                    {
                        "type": "assistant_chunk",
                        "room_id": room.room_id,
                        "request_id": request_id,
                        "chunk": _mask_collaboration_text(chunk),
                        "author_name": "SİDAR",
                    },
                )

            assistant_message = _build_room_message(
                room_id=room.room_id,
                role="assistant",
                content=result,
                author_name="SİDAR",
                author_id="sidar",
                kind="assistant_reply",
                request_id=request_id,
            )
            _append_room_message(room, assistant_message)
            await _broadcast_room_payload(
                room,
                {
                    "type": "assistant_done",
                    "room_id": room.room_id,
                    "request_id": request_id,
                    "message": assistant_message,
                },
            )
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await _broadcast_room_payload(
                    room,
                    {
                        "type": "assistant_done",
                        "room_id": room.room_id,
                        "request_id": request_id,
                        "cancelled": True,
                        "message": None,
                    },
                )
            raise
        except Exception as exc:
            logger.exception("Collaborative agent response error: %s", exc)
            await _broadcast_room_payload(
                room,
                    {
                        "type": "room_error",
                        "room_id": room.room_id,
                        "error": _mask_collaboration_text(str(exc)),
                        "request_id": request_id,
                    },
                )
        finally:
            stop_status.set()
            if status_task is not None:
                status_task.cancel()
                with contextlib.suppress(Exception):
                    await status_task
            if sub_id is not None:
                get_agent_event_bus().unsubscribe(sub_id)
            if room.active_task is not None and room.active_task.done():
                room.active_task = None
            if ctx_token is not None:
                reset_current_metrics_user_id(ctx_token)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue

            action = payload.get("action")
            user_message = payload.get("message", "").strip()

            if not ws_authenticated:
                if action != "auth":
                    await _ws_close_policy_violation(websocket, "Authentication required")
                    return
                auth_token = (payload.get("token", "") or "").strip()
                if not auth_token:
                    await _ws_close_policy_violation(websocket, "Authentication token missing")
                    return
                ws_user = await _await_if_needed(_resolve_user_from_token(agent, auth_token))
                if not ws_user:
                    await _ws_close_policy_violation(websocket, "Invalid or expired token")
                    return
                ws_user_id = ws_user.id
                ws_username = ws_user.username
                ws_user_role = _normalize_collaboration_role(getattr(ws_user, "role", "user"))
                ws_authenticated = True
                await agent.memory.set_active_user(ws_user_id, ws_username)
                with contextlib.suppress(Exception):
                    await websocket.send_json({'auth_ok': True})
                continue

            if action == "join_room":
                target_room_id = str(payload.get("room_id", "") or "").strip()
                display_name = str(payload.get("display_name", "") or ws_username or ws_user_id).strip()
                room = await _join_collaboration_room(
                    websocket,
                    room_id=target_room_id,
                    user_id=ws_user_id,
                    username=ws_username,
                    display_name=display_name,
                    user_role=ws_user_role,
                )
                joined_room_id = room.room_id
                continue

            if action == "cancel" and active_task and not active_task.done():
                active_task.cancel()
                await websocket.send_json({
                    "chunk": "\n\n*[Sistem: İşlem kullanıcı tarafından iptal edildi]*\n",
                    "done": True,
                })
                continue

            if action == "cancel" and joined_room_id:
                room = _collaboration_rooms.get(joined_room_id)
                if room and room.active_task and not room.active_task.done():
                    room.active_task.cancel()
                continue

            if not user_message:
                continue

            client_ip = websocket.client.host if websocket.client else "unknown"
            if await _redis_is_rate_limited("chat_ws", client_ip, _RATE_LIMIT, _RATE_WINDOW):
                await websocket.send_json({"chunk": "[Hız Sınırı] Çok fazla istek. Lütfen bir dakika bekleyin.", "done": True})
                continue

            if active_task and not active_task.done():
                active_task.cancel()

            if joined_room_id:
                room = _collaboration_rooms.get(joined_room_id)
                if room is None:
                    room = await _join_collaboration_room(
                        websocket,
                        room_id=joined_room_id,
                        user_id=ws_user_id,
                        username=ws_username,
                        display_name=ws_username or ws_user_id,
                        user_role=ws_user_role,
                    )
                display_name = str(payload.get("display_name", "") or ws_username or ws_user_id).strip() or ws_username or ws_user_id or "Anonim"
                user_message_payload = _build_room_message(
                    room_id=room.room_id,
                    role="user",
                    content=user_message,
                    author_name=display_name,
                    author_id=ws_user_id or display_name,
                    kind="sidar_command" if _is_sidar_mention(user_message) else "collaboration_note",
                )
                _append_room_message(room, user_message_payload)
                await _broadcast_room_payload(room, {"type": "room_message", "message": user_message_payload})

                if _is_sidar_mention(user_message):
                    command = _strip_sidar_mention(user_message)
                    if not command:
                        await _broadcast_room_payload(
                            room,
                            {
                                "type": "room_error",
                                "room_id": room.room_id,
                                "error": "@Sidar etiketi sonrası komut bulunamadı.",
                            },
                        )
                        continue
                    participant = room.participants.get(_socket_key(websocket))
                    if _collaboration_command_requires_write(command) and not (participant and participant.can_write):
                        _append_room_telemetry(
                            room,
                            {
                                "id": secrets.token_hex(8),
                                "room_id": room.room_id,
                                "kind": "rbac_denied",
                                "source": "collaboration_rbac",
                                "content": command,
                                "ts": _collaboration_now_iso(),
                            },
                        )
                        await _broadcast_room_payload(
                            room,
                            {
                                "type": "room_error",
                                "room_id": room.room_id,
                                "error": "Bu kullanıcı ortak çalışma alanında yazma yetkisine sahip değil.",
                            },
                        )
                        continue
                    if room.active_task and not room.active_task.done():
                        room.active_task.cancel()
                    room.active_task = asyncio.create_task(
                        generate_room_response(room, actor_name=display_name, msg=command)
                    )
                    await asyncio.sleep(0)
                continue

            active_task = asyncio.create_task(generate_response(user_message))

    except WebSocketDisconnect:
        logger.info("İstemci WebSocket bağlantısını kesti.")
        if active_task and not active_task.done():
            active_task.cancel()
        await _leave_collaboration_room(websocket)
    except Exception as _ws_exc:
        # anyio.ClosedResourceError: uvicorn/anyio üst katmanının bağlantı
        # kapatma sinyali — WebSocketDisconnect ile eşdeğer, normal çıkış.
        if _ANYIO_CLOSED is not None and isinstance(_ws_exc, _ANYIO_CLOSED):
            logger.info("İstemci WebSocket bağlantısını kesti (anyio ClosedResourceError).")
            if active_task and not active_task.done():
                active_task.cancel()
            await _leave_collaboration_room(websocket)
        else:
            logger.warning("WebSocket beklenmedik hata: %s", _ws_exc)
            with contextlib.suppress(Exception):
                await websocket.send_json(
                    {"error": "WebSocket oturumu beklenmedik şekilde sonlandı.", "done": True}
                )
            with contextlib.suppress(Exception):
                await _leave_collaboration_room(websocket)


@app.websocket("/ws/voice")
async def websocket_voice(websocket: WebSocket):
    """
    Gerçek zamanlı ses oturumu için websocket.

    MVP davranışı:
    - İstemci binary ses chunk'larını gönderir.
    - `commit` / `end` aksiyonu ile biriken ses STT'den geçirilir.
    - Transkript çıkarıldıktan sonra ajan metin yanıtı stream edilir.
    """
    proto_header = websocket.headers.get("sec-websocket-protocol", "").strip()
    header_token = proto_header or ""

    if header_token:
        await websocket.accept(subprotocol=header_token)
    else:
        await websocket.accept()

    try:
        from core.multimodal import MultimodalPipeline
    except ImportError:
        await websocket.send_json({"error": "core.multimodal modülü yüklenemedi.", "done": True})
        await websocket.close(code=1011, reason="multimodal unavailable")
        return

    try:
        from core.voice import VoicePipeline
    except ImportError:
        VoicePipeline = None  # type: ignore[assignment]

    agent = await _resolve_agent_instance()
    pipeline = MultimodalPipeline(agent.llm, cfg)
    voice_pipeline = None
    voice_init_error = ""
    if VoicePipeline is not None:
        try:
            voice_pipeline = VoicePipeline(cfg)
        except Exception as exc:
            voice_init_error = f"Voice Disabled: {exc.__class__.__name__}"
            logger.warning("Voice pipeline başlatılamadı, voice devre dışı: %s", exc)
    max_voice_bytes = int(getattr(cfg, "VOICE_WS_MAX_BYTES", 10 * 1024 * 1024) or 10 * 1024 * 1024)

    audio_buffer = bytearray()
    ws_user_id = ""
    ws_username = ""
    ws_authenticated = False
    session_mime_type = "audio/webm"
    session_language: str | None = None
    session_prompt = ""
    voice_sequence = 0
    active_response_task: asyncio.Task | None = None
    setattr(websocket, "_sidar_voice_pipeline", voice_pipeline)
    duplex_state = (
        voice_pipeline.create_duplex_state()
        if voice_pipeline is not None and hasattr(voice_pipeline, "create_duplex_state")
        else None
    )
    setattr(websocket, "_sidar_voice_duplex_state", duplex_state)

    async def _emit_voice_state(event: str) -> None:
        nonlocal voice_sequence
        voice_sequence += 1
        if voice_pipeline is None or not hasattr(voice_pipeline, "build_voice_state_payload"):
            await websocket.send_json(
                {
                    "voice_state": str(event or "").strip().lower() or "unknown",
                    "buffered_bytes": len(audio_buffer),
                    "sequence": voice_sequence,
                    "vad_enabled": bool(getattr(voice_pipeline, "vad_enabled", False)) if voice_pipeline is not None else False,
                    "auto_commit_ready": False,
                    "duplex_enabled": bool(getattr(voice_pipeline, "duplex_enabled", False)) if voice_pipeline is not None else False,
                    "interrupt_ready": False,
                    "tts_enabled": bool(getattr(voice_pipeline, "enabled", False)) if voice_pipeline is not None else False,
                    "voice_disabled_reason": voice_init_error,
                    "assistant_turn_id": int(getattr(duplex_state, "assistant_turn_id", 0) or 0),
                    "output_buffer_chars": len(getattr(duplex_state, "output_text_buffer", "") or ""),
                    "last_interrupt_reason": str(getattr(duplex_state, "last_interrupt_reason", "") or ""),
                }
            )
            return
        await websocket.send_json(
            voice_pipeline.build_voice_state_payload(
                event=event,
                buffered_bytes=len(audio_buffer),
                sequence=voice_sequence,
                duplex_state=duplex_state,
            )
        )

    async def _cancel_active_response(reason: str) -> None:
        nonlocal active_response_task
        interrupt_payload = (
            voice_pipeline.interrupt_assistant_turn(duplex_state, reason=reason)
            if voice_pipeline is not None and hasattr(voice_pipeline, "interrupt_assistant_turn")
            else {
                "assistant_turn_id": int(getattr(duplex_state, "assistant_turn_id", 0) or 0),
                "dropped_text_chars": 0,
                "cancelled_audio_sequences": 0,
                "reason": reason,
            }
        )
        if active_response_task is None or active_response_task.done():
            return
        active_response_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await active_response_task
        await websocket.send_json({"voice_interruption": reason, "cancelled": True, **interrupt_payload})
        active_response_task = None

    async def _run_voice_turn(
        *,
        audio_bytes: bytes,
        mime_type: str,
        language: str | None,
        prompt: str,
    ) -> None:
        if not audio_bytes:  # pragma: no cover - _process_audio_commit boş buffer'ı filtrelediği için savunmacı koruma
            await websocket.send_json({"error": "İşlenecek ses verisi bulunamadı.", "done": True})
            return

        result = await pipeline.transcribe_bytes(
            audio_bytes,
            mime_type=mime_type,
            language=language,
            prompt=prompt,
        )
        await _emit_voice_state("processed")

        if not isinstance(result, dict) or not result.get("success"):
            reason = "Ses transkripsiyonu başarısız oldu."
            if isinstance(result, dict):
                reason = str(result.get("reason", reason) or reason)
            await websocket.send_json({"error": reason, "done": True})
            return

        transcript_text = str(result.get("text", "") or "").strip()
        await websocket.send_json(
            {
                "transcript": transcript_text,
                "language": result.get("language", ""),
                "provider": result.get("provider", ""),
            }
        )
        if not transcript_text:
            await websocket.send_json({"done": True})
            return

        assistant_turn_id = (
            voice_pipeline.begin_assistant_turn(duplex_state)
            if voice_pipeline is not None and hasattr(voice_pipeline, "begin_assistant_turn")
            else int(getattr(duplex_state, "assistant_turn_id", 0) or 0)
        )
        await websocket.send_json({"assistant_turn": "started", "assistant_turn_id": assistant_turn_id})

        try:
            await _ws_stream_agent_text_response(websocket, agent, transcript_text)
        except LLMAPIError as exc:
            await websocket.send_json(
                {
                    "chunk": f"\n[LLM Hatası] {exc.provider} ({exc.status_code or 'n/a'}): {exc}",
                    "done": True,
                }
            )
            return
        except Exception as exc:
            logger.exception("Voice websocket agent yanıtı hatası: %s", exc)
            await websocket.send_json({"chunk": f"\n[Sistem Hatası] {exc}", "done": True})
            return

        await websocket.send_json({"assistant_turn": "completed", "assistant_turn_id": assistant_turn_id})
        await websocket.send_json({"done": True})

    async def _process_audio_commit() -> None:
        nonlocal audio_buffer, active_response_task
        if not audio_buffer:
            await websocket.send_json({"error": "İşlenecek ses verisi bulunamadı.", "done": True})
            return

        if active_response_task and not active_response_task.done():
            await _cancel_active_response("superseded_by_new_turn")

        commit_audio = bytes(audio_buffer)
        audio_buffer.clear()
        active_response_task = asyncio.create_task(
            _run_voice_turn(
                audio_bytes=commit_audio,
                mime_type=session_mime_type,
                language=session_language,
                prompt=session_prompt,
            )
        )

    if header_token:
        ws_user = await _await_if_needed(_resolve_user_from_token(agent, header_token))
        if not ws_user:
            await _ws_close_policy_violation(websocket, "Invalid or expired token")
            return
        ws_user_id = ws_user.id
        ws_username = ws_user.username
        ws_authenticated = True
        await agent.memory.set_active_user(ws_user_id, ws_username)
        with contextlib.suppress(Exception):
            await websocket.send_json({"auth_ok": True})

    try:
        while True:
            packet = await websocket.receive()
            packet_type = packet.get("type")
            if packet_type == "websocket.disconnect":
                raise WebSocketDisconnect()

            bytes_payload = packet.get("bytes")
            if bytes_payload is not None:
                if not ws_authenticated:
                    await _ws_close_policy_violation(websocket, "Authentication required")
                    return
                if len(audio_buffer) + len(bytes_payload) > max_voice_bytes:
                    await _ws_close_policy_violation(websocket, "Voice payload too large")
                    return
                audio_buffer.extend(bytes_payload)
                await websocket.send_json({"buffered_bytes": len(audio_buffer)})
                await _emit_voice_state("chunk")
                continue

            text_payload = packet.get("text")
            if text_payload is None:
                continue

            try:
                payload = json.loads(text_payload)
            except json.JSONDecodeError:
                continue

            action = str(payload.get("action", "") or "").strip().lower()
            if not ws_authenticated:
                if action != "auth":
                    await _ws_close_policy_violation(websocket, "Authentication required")
                    return
                auth_token = (payload.get("token", "") or "").strip()
                if not auth_token:
                    await _ws_close_policy_violation(websocket, "Authentication token missing")
                    return
                ws_user = await _await_if_needed(_resolve_user_from_token(agent, auth_token))
                if not ws_user:
                    await _ws_close_policy_violation(websocket, "Invalid or expired token")
                    return
                ws_user_id = ws_user.id
                ws_username = ws_user.username
                ws_authenticated = True
                await agent.memory.set_active_user(ws_user_id, ws_username)
                with contextlib.suppress(Exception):
                    await websocket.send_json({"auth_ok": True})
                continue

            if action in {"start", "reset"}:
                audio_buffer.clear()
                session_mime_type = str(payload.get("mime_type", "audio/webm") or "audio/webm")
                session_language = payload.get("language")
                session_prompt = str(payload.get("prompt", "") or "")
                await websocket.send_json(
                    {
                        "voice_session": "ready",
                        "mime_type": session_mime_type,
                        "duplex": True,
                        "vad_enabled": bool(getattr(voice_pipeline, "vad_enabled", False)),
                        "tts_enabled": bool(getattr(voice_pipeline, "enabled", False)) if voice_pipeline is not None else False,
                        "voice_disabled_reason": str(
                            getattr(voice_pipeline, "voice_disabled_reason", "") or voice_init_error
                        ),
                    }
                )
                await _emit_voice_state("ready")
                continue

            if action == "append_base64":
                encoded_chunk = str(payload.get("chunk", "") or "").strip()
                if not encoded_chunk:
                    continue
                try:
                    decoded_chunk = base64.b64decode(encoded_chunk, validate=True)
                except Exception:
                    await websocket.send_json({"error": "Geçersiz base64 ses parçası", "done": True})
                    continue
                if len(audio_buffer) + len(decoded_chunk) > max_voice_bytes:
                    await _ws_close_policy_violation(websocket, "Voice payload too large")
                    return
                audio_buffer.extend(decoded_chunk)
                await websocket.send_json({"buffered_bytes": len(audio_buffer)})
                await _emit_voice_state("chunk")
                continue

            if action == "cancel":
                audio_buffer.clear()
                await _cancel_active_response("user_cancelled")
                await _emit_voice_state("cancelled")
                await websocket.send_json({"cancelled": True, "done": True})
                continue

            if action == "vad_event":
                vad_state = str(payload.get("state", "") or "unknown")
                await _emit_voice_state(vad_state)
                if (
                    voice_pipeline
                    and hasattr(voice_pipeline, "should_interrupt_response")
                    and voice_pipeline.should_interrupt_response(len(audio_buffer), event=vad_state)
                ):
                    await _cancel_active_response("barge_in")
                if voice_pipeline and voice_pipeline.should_commit_audio(len(audio_buffer), event=vad_state):
                    await _process_audio_commit()
                continue

            if action not in {"commit", "process", "end", "vad_commit"}:
                continue

            session_mime_type = str(payload.get("mime_type", session_mime_type) or session_mime_type)
            session_language = payload.get("language", session_language)
            session_prompt = str(payload.get("prompt", session_prompt) or session_prompt)
            await _process_audio_commit()
    except WebSocketDisconnect:
        logger.info("İstemci voice WebSocket bağlantısını kesti.")
        if active_response_task and not active_response_task.done():
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await active_response_task
    except Exception as exc:
        if _ANYIO_CLOSED is not None and isinstance(exc, _ANYIO_CLOSED):
            logger.info("İstemci voice WebSocket bağlantısını kesti (anyio ClosedResourceError).")
            if active_response_task and not active_response_task.done():  # pragma: no cover
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await active_response_task
        else:
            logger.warning("Voice WebSocket beklenmedik hata: %s", exc)


@app.get(
    "/status",
    summary="Ajan Durumunu Getir",
    description="Ajanın donanım, LLM bağlantı, bellek ve sağlayıcı durumlarını JSON olarak döndürür.",
    responses={200: {"description": "Başarılı durum yanıtı"}},
)
async def status():
    """Ajan durum bilgisini JSON olarak döndür."""
    a = await _resolve_agent_instance()
    gpu_info = a.health.get_gpu_info()
    # Sağlayıcıya göre doğru model adını gönder
    if a.cfg.AI_PROVIDER == "gemini":
        model_display = getattr(a.cfg, "GEMINI_MODEL", "gemini-2.0-flash")
    else:
        model_display = a.cfg.CODING_MODEL

    enc_status = "Etkin (Fernet)" if getattr(a.cfg, "MEMORY_ENCRYPTION_KEY", "") else "Devre Dışı"

    ollama_t0 = time.monotonic()
    ollama_online = a.health.check_ollama()
    ollama_latency_ms = int((time.monotonic() - ollama_t0) * 1000)

    return JSONResponse({
        "version": a.VERSION,
        "provider": a.cfg.AI_PROVIDER,
        "model": model_display,
        "access_level": a.cfg.ACCESS_LEVEL,
        "memory_count": len(a.memory),
        "github": a.github.is_available(),
        "web_search": a.web.is_available(),
        "rag_status": a.docs.status(),
        "pkg_status": a.pkg.status(),
        "enc_status": enc_status,
        # GPU bilgisi
        "gpu_enabled": a.cfg.USE_GPU,
        "gpu_info": a.cfg.GPU_INFO,
        "gpu_count": getattr(a.cfg, "GPU_COUNT", 0),
        "cuda_version": getattr(a.cfg, "CUDA_VERSION", "N/A"),
        "gpu_devices": gpu_info.get("devices", []),
        "ollama_online": ollama_online,
        "ollama_latency_ms": ollama_latency_ms,
    })

async def _await_if_needed(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _health_response(*, require_dependencies: bool = False) -> JSONResponse:
    try:
        agent = await _resolve_agent_instance()
        health_data = agent.health.get_health_summary()
    except Exception as exc:
        logger.warning("Health check güvenli fallback'e düştü: %s", exc)
        return JSONResponse(
            {
                "status": "degraded",
                "error": "health_check_failed",
                "detail": str(exc),
                "uptime_seconds": int(time.monotonic() - _start_time),
            },
            status_code=503,
        )

    health_data["uptime_seconds"] = int(time.monotonic() - _start_time)

    # Eğer ana yapay zeka servisi (Ollama) çöktüyse 503 HTTP kodu döndür
    if agent.cfg.AI_PROVIDER == "ollama" and not health_data["ollama_online"]:
        health_data["status"] = "degraded"
        return JSONResponse(health_data, status_code=503)

    if require_dependencies:
        try:
            dependency_health = agent.health.get_dependency_health()
        except Exception as exc:
            logger.warning("Dependency health sorgusu başarısız oldu: %s", exc)
            health_data["dependencies"] = {"error": {"healthy": False, "detail": str(exc)}}
            health_data["status"] = "degraded"
            return JSONResponse(health_data, status_code=503)
        health_data["dependencies"] = dependency_health
        if any(item.get("healthy") is False for item in dependency_health.values()):
            health_data["status"] = "degraded"
            return JSONResponse(health_data, status_code=503)

    return JSONResponse(health_data)


@app.get(
    "/health",
    summary="Sağlık Kontrolü (Health Check)",
    description="Liveness/readiness kontrolü için sistem sağlık bilgisini döndürür.",
    responses={
        200: {"description": "Sistem sağlıklı"},
        503: {"description": "Sistemde kritik bir sorun var"},
    },
)
@app.get("/healthz", include_in_schema=False)
async def health_check():
    """
    Kubernetes/Docker liveness probe'ları için yapısal (JSON) sağlık kontrolü.
    """
    return await _health_response(require_dependencies=False)


@app.get("/readyz", include_in_schema=False)
async def readiness_check():
    """
    Readiness probe: Redis/PostgreSQL gibi bağımlılıklar erişilemezse 503 döndürür.
    """
    return await _health_response(require_dependencies=True)


@app.get("/metrics")
async def metrics(request: Request, _user=Depends(_require_metrics_access)):
    """
    Temel operasyonel metrikler (admin veya METRICS_TOKEN gerektirir).
    - Varsayılan: JSON formatı (her istemci için çalışır).
    - 'Accept: text/plain' başlığı + prometheus_client kurulu ise Prometheus formatı döner.
    """
    agent = await _resolve_agent_instance()
    uptime_s  = int(time.monotonic() - _start_time)
    rag_docs  = agent.docs.doc_count
    if hasattr(agent.memory, "aget_all_sessions"):
        sessions = await agent.memory.aget_all_sessions()
    else:
        sessions = agent.memory.get_all_sessions()
        if inspect.isawaitable(sessions):
            sessions = await sessions
    rl_total = sum(len(v) for v in _local_rate_limits.values())

    llm_totals = get_llm_metrics_collector().snapshot().get("totals", {})
    payload = {
        "version":                       agent.VERSION,
        "uptime_seconds":                uptime_s,
        "sessions_total":                len(sessions),
        "active_session_turns":          len(agent.memory),
        "rag_documents":                 rag_docs,
        "rate_limit_buckets":            len(_local_rate_limits),
        "rate_limit_requests_in_window": rl_total,
        "provider":                      agent.cfg.AI_PROVIDER,
        "gpu_enabled":                   agent.cfg.USE_GPU,
        "llm_calls":                     llm_totals.get("calls", 0),
        "llm_total_tokens":              llm_totals.get("total_tokens", 0),
    }

    # Prometheus formatı: istemci açıkça talep ederse VE kütüphane kuruluysa sun
    accept = request.headers.get("Accept", "")
    # Yalnızca gerçek HTTP isteğinde Prometheus çıktısı üret;
    # test/yardımcı çağrılarda JSON fallback davranışını koru.
    if isinstance(request, Request) and "text/plain" in accept:
        try:
            from prometheus_client import (
                CONTENT_TYPE_LATEST,
                CollectorRegistry,
                Gauge,
                generate_latest,
            )
            from starlette.responses import Response as _PromeResp
            reg = CollectorRegistry()
            Gauge("sidar_uptime_seconds",      "Sunucu çalışma süresi (s)",     registry=reg).set(uptime_s)
            Gauge("sidar_sessions_total",      "Toplam oturum sayısı",           registry=reg).set(len(sessions))
            Gauge("sidar_rag_documents_total", "RAG belge sayısı",               registry=reg).set(rag_docs)
            Gauge("sidar_active_turns",        "Aktif oturum tur sayısı",        registry=reg).set(len(agent.memory))
            Gauge("sidar_rate_limit_requests", "Rate limit penceredeki istek",   registry=reg).set(rl_total)
            return _PromeResp(generate_latest(reg), media_type=CONTENT_TYPE_LATEST)
        except ImportError:
            pass  # prometheus_client kurulu değil — JSON ile devam et

    return JSONResponse(payload)


@app.get("/metrics/llm/prometheus")
async def llm_prometheus_metrics(_user=Depends(_require_metrics_access)):
    """LLM + ajan delegasyon metriklerini Prometheus text/plain formatında döndürür."""
    snapshot = get_llm_metrics_collector().snapshot()
    llm_part = render_llm_metrics_prometheus(snapshot)

    delegation_part = ""
    try:
        from core.agent_metrics import get_agent_metrics_collector
        delegation_part = get_agent_metrics_collector().render_prometheus()
    except Exception:
        pass

    return Response(content=llm_part + delegation_part, media_type="text/plain; version=0.0.4")


@app.get("/metrics/llm")
@app.get("/api/budget")
async def llm_budget_metrics(_user=Depends(_require_metrics_access)):
    """LLM token/latency/rate-limit metriklerini JSON olarak döndürür (admin veya METRICS_TOKEN gerektirir)."""
    collector = get_llm_metrics_collector()
    return JSONResponse(collector.snapshot())



# ─────────────────────────────────────────────
#  ÇOKLU SOHBET (SESSIONS) ROTALARI
# ─────────────────────────────────────────────

@app.get(
    "/sessions",
    summary="Tüm Oturumları Listele",
    description="Kayıtlı sohbet oturumları listesini ve aktif oturum kimliğini döndürür.",
    responses={200: {"description": "Oturum listesi başarıyla alındı"}},
)
async def get_sessions(request: Request, user=Depends(_get_request_user)):
    """Yalnızca oturum sahibine ait sohbetleri döndürür."""
    agent = await _resolve_agent_instance()
    sessions = await agent.memory.db.list_sessions(user.id)
    return JSONResponse({
        "active_session": None,
        "sessions": [
            {"id": row.id, "title": row.title, "updated_at": row.updated_at, "message_count": len(await agent.memory.db.get_session_messages(row.id))}
            for row in sessions
        ]
    })

@app.get("/sessions/{session_id}")
async def load_session(session_id: str, request: Request, user=Depends(_get_request_user)):
    """Belirli bir oturumu kullanıcı kimliğiyle doğrulayarak yükler."""
    agent = await _resolve_agent_instance()
    session = await agent.memory.db.load_session(session_id, user.id)
    if not session:
        return JSONResponse({"success": False, "error": "Oturum bulunamadı."}, status_code=404)
    messages = await agent.memory.db.get_session_messages(session_id)
    history = [{"role": m.role, "content": m.content, "timestamp": agent.memory._safe_ts(m.created_at), "tokens_used": m.tokens_used} for m in messages]
    return JSONResponse({"success": True, "history": history})

@app.post("/sessions/new")
async def new_session(request: Request, user=Depends(_get_request_user)):
    """Aktif kullanıcı için yeni bir oturum oluşturur."""
    agent = await _resolve_agent_instance()
    session = await agent.memory.db.create_session(user.id, "Yeni Sohbet")
    return JSONResponse({"success": True, "session_id": session.id})

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request, user=Depends(_get_request_user)):
    """Kullanıcıya ait belirli bir oturumu siler."""
    agent = await _resolve_agent_instance()
    deleted = await agent.memory.db.delete_session(session_id, user.id)
    if deleted:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "Silinemedi."}, status_code=500)

@app.get("/files")
async def list_project_files(path: str = ""):
    """
    Proje dizinindeki dosya ve klasörleri listeler.
    path parametresi boşsa proje kök dizinini listeler.
    """
    _root = Path(__file__).parent.resolve()
    target = (_root / path).resolve()

    # Güvenlik: proje kökünün dışına çıkma
    try:
        target.relative_to(_root)
    except ValueError:
        return JSONResponse({"error": "Güvenlik: proje dışına çıkılamaz."}, status_code=403)

    if not target.exists():
        return JSONResponse({"error": f"Dizin bulunamadı: {path}"}, status_code=404)
    if not target.is_dir():
        return JSONResponse({"error": f"Belirtilen yol bir dizin değil: {path}"}, status_code=400)

    items = []
    for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        # Gizli ve sanal ortam klasörlerini atla
        if item.name.startswith(".") or item.name in ("__pycache__", "node_modules"):
            continue
        rel = str(item.relative_to(_root))
        items.append({
            "name": item.name,
            "path": rel,
            "type": "file" if item.is_file() else "dir",
            "size": item.stat().st_size if item.is_file() else 0,
        })

    return JSONResponse({"path": str(target.relative_to(_root)) if path else ".", "items": items})


@app.get("/file-content")
async def file_content(path: str):
    """
    Proje içindeki bir dosyanın içeriğini döndürür.
    Güvenli metin tabanlı uzantılarla sınırlandırılmıştır.
    """
    _SAFE_EXTENSIONS = {
        ".py", ".txt", ".md", ".json", ".yaml", ".yml", ".ini", ".cfg",
        ".toml", ".html", ".css", ".js", ".ts", ".sh",
        ".gitignore", ".dockerignore", ".sql", ".csv", ".xml",
    }
    _root = Path(__file__).parent.resolve()
    target = (_root / path).resolve()

    try:
        target.relative_to(_root)
    except ValueError:
        return JSONResponse({"error": "Güvenlik: proje dışına çıkılamaz."}, status_code=403)

    if not target.exists():
        return JSONResponse({"error": f"Dosya bulunamadı: {path}"}, status_code=404)
    if target.is_dir():
        return JSONResponse({"error": "Belirtilen yol bir dizin."}, status_code=400)
    if target.suffix.lower() not in _SAFE_EXTENSIONS:
        return JSONResponse({"error": f"Desteklenmeyen dosya türü: {target.suffix}"}, status_code=415)

    size_bytes = target.stat().st_size
    if size_bytes > MAX_FILE_CONTENT_BYTES:
        return JSONResponse(
            {
                "error": (
                    f"Dosya boyutu limiti aşıldı: {size_bytes} bayt "
                    f"(maksimum {MAX_FILE_CONTENT_BYTES} bayt)"
                )
            },
            status_code=413,
        )

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return JSONResponse({"path": path, "content": content, "size": len(content)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def _git_run(cmd: list, cwd: str, stderr=subprocess.DEVNULL) -> str:
    """Senkron git alt süreci çalıştırır. asyncio.to_thread() ile çağrılmalı."""
    try:
        return subprocess.check_output(cmd, cwd=cwd, stderr=stderr).decode().strip()
    except Exception:
        return ""


@app.get("/git-info")
async def git_info():
    """Git deposu bilgilerini (dal adı, repo adı) döndürür."""
    _root = str(Path(__file__).parent)

    branch = await asyncio.to_thread(
        _git_run, ["git", "rev-parse", "--abbrev-ref", "HEAD"], _root
    ) or "main"
    remote = await asyncio.to_thread(
        _git_run, ["git", "remote", "get-url", "origin"], _root
    ) or ""

    # Varsayılan branch için önce upstream ref'i dene (origin/main gibi döner),
    # boşsa origin/HEAD symbolic-ref yoluna geri dön.
    default_branch_raw = await asyncio.to_thread(
        _git_run, ["git", "symbolic-ref", "--short", "HEAD@{upstream}"], _root
    ) or ""
    if not default_branch_raw:
        default_branch_raw = await asyncio.to_thread(
            _git_run, ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], _root
        ) or ""
    default_branch = default_branch_raw.replace("origin/", "").strip() or "main"

    # GitHub URL'sini "owner/repo" biçimine çevir
    repo = ""
    if remote:
        # https://github.com/owner/repo.git  →  owner/repo
        # git@github.com:owner/repo.git      →  owner/repo
        repo = remote.removesuffix(".git")
        repo = repo.split("github.com/")[-1].split("github.com:")[-1]

    return JSONResponse({"branch": branch, "repo": repo or "Sidar", "default_branch": default_branch})


@app.get("/git-branches")
async def git_branches():
    """Yerel git dallarını listeler."""
    _root = str(Path(__file__).parent)

    branches_raw = await asyncio.to_thread(
        _git_run, ["git", "branch", "--format=%(refname:short)"], _root
    )
    branches = [b.strip() for b in branches_raw.split("\n") if b.strip()]
    current = await asyncio.to_thread(
        _git_run, ["git", "rev-parse", "--abbrev-ref", "HEAD"], _root
    ) or "main"

    return JSONResponse({"branches": branches or ["main"], "current": current})


_BRANCH_RE = re.compile(r"^[a-zA-Z0-9/_.-]+$")


@app.post("/set-branch")
async def set_branch(request: Request):
    """Aktif git dalını değiştirir (git checkout)."""
    body = await request.json()
    branch_name = body.get("branch", "").strip()
    if not branch_name:
        return JSONResponse({"success": False, "error": "Dal adı boş."}, status_code=400)
    if not _BRANCH_RE.match(branch_name):
        return JSONResponse({"success": False, "error": "Geçersiz dal adı: yalnızca harf, rakam, '/', '_', '-', '.' kullanılabilir."}, status_code=400)

    _root = str(Path(__file__).parent)
    try:
        await asyncio.to_thread(
            subprocess.check_output,
            ["git", "checkout", branch_name],
            cwd=_root,
            stderr=subprocess.STDOUT,
        )
        return JSONResponse({"success": True, "branch": branch_name})
    except subprocess.CalledProcessError as exc:
        detail = exc.output.decode().strip() if exc.output else str(exc)
        return JSONResponse({"success": False, "error": detail}, status_code=400)




@app.get("/github-repos")
async def github_repos(owner: str = "", q: str = ""):
    """GitHub erişimi olan depo listesini döndürür (opsiyonel owner + arama filtresi)."""
    agent = await _resolve_agent_instance()

    # owner verilmezse aktif repodan owner türet
    active_repo = (getattr(agent.github, "repo_name", "") or cfg.GITHUB_REPO or "").strip()
    effective_owner = owner.strip()
    if not effective_owner and "/" in active_repo:
        effective_owner = active_repo.split("/", 1)[0]

    ok, repos = agent.github.list_repos(owner=effective_owner, limit=200)
    if not ok:
        return JSONResponse({"success": False, "error": "Repo listesi alınamadı.", "repos": []}, status_code=400)

    query = q.strip().lower()
    if query:
        repos = [r for r in repos if query in r.get("full_name", "").lower()]

    repos = sorted(repos, key=lambda r: r.get("full_name", "").lower())
    return JSONResponse({
        "success": True,
        "owner": effective_owner,
        "repos": repos,
        "active_repo": active_repo,
    })


@app.get(
    "/github-prs",
    summary="GitHub PR Listesini Getir",
    description="Yapılandırılmış repodan açık pull request listesini döndürür.",
    responses={200: {"description": "PR listesi başarıyla alındı"}},
)
async def github_prs(state: str = "open", limit: int = 10):
    """
    Aktif GitHub deposundaki PR listesini döndürür.
    state: open / closed / all
    limit: maksimum PR sayısı (max 50)
    """
    agent = await _resolve_agent_instance()
    if not agent.github.is_available():
        return JSONResponse({"success": False, "error": "GitHub token ayarlanmamış.", "prs": []}, status_code=503)
    ok, prs, err = agent.github.get_pull_requests_detailed(state=state, limit=min(limit, 50))
    if not ok:
        return JSONResponse({"success": False, "error": err, "prs": []}, status_code=500)
    return JSONResponse({"success": True, "prs": prs, "repo": agent.github.repo_name})


@app.get("/github-prs/{number}")
async def github_pr_detail(number: int):
    """Belirli bir PR'ın detaylarını döndürür."""
    agent = await _resolve_agent_instance()
    if not agent.github.is_available():
        return JSONResponse({"success": False, "error": "GitHub token ayarlanmamış."}, status_code=503)
    ok, result = agent.github.get_pull_request(number)
    if not ok:
        return JSONResponse({"success": False, "error": result}, status_code=404)
    return JSONResponse({"success": True, "detail": result})


@app.post("/set-repo")
async def set_repo(request: Request):
    """GitHub deposunu çalışma zamanında değiştirir."""
    body = await request.json()
    repo_name = body.get("repo", "").strip()
    if not repo_name:
        return JSONResponse({"success": False, "error": "Depo adı boş."}, status_code=400)

    agent = await _resolve_agent_instance()
    ok, msg = agent.github.set_repo(repo_name)
    if ok:
        cfg.GITHUB_REPO = repo_name
    return JSONResponse({"success": ok, "message": msg})


# ─────────────────────────────────────────────
#  RAG BELGE DEPOSU YÖNETİMİ
# ─────────────────────────────────────────────

@app.get("/rag/docs")
async def rag_list_docs():
    """RAG deposundaki aktif oturuma ait belgeleri listeler."""
    agent = await _resolve_agent_instance()
    session_id = agent.memory.active_session_id or "global"
    docs = agent.docs.get_index_info(session_id=session_id)
    return JSONResponse({"success": True, "docs": docs, "count": len(docs)})


@app.post(
    "/rag/add-file",
    summary="Yerel Dosyayı RAG'a Ekle",
    description="Proje dizinindeki yerel bir dosyayı RAG vektör deposuna ekler.",
    responses={
        200: {"description": "Dosya başarıyla RAG deposuna eklendi"},
        400: {"description": "Dosya yolu boş veya geçersiz"},
        403: {"description": "Güvenlik: Proje dizini dışına çıkma girişimi"},
    },
)
async def rag_add_file(request: Request):
    """
    Proje dizinindeki yerel bir dosyayı RAG deposuna ekler.
    Body: {"path": "relative/path/to/file.py", "title": "Opsiyonel başlık"}
    """
    body = await request.json()
    path = body.get("path", "").strip()
    title = body.get("title", "").strip()
    if not path:
        return JSONResponse({"success": False, "error": "Dosya yolu boş."}, status_code=400)

    _root = Path(__file__).parent.resolve()
    target = (_root / path).resolve()
    try:
        target.relative_to(_root)
    except ValueError:
        return JSONResponse({"success": False, "error": "Güvenlik: proje dışına çıkılamaz."}, status_code=403)

    agent = await _resolve_agent_instance()
    session_id = agent.memory.active_session_id or "global"
    ok, msg = await asyncio.to_thread(
        agent.docs.add_document_from_file, str(target), title or target.name, None, session_id
    )
    return JSONResponse({"success": ok, "message": msg})


@app.post("/rag/add-url")
async def rag_add_url(request: Request):
    """URL'den içerik çekerek RAG deposuna ekler."""
    body = await request.json()
    url   = body.get("url", "").strip()
    title = body.get("title", "").strip()
    if not url:
        return JSONResponse({"success": False, "error": "URL boş."}, status_code=400)

    agent = await _resolve_agent_instance()
    session_id = agent.memory.active_session_id or "global"
    ok, msg = await agent.docs.add_document_from_url(url, title=title, session_id=session_id)
    return JSONResponse({"success": ok, "message": msg})


@app.delete("/rag/docs/{doc_id}")
async def rag_delete_doc(doc_id: str):
    """RAG deposundan belge siler (oturum izolasyonuna uygun)."""
    agent = await _resolve_agent_instance()
    session_id = agent.memory.active_session_id or "global"
    msg = await asyncio.to_thread(agent.docs.delete_document, doc_id, session_id)
    success = msg.startswith("✓")
    return JSONResponse({"success": success, "message": msg})




@app.post("/api/rag/upload")
async def upload_rag_file(file: UploadFile = File(...)):
    """Web arayüzünden Sürükle-Bırak ile gelen dosyaları RAG deposuna ekler."""
    agent = await _await_if_needed(_resolve_agent_instance())
    session_id = agent.memory.active_session_id or "global"

    temp_dir = None
    try:
        # Dosya boyutunu diske yazmadan önce kontrol et (DoS / disk doldurma koruması)
        max_bytes = Config.MAX_RAG_UPLOAD_BYTES
        data = await file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail={"detail": f"Dosya çok büyük. Maksimum izin verilen boyut: {max_bytes // (1024 * 1024)} MB"},
            )

        # Dosyayı orijinal adıyla güvenli bir geçici klasöre kaydet
        temp_dir = Path(tempfile.mkdtemp())
        original_name = file.filename or "uploaded_file.txt"
        safe_filename = "".join(c for c in original_name if c.isalnum() or c in ".-_ ")
        if not safe_filename:
            safe_filename = "uploaded_file.txt"
        tmp_path = temp_dir / safe_filename

        async with await anyio.open_file(tmp_path, "wb") as buffer:
            await buffer.write(data)

        # RAG deposuna ekle (İzolasyon korumalı)
        ok, msg = await asyncio.to_thread(
            agent.docs.add_document_from_file,
            str(tmp_path),
            original_name,
            None,
            session_id,
        )

        if ok:
            return JSONResponse({"success": True, "message": msg})
        return JSONResponse({"success": False, "error": msg}, status_code=400)

    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)
    finally:
        try:
            await file.close()
        except Exception:
            pass
        if temp_dir is not None:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

@app.get(
    "/rag/search",
    summary="RAG Deposunda Arama Yap",
    description="RAG deposunda belirtilen sorguyu mode/top_k parametreleriyle arar.",
    responses={
        200: {"description": "Arama başarılı"},
        400: {"description": "Sorgu parametresi eksik veya hatalı"},
    },
)
async def rag_search(q: str = "", mode: str = "auto", top_k: int = 3):
    """RAG deposunda aktif oturuma ait belgelerde arama yapar."""
    if not q.strip():
        return JSONResponse({"success": False, "error": "Sorgu boş."}, status_code=400)
    agent = await _resolve_agent_instance()
    session_id = agent.memory.active_session_id or "global"
    search_call = agent.docs.search
    if asyncio.iscoroutinefunction(search_call):
        ok, result = await search_call(q.strip(), min(top_k, 10), mode, session_id)
    else:
        ok, result = await asyncio.to_thread(
            search_call, q.strip(), min(top_k, 10), mode, session_id
        )
    return JSONResponse({"success": ok, "result": result})


@app.get(
    "/todo",
    summary="Görev Listesini Getir",
    description="Aktif görev listesini ve özet sayaç bilgilerini döndürür.",
    responses={200: {"description": "Görev listesi başarıyla alındı"}},
)
async def get_todo():
    """
    Aktif görev listesini JSON olarak döndürür.
    UI'daki Todo paneli bu endpoint'i periyodik olarak sorgular.
    """
    agent = await _resolve_agent_instance()
    tasks = agent.todo.get_tasks()
    active = sum(1 for t in tasks if t["status"] != "completed")
    return JSONResponse({"tasks": tasks, "count": len(tasks), "active": active})


@app.post(
    "/clear",
    summary="Aktif Belleği Temizle",
    description="Mevcut aktif konuşma belleğini tamamen temizler.",
    responses={200: {"description": "Bellek başarıyla temizlendi"}},
)
async def clear():
    """Aktif konuşma belleğini temizle."""
    agent = await _resolve_agent_instance()
    await _await_if_needed(agent.memory.clear())
    return JSONResponse({"result": True})


@app.post(
    "/set-level",
    summary="Güvenlik Seviyesini Değiştir",
    description=(
        "Ajanın çalışma zamanındaki erişim seviyesini "
        "(restricted, sandbox, full) değiştirir ve sohbet belleğine loglar."
    ),
    responses={200: {"description": "Seviye başarıyla değiştirildi"}},
)
async def set_level_endpoint(request: Request, _user=Depends(_require_admin_user)):
    """Güvenlik seviyesini çalışma zamanında değiştirir (yalnızca admin)."""
    body = await request.json()
    new_level = body.get("level", "").strip()
    if not new_level:
        return JSONResponse({"success": False, "error": "Seviye belirtilmedi."}, status_code=400)

    agent = await _await_if_needed(_resolve_agent_instance())
    result_msg = await asyncio.to_thread(agent.set_access_level, new_level)
    if asyncio.iscoroutine(result_msg):
        result_msg = await result_msg
    return JSONResponse(
        {
            "success": True,
            "message": result_msg,
            "current_level": agent.security.level_name,
        }
    )


# ─────────────────────────────────────────────
#  Bulgu O-7: Faz 4/5 Modül API Endpoint'leri
#  VisionPipeline · EntityMemory · FeedbackStore
#  Slack · Jira · Teams
# ─────────────────────────────────────────────

# ── Vision ──────────────────────────────────

class _VisionAnalyzeRequest(BaseModel):
    image_base64: str = Field(..., description="Base64 kodlu görüntü verisi")
    mime_type: str = Field("image/png", description="Görüntü MIME türü")
    analysis_type: str = Field("general", description="Analiz türü: general, ui, chart, document")
    prompt: str | None = Field(None, description="Özel analiz talimatı (opsiyonel)")


class _VisionMockupRequest(BaseModel):
    image_base64: str = Field(..., description="Base64 kodlu mockup görüntüsü")
    mime_type: str = Field("image/png", description="Görüntü MIME türü")
    framework: str = Field("html", description="Hedef framework: html, react, vue")
    prompt: str | None = Field(None, description="Ek talimat (opsiyonel)")


@app.post("/api/vision/analyze", summary="Görüntü Analizi", tags=["Vision"])
async def api_vision_analyze(req: _VisionAnalyzeRequest):
    """VisionPipeline ile görüntüyü analiz eder."""
    agent = await _resolve_agent_instance()
    VisionPipeline, build_analyze_prompt = _resolve_vision_components()
    pipeline = VisionPipeline(agent.llm, cfg)
    prompt = req.prompt or build_analyze_prompt(req.analysis_type)
    try:
        result = await pipeline.analyze(
            image_b64=req.image_base64,
            mime_type=req.mime_type,
            prompt=prompt,
        )
    except TypeError:
        try:
            image_bytes = base64.b64decode(req.image_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Geçersiz base64 görüntü verisi: {exc}") from exc

        result = await pipeline.analyze(
            image_bytes=image_bytes,
            mime_type=req.mime_type,
            analysis_type=req.analysis_type,
        )
    return JSONResponse({"success": True, "result": result})


@app.post("/api/vision/mockup", summary="Mockup → Kod Dönüşümü", tags=["Vision"])
async def api_vision_mockup(req: _VisionMockupRequest):
    """VisionPipeline ile mockup görüntüsünden kod üretir."""
    agent = await _resolve_agent_instance()
    VisionPipeline, _build_analyze_prompt = _resolve_vision_components()
    pipeline = VisionPipeline(agent.llm, cfg)
    try:
        code = await pipeline.mockup_to_code(
            image_b64=req.image_base64,
            mime_type=req.mime_type,
            framework=req.framework,
            extra_instructions=req.prompt or "",
        )
    except TypeError:
        try:
            image_bytes = base64.b64decode(req.image_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Geçersiz base64 görüntü verisi: {exc}") from exc

        code = await pipeline.mockup_to_code(
            image_bytes=image_bytes,
            mime_type=req.mime_type,
            framework=req.framework,
            extra_instructions=req.prompt or "",
        )
    return JSONResponse({"success": True, "code": code})


# ── EntityMemory ─────────────────────────────

class _EntityUpsertRequest(BaseModel):
    user_id: str = Field(..., description="Kullanıcı kimliği")
    key: str = Field(..., description="Bellek anahtarı")
    value: str = Field(..., description="Saklanacak değer")
    ttl_days: int | None = Field(None, description="Yaşam süresi (gün); None = kalıcı")


_entity_memory_instance = None


async def _get_entity_memory():
    global _entity_memory_instance
    if _entity_memory_instance is None:
        try:
            from core.entity_memory import get_entity_memory
            _entity_memory_instance = get_entity_memory(cfg)
            await _entity_memory_instance.initialize()
        except Exception as exc:
            raise HTTPException(status_code=501, detail=f"EntityMemory başlatılamadı: {exc}") from exc
    return _entity_memory_instance


@app.post("/api/memory/entity/upsert", summary="Varlık Belleği Yaz", tags=["EntityMemory"])
async def api_entity_upsert(req: _EntityUpsertRequest):
    """Kullanıcıya ait bir bellek kaydını ekler veya günceller."""
    mem = await _get_entity_memory()
    await mem.upsert(user_id=req.user_id, key=req.key, value=req.value, ttl_days=req.ttl_days)
    return JSONResponse({"success": True})


@app.get("/api/memory/entity/{user_id}", summary="Varlık Belleği Profili", tags=["EntityMemory"])
async def api_entity_get_profile(user_id: str):
    """Bir kullanıcının tüm bellek profilini döner."""
    mem = await _get_entity_memory()
    profile = await mem.get_profile(user_id=user_id)
    return JSONResponse({"success": True, "user_id": user_id, "profile": profile})


@app.delete(
    "/api/memory/entity/{user_id}/{key}",
    summary="Varlık Belleği Sil",
    tags=["EntityMemory"],
)
async def api_entity_delete(user_id: str, key: str):
    """Kullanıcıya ait bir bellek kaydını siler."""
    mem = await _get_entity_memory()
    deleted = await mem.delete(user_id=user_id, key=key)
    return JSONResponse({"success": deleted})


# ── FeedbackStore ────────────────────────────

class _FeedbackRecordRequest(BaseModel):
    user_id: str = Field(..., description="Kullanıcı kimliği")
    prompt: str = Field(..., description="Kullanıcı girdisi")
    response: str = Field(..., description="Model çıktısı")
    rating: int = Field(..., ge=1, le=5, description="Değerlendirme puanı (1–5)")
    note: str | None = Field(None, description="Ek not")


_feedback_store_instance = None


async def _get_feedback_store():
    global _feedback_store_instance
    if _feedback_store_instance is None:
        try:
            from core.active_learning import get_feedback_store
            _feedback_store_instance = get_feedback_store(cfg)
            await _feedback_store_instance.initialize()
        except Exception as exc:
            raise HTTPException(status_code=501, detail=f"FeedbackStore başlatılamadı: {exc}") from exc
    return _feedback_store_instance


@app.post("/api/feedback/record", summary="Geri Bildirim Kaydet", tags=["ActiveLearning"])
async def api_feedback_record(req: _FeedbackRecordRequest):
    """Kullanıcı geri bildirimini FeedbackStore'a kaydeder."""
    store = await _get_feedback_store()
    await store.record(
        user_id=req.user_id,
        prompt=req.prompt,
        response=req.response,
        rating=req.rating,
        note=req.note or "",
    )
    return JSONResponse({"success": True})


@app.get("/api/feedback/stats", summary="Geri Bildirim İstatistikleri", tags=["ActiveLearning"])
async def api_feedback_stats():
    """FeedbackStore istatistiklerini döner."""
    store = await _get_feedback_store()
    stats = await store.stats()
    return JSONResponse({"success": True, "stats": stats})


# ── Slack ────────────────────────────────────

class _SlackSendRequest(BaseModel):
    text: str = Field(..., description="Gönderilecek mesaj metni")
    channel: str | None = Field(None, description="Hedef kanal (ör. #general)")
    thread_ts: str | None = Field(None, description="Thread zaman damgası")


_slack_mgr_instance = None


async def _get_slack_manager():
    global _slack_mgr_instance
    if _slack_mgr_instance is None:
        from managers.slack_manager import SlackManager
        _slack_mgr_instance = SlackManager(
            token=getattr(cfg, "SLACK_TOKEN", ""),
            webhook_url=getattr(cfg, "SLACK_WEBHOOK_URL", ""),
            default_channel=getattr(cfg, "SLACK_DEFAULT_CHANNEL", ""),
        )
        await _slack_mgr_instance.initialize()
    return _slack_mgr_instance


@app.post("/api/integrations/slack/send", summary="Slack Mesajı Gönder", tags=["Slack"])
async def api_slack_send(req: _SlackSendRequest):
    """Slack kanalına mesaj gönderir."""
    maybe_mgr = _get_slack_manager()
    mgr = await maybe_mgr if inspect.isawaitable(maybe_mgr) else maybe_mgr
    if not mgr.is_available():
        raise HTTPException(status_code=503, detail="Slack entegrasyonu yapılandırılmamış.")
    ok, err = await mgr.send_message(text=req.text, channel=req.channel, thread_ts=req.thread_ts)
    if not ok:
        raise HTTPException(status_code=502, detail=f"Slack hatası: {err}")
    return JSONResponse({"success": True})


@app.get("/api/integrations/slack/channels", summary="Slack Kanal Listesi", tags=["Slack"])
async def api_slack_channels():
    """Workspace'deki Slack kanallarını listeler (SDK gerektirir)."""
    maybe_mgr = _get_slack_manager()
    mgr = await maybe_mgr if inspect.isawaitable(maybe_mgr) else maybe_mgr
    if not mgr.is_available():
        raise HTTPException(status_code=503, detail="Slack entegrasyonu yapılandırılmamış.")
    ok, channels, err = await mgr.list_channels()
    if not ok:
        raise HTTPException(status_code=502, detail=f"Slack hatası: {err}")
    return JSONResponse({"success": True, "channels": channels})


# ── Jira ─────────────────────────────────────

class _JiraCreateRequest(BaseModel):
    project_key: str = Field(..., description="Jira proje anahtarı (ör. SIDAR)")
    summary: str = Field(..., description="Issue başlığı")
    description: str | None = Field(None, description="Issue açıklaması")
    issue_type: str = Field("Task", description="Issue türü: Task, Bug, Story")
    priority: str | None = Field(None, description="Öncelik: Highest, High, Medium, Low")


_jira_mgr_instance = None


def _get_jira_manager():
    global _jira_mgr_instance
    if _jira_mgr_instance is None:
        from managers.jira_manager import JiraManager
        _jira_mgr_instance = JiraManager(
            base_url=getattr(cfg, "JIRA_BASE_URL", ""),
            email=getattr(cfg, "JIRA_EMAIL", ""),
            api_token=getattr(cfg, "JIRA_API_TOKEN", ""),
            default_project=getattr(cfg, "JIRA_DEFAULT_PROJECT", ""),
        )
    return _jira_mgr_instance


@app.post("/api/integrations/jira/issue", summary="Jira Issue Oluştur", tags=["Jira"])
async def api_jira_create_issue(req: _JiraCreateRequest):
    """Jira'da yeni bir issue oluşturur."""
    mgr = _get_jira_manager()
    if not mgr.is_available():
        raise HTTPException(status_code=503, detail="Jira entegrasyonu yapılandırılmamış.")
    ok, issue, err = await mgr.create_issue(
        project_key=req.project_key,
        summary=req.summary,
        description=req.description or "",
        issue_type=req.issue_type,
        priority=req.priority,
    )
    if not ok:
        raise HTTPException(status_code=502, detail=f"Jira hatası: {err}")
    return JSONResponse({"success": True, "issue": issue})


@app.get("/api/integrations/jira/issues", summary="Jira Issue Arama", tags=["Jira"])
async def api_jira_search_issues(jql: str = "", max_results: int = 20):
    """JQL sorgusuna göre Jira issue'larını listeler."""
    mgr = _get_jira_manager()
    if not mgr.is_available():
        raise HTTPException(status_code=503, detail="Jira entegrasyonu yapılandırılmamış.")
    ok, issues, err = await mgr.search_issues(jql=jql, max_results=max_results)
    if not ok:
        raise HTTPException(status_code=502, detail=f"Jira hatası: {err}")
    return JSONResponse({"success": True, "issues": issues, "total": len(issues)})


# ── Teams ────────────────────────────────────

class _TeamsSendRequest(BaseModel):
    text: str = Field(..., description="Gönderilecek mesaj metni")
    title: str | None = Field(None, description="Mesaj başlığı")


class _OperationChecklistCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    items: list[str] = Field(default_factory=list)
    status: str = Field(default="pending", min_length=1, max_length=32)


class _ContentAssetCreateRequest(BaseModel):
    asset_type: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=160)
    content: str = Field(..., min_length=1)
    channel: str = Field(default="", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class _CampaignCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    channel: str = Field(default="", max_length=64)
    objective: str = Field(default="", max_length=400)
    status: str = Field(default="draft", min_length=1, max_length=32)
    budget: float = Field(default=0.0, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    initial_assets: list[_ContentAssetCreateRequest] = Field(default_factory=list)
    initial_checklists: list[_OperationChecklistCreateRequest] = Field(default_factory=list)


_teams_mgr_instance = None


def _get_teams_manager():
    global _teams_mgr_instance
    if _teams_mgr_instance is None:
        from managers.teams_manager import TeamsManager
        _teams_mgr_instance = TeamsManager(
            webhook_url=getattr(cfg, "TEAMS_WEBHOOK_URL", ""),
        )
    return _teams_mgr_instance


@app.post("/api/integrations/teams/send", summary="Teams Mesajı Gönder", tags=["Teams"])
async def api_teams_send(req: _TeamsSendRequest):
    """Microsoft Teams kanalına mesaj gönderir."""
    mgr = _get_teams_manager()
    if not mgr.is_available():
        raise HTTPException(status_code=503, detail="Teams entegrasyonu yapılandırılmamış.")
    ok, err = await mgr.send_message(text=req.text, title=req.title or "Sidar Bildirimi")
    if not ok:
        raise HTTPException(status_code=502, detail=f"Teams hatası: {err}")
    return JSONResponse({"success": True})


@app.get("/api/operations/campaigns", summary="Operasyon Kampanyalarını Listele", tags=["Operations"])
async def api_operations_list_campaigns(
    status: str = "",
    limit: int = 50,
    _user=Depends(_get_request_user),
):
    agent = await _resolve_agent_instance()
    campaigns = await agent.memory.db.list_marketing_campaigns(
        tenant_id=_get_user_tenant(_user),
        status=status,
        limit=limit,
    )
    return JSONResponse({"success": True, "campaigns": [_serialize_campaign(item) for item in campaigns]})


@app.post("/api/operations/campaigns", summary="Operasyon Kampanyası Oluştur", tags=["Operations"])
async def api_operations_create_campaign(
    req: _CampaignCreateRequest,
    _user=Depends(_get_request_user),
):
    agent = await _resolve_agent_instance()
    db = agent.memory.db
    campaign = await db.upsert_marketing_campaign(
        tenant_id=_get_user_tenant(_user),
        name=req.name,
        channel=req.channel,
        objective=req.objective,
        status=req.status,
        owner_user_id=str(getattr(_user, "id", "") or ""),
        budget=float(req.budget or 0.0),
        metadata=dict(req.metadata or {}),
    )
    assets = []
    for item in req.initial_assets:
        assets.append(
            await db.add_content_asset(
                campaign_id=int(campaign.id),
                tenant_id=_get_user_tenant(_user),
                asset_type=item.asset_type,
                title=item.title,
                content=item.content,
                channel=item.channel,
                metadata=dict(item.metadata or {}),
            )
        )
    checklists = []
    for item in req.initial_checklists:
        checklists.append(
            await db.add_operation_checklist(
                campaign_id=int(campaign.id),
                tenant_id=_get_user_tenant(_user),
                title=item.title,
                items=list(item.items or []),
                status=item.status,
                owner_user_id=str(getattr(_user, "id", "") or ""),
            )
        )
    return JSONResponse(
        {
            "success": True,
            "campaign": _serialize_campaign(campaign),
            "assets": [_serialize_content_asset(item) for item in assets],
            "checklists": [_serialize_operation_checklist(item) for item in checklists],
        }
    )


@app.get("/api/operations/campaigns/{campaign_id}/assets", summary="Kampanya İçerik Varlıklarını Listele", tags=["Operations"])
async def api_operations_list_assets(
    campaign_id: int,
    limit: int = 100,
    _user=Depends(_get_request_user),
):
    agent = await _resolve_agent_instance()
    assets = await agent.memory.db.list_content_assets(
        tenant_id=_get_user_tenant(_user),
        campaign_id=campaign_id,
        limit=limit,
    )
    return JSONResponse({"success": True, "assets": [_serialize_content_asset(item) for item in assets]})


@app.post("/api/operations/campaigns/{campaign_id}/assets", summary="Kampanyaya İçerik Varlığı Ekle", tags=["Operations"])
async def api_operations_add_asset(
    campaign_id: int,
    req: _ContentAssetCreateRequest,
    _user=Depends(_get_request_user),
):
    agent = await _resolve_agent_instance()
    asset = await agent.memory.db.add_content_asset(
        campaign_id=campaign_id,
        tenant_id=_get_user_tenant(_user),
        asset_type=req.asset_type,
        title=req.title,
        content=req.content,
        channel=req.channel,
        metadata=dict(req.metadata or {}),
    )
    return JSONResponse({"success": True, "asset": _serialize_content_asset(asset)})


@app.get("/api/operations/campaigns/{campaign_id}/checklists", summary="Kampanya Operasyon Checklistlerini Listele", tags=["Operations"])
async def api_operations_list_checklists(
    campaign_id: int,
    limit: int = 100,
    _user=Depends(_get_request_user),
):
    agent = await _resolve_agent_instance()
    checklists = await agent.memory.db.list_operation_checklists(
        tenant_id=_get_user_tenant(_user),
        campaign_id=campaign_id,
        limit=limit,
    )
    return JSONResponse({"success": True, "checklists": [_serialize_operation_checklist(item) for item in checklists]})


@app.post("/api/operations/campaigns/{campaign_id}/checklists", summary="Kampanyaya Operasyon Checklisti Ekle", tags=["Operations"])
async def api_operations_add_checklist(
    campaign_id: int,
    req: _OperationChecklistCreateRequest,
    _user=Depends(_get_request_user),
):
    agent = await _resolve_agent_instance()
    checklist = await agent.memory.db.add_operation_checklist(
        campaign_id=campaign_id,
        tenant_id=_get_user_tenant(_user),
        title=req.title,
        items=list(req.items or []),
        status=req.status,
        owner_user_id=str(getattr(_user, "id", "") or ""),
    )
    return JSONResponse({"success": True, "checklist": _serialize_operation_checklist(checklist)})


# ─────────────────────────────────────────────
#  Proaktif Otonomi / Federation
# ─────────────────────────────────────────────


class _FederationTaskRequest(BaseModel):
    task_id: str = Field(..., description="Dış platform tarafından verilen görev kimliği")
    source_system: str = Field(..., description="Gönderen swarm platformu (örn. crewai, autogen)")
    source_agent: str = Field(..., description="Gönderen ajan veya workflow adı")
    target_agent: str = Field("supervisor", description="Sidar içinde hedef ajan/rol")
    goal: str = Field(..., description="Sidar'ın çalıştıracağı hedef görev")
    protocol: str = Field("federation.v1", description="Federation sözleşme sürümü")
    intent: str = Field("mixed", description="Görev intent tipi")
    context: dict[str, str] = Field(default_factory=dict, description="Yapısal bağlam")
    inputs: list[str] = Field(default_factory=list, description="Ek girdiler")
    meta: dict[str, str] = Field(default_factory=dict, description="Ek protokol meta verisi")
    correlation_id: str = Field("", description="Dış sistemlerle iz sürme için korelasyon kimliği")


class _FederationFeedbackRequest(BaseModel):
    feedback_id: str = Field(..., description="Dış sistem action feedback kaydı kimliği")
    source_system: str = Field(..., description="Feedback gönderen dış sistem")
    source_agent: str = Field(..., description="Feedback gönderen ajan/workflow")
    action_name: str = Field(..., description="Geri besleme verilen aksiyon adı")
    status: str = Field(..., description="Aksiyonun dış sistemdeki durumu")
    summary: str = Field(..., description="İnsan/ajan tarafından üretilen kısa özet")
    related_task_id: str = Field("", description="İlişkili federation task id")
    related_trigger_id: str = Field("", description="İlişkili autonomy trigger id")
    details: dict[str, Any] = Field(default_factory=dict, description="Detay payload")
    meta: dict[str, str] = Field(default_factory=dict, description="Ek protokol meta verisi")
    correlation_id: str = Field("", description="Dış sistemlerle paylaşılan korelasyon kimliği")


class _AutonomyWakeRequest(BaseModel):
    event_name: str = Field("manual_wake", description="Manuel/proaktif tetik olay adı")
    prompt: str = Field(..., description="Ajanın değerlendireceği proaktif prompt")
    source: str = Field("manual", description="Tetik kaynağı etiketi")
    payload: dict[str, Any] = Field(default_factory=dict, description="Ek olay payload'u")
    meta: dict[str, str] = Field(default_factory=dict, description="Ek meta verisi")


def _verify_hmac_signature(payload_body: bytes, secret_value: str, signature_header: str, *, label: str) -> None:
    secret = str(secret_value or "").encode("utf-8")
    if not secret:
        return
    if not signature_header:
        raise HTTPException(status_code=401, detail=f"{label} imza başlığı eksik.")
    expected_signature = "sha256=" + hmac.new(secret, payload_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, signature_header):
        raise HTTPException(status_code=401, detail="Geçersiz imza.")


@app.post(
    "/api/autonomy/webhook/{source}",
    summary="Otonom Webhook Tetikleyicisi",
    description="Harici sistem olaylarını Sidar'a otonom trigger olarak iletir.",
)
async def autonomy_webhook(
    source: str,
    request: Request,
    x_sidar_signature: str = Header(default=""),
):
    """Genel amaçlı webhook olaylarını ajanın proaktif değerlendirmesine iletir."""
    if not bool(getattr(cfg, "ENABLE_EVENT_WEBHOOKS", True)):
        raise HTTPException(status_code=503, detail="Event webhook özelliği devre dışı.")

    payload_body = await request.body()
    _verify_hmac_signature(
        payload_body,
        str(getattr(cfg, "AUTONOMY_WEBHOOK_SECRET", "") or ""),
        x_sidar_signature,
        label="Autonomy webhook",
    )

    try:
        data = json.loads(payload_body.decode("utf-8")) if payload_body else {}
    except json.JSONDecodeError:
        return JSONResponse({"success": False, "error": "Geçersiz JSON payload'u"}, status_code=400)

    payload_dict = data if isinstance(data, dict) else {"payload": data}
    resolved_event_name = str(payload_dict.get("event_name", source) or source)
    ci_context = _resolve_ci_failure_context(resolved_event_name, payload_dict)
    federation_workflow = None if ci_context else await _run_event_driven_federation_workflow(
        source=source,
        event_name=resolved_event_name,
        payload=payload_dict,
    )
    dispatch_payload = ci_context if ci_context else payload_dict
    dispatch_meta = {"source": source, "provider": source, "ci_failure": "true" if ci_context else "false"}
    if federation_workflow:
        dispatch_payload = _embed_event_driven_federation_payload(payload_dict, federation_workflow)
        dispatch_meta.update({
            "event_driven_federation": "true",
            "workflow_type": str(federation_workflow.get("workflow_type") or "external_event"),
            "correlation_id": str(federation_workflow.get("correlation_id") or ""),
        })
    result = await _dispatch_autonomy_trigger(
        trigger_source=f"webhook:{source}:ci_failure" if ci_context else f"webhook:{source}",
        event_name="ci_failure_remediation" if ci_context else resolved_event_name,
        payload=dispatch_payload,
        meta=dispatch_meta,
    )
    return JSONResponse({"success": True, "result": result, "event_driven_federation": federation_workflow})


@app.post(
    "/api/autonomy/wake",
    summary="Manuel Otonomi Uyanışı",
    description="SIDAR'ı kullanıcı veya sistem tarafından proaktif görev için uyandırır.",
)
async def autonomy_wake(req: _AutonomyWakeRequest):
    """Webhook dışı manuel/proaktif tetik giriş noktası."""
    payload = dict(req.payload or {})
    payload["prompt"] = req.prompt.strip()
    result = await _await_if_needed(_dispatch_autonomy_trigger(
        trigger_source=f"manual:{req.source.strip() or 'manual'}",
        event_name=req.event_name.strip() or "manual_wake",
        payload=payload,
        meta=dict(req.meta or {}),
    ))
    return JSONResponse({"success": True, "result": result})


@app.get(
    "/api/autonomy/activity",
    summary="Otonomi Aktivite Akışı",
    description="Webhook/cron/manual kaynaklı son proaktif tetik geçmişini döndürür.",
)
async def autonomy_activity(limit: int = 20):
    """Son proaktif tetik kayıtlarını UI ve operasyon panelleri için sunar."""
    agent = await _resolve_agent_instance()
    return JSONResponse({"success": True, "activity": agent.get_autonomy_activity(limit=limit)})


@app.post(
    "/api/swarm/federation",
    summary="Dış Swarm Federation Görevi",
    description="CrewAI/AutoGen gibi dış platformlardan gelen görevleri Sidar içinde çalıştırır.",
)
async def swarm_federation_execute(
    req: _FederationTaskRequest,
    x_sidar_signature: str = Header(default=""),
):
    """Federasyon görevlerini Sidar içinde çalıştırıp yapısal sonuç döndürür."""
    if not bool(getattr(cfg, "ENABLE_SWARM_FEDERATION", True)):
        raise HTTPException(status_code=503, detail="Swarm federation özelliği devre dışı.")

    raw_body = json.dumps(req.__dict__, ensure_ascii=False, sort_keys=True).encode("utf-8")
    _verify_hmac_signature(
        raw_body,
        str(getattr(cfg, "SWARM_FEDERATION_SHARED_SECRET", "") or ""),
        x_sidar_signature,
        label="Federation",
    )

    envelope = FederationTaskEnvelope(
        task_id=req.task_id,
        source_system=req.source_system,
        source_agent=req.source_agent,
        target_system="sidar",
        target_agent=req.target_agent,
        goal=req.goal,
        protocol=normalize_federation_protocol(req.protocol),
        intent=req.intent,
        context=dict(req.context or {}),
        inputs=list(req.inputs or []),
        meta=dict(req.meta or {}),
        correlation_id=req.correlation_id,
    )
    federation_payload = {
        "kind": "federation_task",
        "federation_task": asdict(envelope),
        "federation_prompt": envelope.to_prompt(),
        "task_id": envelope.task_id,
        "source_system": envelope.source_system,
        "source_agent": envelope.source_agent,
        "target_agent": envelope.target_agent,
        "correlation_id": envelope.correlation_id,
    }
    trigger_result = await _dispatch_autonomy_trigger(
        trigger_source=f"federation:{envelope.source_system}",
        event_name="federation_task",
        payload=federation_payload,
        meta={
            "protocol": envelope.protocol,
            "protocol_legacy_alias": LEGACY_FEDERATION_PROTOCOL_V1,
            "correlation_id": envelope.correlation_id,
        },
    )
    summary = str(trigger_result.get("summary", "") or "").strip()
    result = FederationTaskResult(
        task_id=envelope.task_id,
        source_system="sidar",
        source_agent=envelope.target_agent,
        target_system=envelope.source_system,
        target_agent=envelope.source_agent,
        status="success" if summary else "failed",
        summary=summary or "Sidar görev için çıktı üretemedi.",
        protocol=envelope.protocol,
        correlation_id=envelope.correlation_id,
        meta={
            "protocol": envelope.protocol,
            "protocol_legacy_alias": LEGACY_FEDERATION_PROTOCOL_V1,
            "correlation_id": envelope.correlation_id,
            "autonomy_trigger_id": str(trigger_result.get("trigger_id", "") or ""),
            "action_feedback_endpoint": "/api/swarm/federation/feedback",
        },
    )
    return JSONResponse({"success": True, "result": asdict(result)})


@app.post(
    "/api/swarm/federation/feedback",
    summary="Dış Swarm Action Feedback",
    description="Dış swarm sistemlerinden gelen action feedback sinyallerini autonomy korelasyon akışına bağlar.",
)
async def swarm_federation_feedback(
    req: _FederationFeedbackRequest,
    x_sidar_signature: str = Header(default=""),
):
    if not bool(getattr(cfg, "ENABLE_SWARM_FEDERATION", True)):
        raise HTTPException(status_code=503, detail="Swarm federation özelliği devre dışı.")

    raw_body = json.dumps(req.__dict__, ensure_ascii=False, sort_keys=True).encode("utf-8")
    _verify_hmac_signature(
        raw_body,
        str(getattr(cfg, "SWARM_FEDERATION_SHARED_SECRET", "") or ""),
        x_sidar_signature,
        label="Federation feedback",
    )

    feedback = ActionFeedback(
        feedback_id=req.feedback_id,
        source_system=req.source_system,
        source_agent=req.source_agent,
        action_name=req.action_name,
        status=req.status,
        summary=req.summary,
        related_task_id=req.related_task_id,
        related_trigger_id=req.related_trigger_id,
        details=dict(req.details or {}),
        meta=dict(req.meta or {}),
        correlation_id=derive_correlation_id(req.correlation_id, req.related_task_id, req.related_trigger_id, req.feedback_id),
    )
    trigger = feedback.to_external_trigger()
    result = await _dispatch_autonomy_trigger(
        trigger_source=trigger.source,
        event_name=trigger.event_name,
        payload=dict(trigger.payload or {}),
        meta=dict(trigger.meta or {}),
    )
    return JSONResponse(
        {
            "success": True,
            "result": result,
            "feedback": {
                "feedback_id": feedback.feedback_id,
                "correlation_id": feedback.correlation_id,
                "related_task_id": feedback.related_task_id,
                "related_trigger_id": feedback.related_trigger_id,
            },
        }
    )


# ─────────────────────────────────────────────
#  GitHub Webhook
# ─────────────────────────────────────────────

@app.post(
    "/api/webhook",
    summary="GitHub Webhook Alıcısı",
    description="GitHub repository'sinden gelen Push, PR ve Issue olaylarını dinler ve doğrular.",
    responses={
        200: {"description": "Webhook başarıyla işlendi"},
        401: {"description": "Geçersiz imza"},
    },
)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
):
    """GitHub'dan gelen webhook tetiklemelerini karşılar."""
    payload_body = await request.body()
    secret = getattr(cfg, "GITHUB_WEBHOOK_SECRET", "").encode("utf-8")

    if not secret:
        logger.warning(
            "GITHUB_WEBHOOK_SECRET yapılandırılmamış — webhook imza doğrulaması atlanıyor. "
            "Üretim ortamında mutlaka ayarlayın."
        )
    if secret:
        if not x_hub_signature_256:
            raise HTTPException(status_code=401, detail="X-Hub-Signature-256 başlığı eksik.")

        expected_signature = "sha256=" + hmac.new(secret, payload_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_signature, x_hub_signature_256):
            logger.warning("Geçersiz GitHub Webhook imzası algılandı!")
            raise HTTPException(status_code=401, detail="Geçersiz imza.")

    try:
        data = json.loads(payload_body.decode("utf-8"))
    except json.JSONDecodeError:
        return JSONResponse({"success": False, "error": "Geçersiz JSON payload'u"}, status_code=400)

    agent = _await_if_needed(_resolve_agent_instance())
    if inspect.isawaitable(agent):
        agent = await agent
    msg = ""

    if x_github_event == "push":
        pusher = data.get("pusher", {}).get("name", "Biri")
        ref = data.get("ref", "")
        branch = ref.split("/")[-1] if "/" in ref else ref
        msg = f"[GITHUB BİLDİRİMİ] '{pusher}' adlı kullanıcı '{branch}' dalına yeni kod yükledi (push)."
    elif x_github_event == "pull_request":
        action = data.get("action")
        pr_title = data.get("pull_request", {}).get("title", "")
        pr_num = data.get("pull_request", {}).get("number", "")
        msg = f"[GITHUB BİLDİRİMİ] Pull Request #{pr_num} durumu güncellendi ({action}): {pr_title}"
    elif x_github_event == "issues":
        action = data.get("action")
        issue_title = data.get("issue", {}).get("title", "")
        issue_num = data.get("issue", {}).get("number", "")
        msg = f"[GITHUB BİLDİRİMİ] Issue #{issue_num} durumu güncellendi ({action}): {issue_title}"

    ci_context = _resolve_ci_failure_context(x_github_event, data if isinstance(data, dict) else {})
    if ci_context:
        msg = (
            "[GITHUB CI] Başarısız pipeline algılandı: "
            f"{ci_context.get('workflow_name', x_github_event)} "
            f"(run_id={ci_context.get('run_id', '-')}, conclusion={ci_context.get('conclusion', '-')})"
        )

    if msg:
        logger.info("Webhook işlendi: %s", msg)
        await _await_if_needed(agent.memory.add("user", msg))
        await _await_if_needed(
            agent.memory.add(
                "assistant",
                "GitHub bildirimini kayıtlarıma aldım. İstenirse 'github_commits' veya PR/Issue araçlarımla detayları inceleyebilirim.",
            )
        )
        if bool(getattr(cfg, "ENABLE_EVENT_WEBHOOKS", True)):
            with contextlib.suppress(Exception):
                payload_dict = data if isinstance(data, dict) else {"payload": data}
                federation_workflow = None if ci_context else await _await_if_needed(
                    _run_event_driven_federation_workflow(
                        source="github",
                        event_name=x_github_event,
                        payload=payload_dict,
                    )
                )
                dispatch_payload = ci_context if ci_context else payload_dict
                dispatch_meta = {"source": "github", "provider": "github", "ci_failure": "true" if ci_context else "false"}
                if federation_workflow:
                    dispatch_payload = _embed_event_driven_federation_payload(payload_dict, federation_workflow)
                    dispatch_meta.update({
                        "event_driven_federation": "true",
                        "workflow_type": str(federation_workflow.get("workflow_type") or "external_event"),
                        "correlation_id": str(federation_workflow.get("correlation_id") or ""),
                    })
                await _await_if_needed(
                    _dispatch_autonomy_trigger(
                        trigger_source="webhook:github:ci_failure" if ci_context else "webhook:github",
                        event_name="ci_failure_remediation" if ci_context else x_github_event,
                        payload=dispatch_payload,
                        meta=dispatch_meta,
                    )
                )

    return JSONResponse({"success": True, "event": x_github_event, "message": "İşlendi"})


@app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
async def spa_fallback(full_path: str):
    normalized = (full_path or "").strip()
    if not normalized:
        maybe_response = index()
        if inspect.isawaitable(maybe_response):
            return await maybe_response
        return maybe_response
    first_segment = normalized.split("/", 1)[0].lower()
    if first_segment in {"api", "vendor", "static", "assets", "ws", "webhook"}:
        return Response(status_code=404)
    if "." in Path(normalized).name:
        return Response(status_code=404)
    maybe_response = index()
    response = await maybe_response if inspect.isawaitable(maybe_response) else maybe_response
    if getattr(response, "status_code", None) == 500:
        return HTMLResponse(
            "<h1>SİDAR arayüzü için SPA fallback etkin.</h1>",
            status_code=200,
        )
    return response


# ─────────────────────────────────────────────
#  BAŞLATMA
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Sidar Web Arayüzü")
    parser.add_argument(
        "--host", default=cfg.WEB_HOST,
        help=f"Sunucu adresi (varsayılan: {cfg.WEB_HOST})"
    )
    parser.add_argument(
        "--port", type=int, default=cfg.WEB_PORT,
        help=f"Port numarası (varsayılan: {cfg.WEB_PORT})"
    )
    parser.add_argument(
        "--level", choices=["restricted", "sandbox", "full"],
        help="Erişim seviyesi (varsayılan: .env'deki değer)"
    )
    parser.add_argument(
        "--provider", choices=["ollama", "gemini", "openai", "anthropic"],
        help="AI sağlayıcısı (varsayılan: .env'deki değer)"
    )
    parser.add_argument(
        "--log", default="info",
        help="Log seviyesi (debug/info/warning)"
    )
    args, _unknown_args = parser.parse_known_args()

    # Dinamik config override
    if args.level:
        cfg.ACCESS_LEVEL = args.level
    if args.provider:
        cfg.AI_PROVIDER = args.provider

    # Ajan önceden başlat (ilk istekte gecikme olmasın).
    # Bellek katmanı native-async olduğu için initialize() adımı burada tamamlanır.
    global _agent
    try:
        _agent = SidarAgent(cfg)
        initialize_result = getattr(_agent, "initialize", None)
        if callable(initialize_result):
            maybe_coro = initialize_result()
            if inspect.isawaitable(maybe_coro):
                asyncio.run(maybe_coro)
    except Exception as exc:
        logger.warning("Web server agent ön başlatması başarısız; sunucu yine de başlatılacak: %s", exc)
        _agent = None

    display_host = "localhost" if args.host in ("0.0.0.0", "") else args.host
    agent_version = getattr(_agent, "VERSION", "") if _agent is not None else ""
    version_label = f"v{agent_version}" if agent_version else f"v{getattr(cfg, 'VERSION', '?')}"

    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║  SİDAR Web Arayüzü                   ║")
    print(f"  ║  http://{display_host}:{args.port:<27}║")
    print("  ╚══════════════════════════════════════╝")
    print(f"     Sürüm: {version_label}")
    print()


    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log.lower(),
    )


if __name__ == "__main__":
    main()
