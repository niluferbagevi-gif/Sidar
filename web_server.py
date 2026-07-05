"""
Sidar Project - Web Arayüzü Sunucusu
FastAPI + WebSocket ile asenkron (async) çift yönlü akış destekli chat arayüzü.

Başlatmak için:
    python web_server.py
    python web_server.py --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import ast
import asyncio
import atexit
import builtins
import contextlib
import hashlib
import hmac
import importlib
import importlib.util
import inspect
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess  # nosec B404
import sys
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, cast

import anyio
from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
)
from fastapi import (
    WebSocketDisconnect as _FastAPIWebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from agent.base_agent import BaseAgent
from agent.core.contracts import (
    LEGACY_FEDERATION_PROTOCOL_V1,
    ActionFeedback,
    ExternalTrigger,
    FederationTaskEnvelope,
    FederationTaskResult,
    derive_correlation_id,
    normalize_federation_protocol,
)
from agent.core.event_stream import get_agent_event_bus
from agent.registry import AgentRegistry
from agent.sidar_agent import SidarAgent
from agent.swarm import SwarmOrchestrator, SwarmTask
from config import Config, get_config, register_config_reload_callback
from core.ci_remediation import build_ci_failure_context
from core.hitl import get_hitl_gate, get_hitl_store, set_hitl_broadcast_hook
from core.llm_client import LLMAPIError
from core.llm_metrics import (
    get_llm_metrics_collector,
    reset_current_metrics_user_id,
    set_current_metrics_user_id,
)
from managers.system_health import render_llm_metrics_prometheus
from sidar_assets.paths import web_dist_path
from web import app_factory as _app_factory
from web import bootstrap as web_bootstrap
from web import security as web_security
from web.bootstrap import make_static_files_with_staticfiles as _make_static_files_with_staticfiles
from web.middleware.cors import configure_loopback_cors
from web.middleware.ratelimit import (
    ddos_rate_limit_middleware_impl,
    rate_limit_middleware_impl,
)
from web.routes import autonomy as autonomy_routes
from web.routes import collaboration as collaboration_routes
from web.routes import federation as federation_routes
from web.routes import health_runtime as health_runtime_routes
from web.routes import integrations as integrations_routes
from web.routes import memory_feedback as memory_feedback_routes
from web.routes import operations as operations_routes
from web.routes import operations_models as operations_route_models
from web.routes import plugin_marketplace as plugin_marketplace_routes
from web.routes import vision as vision_routes
from web.routes import ws_chat as ws_chat_routes
from web.routes import ws_voice as ws_voice_routes
from web.routes.agent import build_agent_router
from web.routes.auth_admin import build_auth_admin_router
from web.routes.health import build_health_router
from web.routes.hitl import build_hitl_router
from web.routes.metrics import build_metrics_router
from web.routes.orchestration import build_orchestration_router
from web.routes.project_ops import build_project_ops_router
from web.routes.rag import build_rag_router
from web.routes.static import build_frontend_router
from web.routes.webhooks import build_webhooks_router
from web.security import (
    build_user_from_jwt_payload,
    get_jwt_secret,
    get_request_user,
    is_admin_user,
    issue_auth_token,
    require_admin_user,
    require_metrics_access,
    resolve_user_from_token,
)

_ANYIO_CLOSED = anyio.ClosedResourceError
WebSocketDisconnect = _FastAPIWebSocketDisconnect

# OpenTelemetry bağımlılıkları config.Config.init_telemetry içinde lazy import edilir.
# Bu fallback globals yalnız eski/test fallback yolu için korunur ve testlerde monkeypatch edilir.
trace: Any = None
OTLPSpanExporter: Any = None
FastAPIInstrumentor: Any = None
HTTPXClientInstrumentor: Any = None
Resource: Any = None
TracerProvider: Any = None
BatchSpanProcessor: Any = None

with contextlib.suppress(ImportError):
    from opentelemetry import trace as _otel_trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter as _OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import (
        FastAPIInstrumentor as _FastAPIInstrumentor,
    )
    from opentelemetry.instrumentation.httpx import (
        HTTPXClientInstrumentor as _HTTPXClientInstrumentor,
    )
    from opentelemetry.sdk.resources import Resource as _Resource
    from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor as _BatchSpanProcessor,
    )

    trace = _otel_trace
    OTLPSpanExporter = _OTLPSpanExporter
    FastAPIInstrumentor = _FastAPIInstrumentor
    HTTPXClientInstrumentor = _HTTPXClientInstrumentor
    Resource = _Resource
    TracerProvider = _TracerProvider
    BatchSpanProcessor = _BatchSpanProcessor


logger = logging.getLogger(__name__)
print = builtins.print


def _resolve_psutil_module() -> Any:
    """Resolve psutil through Python import hooks for testable fallback behavior."""
    return importlib.import_module("psutil")


# ─────────────────────────────────────────────
#  HITL WebSocket Yayın Kümesi
# ─────────────────────────────────────────────
_hitl_ws_clients: set[WebSocket] = set()


class _CollaborationParticipant(collaboration_routes.CollaborationParticipant):
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
        super().__init__(
            websocket,
            user_id,
            username,
            display_name,
            role,
            can_write,
            write_scopes,
            joined_at,
            now_iso=_collaboration_now_iso,
        )


_CollaborationRoom = collaboration_routes.CollaborationRoom
_collaboration_rooms: dict[str, _CollaborationRoom] = {}


def _collaboration_now_iso() -> str:
    return collaboration_routes.collaboration_now_iso()


def _normalize_room_id(room_id: str) -> str:
    return collaboration_routes.normalize_room_id(room_id)


def _socket_key(websocket: WebSocket) -> int:
    return collaboration_routes.socket_key(websocket)


def _serialize_collaboration_participant(participant: _CollaborationParticipant) -> dict[str, Any]:
    return collaboration_routes.serialize_collaboration_participant(participant)


def _normalize_collaboration_role(role: str) -> str:
    return collaboration_routes.normalize_collaboration_role(role)


def _collaboration_write_scopes_for_role(role: str, room_id: str) -> list[str]:
    return collaboration_routes.collaboration_write_scopes_for_role(
        role, room_id, base_dir=Path(getattr(cfg, "BASE_DIR", "."))
    )


def _collaboration_command_requires_write(command: str) -> bool:
    return collaboration_routes.collaboration_command_requires_write(command)


def _mask_collaboration_text(text: str) -> str:
    return collaboration_routes.mask_collaboration_text(
        text, import_module=importlib.import_module, logger_obj=logger
    )


def _serialize_collaboration_room(room: _CollaborationRoom) -> dict[str, Any]:
    return collaboration_routes.serialize_collaboration_room(room)


def _append_room_message(
    room: _CollaborationRoom, payload: dict[str, Any], *, limit: int = 200
) -> None:
    collaboration_routes.append_room_message(room, payload, limit=limit)


def _append_room_telemetry(
    room: _CollaborationRoom, payload: dict[str, Any], *, limit: int = 200
) -> None:
    collaboration_routes.append_room_telemetry(
        room, payload, mask_text=_mask_collaboration_text, limit=limit
    )


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
    return collaboration_routes.build_room_message(
        room_id=room_id,
        role=role,
        content=content,
        author_name=author_name,
        author_id=author_id,
        kind=kind,
        request_id=request_id,
        mask_text=_mask_collaboration_text,
        now_iso=_collaboration_now_iso,
    )


async def _broadcast_room_payload(room: _CollaborationRoom, payload: dict[str, Any]) -> None:
    await collaboration_routes.broadcast_room_payload(room, payload)


async def _emit_control_room_event(
    room_id: str,
    *,
    kind: str,
    source: str,
    content: str,
    payload: dict[str, Any] | None = None,
) -> None:
    normalized = _normalize_room_id(room_id or "ops:control")
    room = _collaboration_rooms.setdefault(normalized, _CollaborationRoom(room_id=normalized))
    event = {
        "id": secrets.token_hex(8),
        "room_id": normalized,
        "kind": kind or "status",
        "source": source or "api",
        "content": _mask_collaboration_text(content),
        "payload": payload or {},
        "ts": _collaboration_now_iso(),
    }
    _append_room_telemetry(room, event)
    await _broadcast_room_payload(room, {"type": "collaboration_event", "event": event})


async def _join_collaboration_room(
    websocket: WebSocket,
    *,
    room_id: str,
    user_id: str,
    username: str,
    display_name: str,
    user_role: str = "user",
) -> _CollaborationRoom:
    return await collaboration_routes.join_collaboration_room(
        _collaboration_rooms,
        websocket,
        room_id=room_id,
        user_id=user_id,
        username=username,
        display_name=display_name,
        user_role=user_role,
        base_dir=Path(getattr(cfg, "BASE_DIR", ".")),
        socket_key_func=_socket_key,
        leave_room=_leave_collaboration_room,
        now_iso=_collaboration_now_iso,
    )


async def _leave_collaboration_room(websocket: WebSocket) -> None:
    await collaboration_routes.leave_collaboration_room(
        _collaboration_rooms, websocket, socket_key_func=_socket_key
    )


def _is_sidar_mention(message: str) -> bool:
    return collaboration_routes.is_sidar_mention(message)


def _strip_sidar_mention(message: str) -> str:
    return collaboration_routes.strip_sidar_mention(message)


def _build_collaboration_prompt(room: _CollaborationRoom, *, actor_name: str, command: str) -> str:
    return collaboration_routes.build_collaboration_prompt(
        room, actor_name=actor_name, command=command
    )


def _iter_stream_chunks(text: str, *, size: int = 180) -> list[str]:
    clean = str(text or "")
    if not clean:
        return []
    return [clean[index : index + size] for index in range(0, len(clean), size)]


async def _hitl_broadcast(payload: dict[str, Any]) -> None:
    """HITL olaylarını bağlı tüm admin WebSocket bağlantılarına gönder."""
    dead = set()
    for ws in list(_hitl_ws_clients):
        try:
            await ws.send_json(payload)
        except (RuntimeError, WebSocketDisconnect, _ANYIO_CLOSED) as exc:
            logger.debug("HITL WebSocket yayını başarısız oldu; bağlantı düşürülecek: %s", exc)
            dead.add(ws)
    _hitl_ws_clients.difference_update(dead)


set_hitl_broadcast_hook(_hitl_broadcast)

# ─────────────────────────────────────────────
#  UYGULAMA BAŞLATMA
# ─────────────────────────────────────────────


def _refresh_cfg(config_instance: Config | None = None) -> Config:
    """Keep web_server's cached Config reference aligned with config.reload_environment()."""
    global cfg
    cfg = config_instance if config_instance is not None else get_config()
    return cfg


def _on_config_reload(config_instance: Config) -> None:
    """Callback hook used by config.reload_environment(); aligns the cached Config reference."""
    _refresh_cfg(config_instance)


register_config_reload_callback(_on_config_reload)
cfg = _refresh_cfg()
Config.initialize_directories()
_agent: SidarAgent | None = None
# Event loop başlamadan önce asyncio.Lock() oluşturmak Python <3.10'da
# DeprecationWarning üretir. Lazy başlatma ile bu risk tamamen ortadan kalkar.
_agent_lock: asyncio.Lock | None = None
_rag_prewarm_task: asyncio.Task[Any] | None = None
_autonomy_cron_task: asyncio.Task[Any] | None = None
_autonomy_cron_stop: asyncio.Event | None = None
_nightly_memory_task: asyncio.Task[Any] | None = None
_nightly_memory_stop: asyncio.Event | None = None
_shutdown_cleanup_done = False
MAX_FILE_CONTENT_BYTES = 1_048_576  # 1 MB


_SAFE_PS_PATHS: tuple[str, ...] = ("/bin/ps", "/usr/bin/ps", "/sbin/ps", "/usr/sbin/ps")


def _resolve_safe_ps_binary() -> str | None:
    """Yalnızca sistem-yönetimi dizinlerindeki bilinen ps ikilisini döndürür.

    SAST (Bandit B603/B607): subprocess çağrılırken `ps` ikilisinin PATH
    üzerinden alınması, ortam değişkeni manipülasyonuyla rastgele bir ikilinin
    çalıştırılmasına yol açabilir. Bu helper, ikiliyi yalnızca whitelist'teki
    absolute path'lerden çözer.
    """
    for candidate in _SAFE_PS_PATHS:
        try:
            p = Path(candidate)
            if p.is_file() and os.access(candidate, os.X_OK):
                return candidate
        except Exception:  # nosec B112
            # Adayın stat/access kontrolü başarısızsa sessizce sıradakine geçilir.
            continue
    try:
        which_path = shutil.which("ps")
    except Exception:
        which_path = None
    if which_path and which_path in _SAFE_PS_PATHS:
        return which_path
    return None


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

    # Güvenlik (SAST B603/B607): ps ikilisi PATH manipülasyonuna karşı yalnızca
    # sistem-yönetimi dizinlerindeki bilinen absolute path'lerden çözülür.
    ps_binary = _resolve_safe_ps_binary()
    if ps_binary is None:
        return []

    try:
        raw = subprocess.check_output(  # nosec
            [ps_binary, "-eo", "pid=,ppid=,comm=,args="],
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

    def _sink(event: Any) -> None:
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
    collector._sidar_usage_sink_bound = True  # type: ignore[attr-defined, unused-ignore]


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
    global _agent, _agent_lock
    runtime_state = _runtime_state()
    if runtime_state is not None and getattr(runtime_state, "agent", None) is not None:
        _agent = runtime_state.agent
        if _agent is not None:
            return _agent
    if _agent is not None:
        if runtime_state is not None:
            runtime_state.agent = _agent
        return _agent
    if runtime_state is not None and getattr(runtime_state, "agent_lock", None) is not None:
        _agent_lock = runtime_state.agent_lock
    if _agent_lock is None:
        _agent_lock = asyncio.Lock()
        if runtime_state is not None:
            runtime_state.agent_lock = _agent_lock
    async with _agent_lock:
        if _agent is None:
            _agent = SidarAgent(cfg)
            await _agent.initialize()
            _bind_llm_usage_sink(_agent)
            if runtime_state is not None:
                runtime_state.agent = _agent
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


def _autonomy_service_actor(trigger_source: str) -> tuple[str, str]:
    """Return the explicit service actor used by userless autonomy triggers."""
    configured_user = str(
        getattr(cfg, "AUTONOMY_SERVICE_USER_ID", "")
        or getattr(cfg, "SYSTEM_USER_ID", "")
        or "system:autonomy"
    ).strip()
    service_user_id = configured_user or "system:autonomy"
    source_label = str(trigger_source or "external").strip() or "external"
    return service_user_id, f"autonomy:{source_label}"


async def _prepare_autonomy_memory_context(agent: Any, trigger_source: str) -> None:
    """Bind a service user before system webhook/cron/federation memory operations."""
    memory = getattr(agent, "memory", None)
    set_active_user = getattr(memory, "set_active_user", None)
    if not callable(set_active_user):
        return
    service_user_id, service_username = _autonomy_service_actor(trigger_source)
    maybe_result = set_active_user(service_user_id, service_username)
    if inspect.isawaitable(maybe_result):
        await maybe_result


async def _dispatch_autonomy_trigger(
    *,
    trigger_source: str,
    event_name: str,
    payload: dict[str, Any],
    meta: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Webhook/cron/federation kaynaklı otonom tetikleyiciyi ajana ilet."""
    agent = await _resolve_agent_instance()
    await _prepare_autonomy_memory_context(agent, trigger_source)
    trigger = ExternalTrigger(
        trigger_id=f"trigger-{secrets.token_hex(6)}",
        source=trigger_source,
        event_name=event_name,
        payload=payload,
        meta=dict(meta or {}),
    )
    fallback_prompt = (
        str(payload.get("federation_prompt") or "").strip() if isinstance(payload, dict) else ""
    )
    if (
        not fallback_prompt
        and isinstance(payload, dict)
        and payload.get("kind") == "action_feedback"
    ):
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
    failure_conclusions = {
        "failure",
        "timed_out",
        "cancelled",
        "startup_failure",
        "action_required",
    }

    if bool(data.get("ci_failure") or data.get("pipeline_failed")) or normalized in {
        "ci_failure_remediation",
        "ci_pipeline_failed",
        "pipeline_failed",
    }:
        return {
            "kind": "generic_ci_failure",
            "repo": str(data.get("repo") or data.get("repository") or "").strip(),
            "workflow_name": str(
                data.get("workflow_name")
                or data.get("pipeline")
                or data.get("job_name")
                or "ci_failure"
            ).strip(),
            "run_id": str(
                data.get("run_id") or data.get("pipeline_id") or data.get("build_id") or ""
            ).strip(),
            "run_number": str(data.get("run_number") or data.get("pipeline_number") or "").strip(),
            "branch": str(data.get("branch") or data.get("ref") or "").strip(),
            "base_branch": str(
                data.get("base_branch") or data.get("target_branch") or "main"
            ).strip(),
            "sha": str(data.get("sha") or data.get("commit") or "").strip(),
            "conclusion": str(data.get("conclusion") or "failure").strip(),
            "status": str(data.get("status") or "completed").strip(),
            "html_url": str(data.get("html_url") or data.get("pipeline_url") or "").strip(),
            "jobs_url": str(data.get("jobs_url") or "").strip(),
            "logs_url": str(data.get("logs_url") or data.get("log_url") or "").strip(),
            "log_excerpt": str(
                data.get("log_excerpt")
                or data.get("logs")
                or data.get("error")
                or data.get("details")
                or ""
            ).strip(),
            "failure_summary": str(
                data.get("failure_summary")
                or data.get("summary")
                or data.get("message")
                or "ci failure"
            ).strip(),
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
                base_branch = str(
                    (pull_requests[0] or {}).get("base", {}).get("ref", "") or ""
                ).strip()
            return {
                "kind": "workflow_run",
                "repo": repo_name,
                "workflow_name": str(workflow.get("name") or "workflow_run").strip(),
                "run_id": str(workflow.get("id") or "").strip(),
                "run_number": str(workflow.get("run_number") or "").strip(),
                "branch": str(workflow.get("head_branch") or "").strip(),
                "base_branch": base_branch
                or str(repository.get("default_branch") or "main").strip(),
                "sha": str(workflow.get("head_sha") or "").strip(),
                "conclusion": str(workflow.get("conclusion") or "").strip(),
                "status": str(workflow.get("status") or "").strip(),
                "html_url": str(workflow.get("html_url") or "").strip(),
                "jobs_url": str(workflow.get("jobs_url") or "").strip(),
                "logs_url": str(workflow.get("logs_url") or "").strip(),
                "log_excerpt": str(
                    workflow.get("display_title") or workflow.get("name") or ""
                ).strip(),
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
                "log_excerpt": "\n\n".join(
                    filter(
                        None,
                        [
                            str(output.get("summary") or "").strip(),
                            str(output.get("text") or "").strip(),
                        ],
                    )
                ),
                "failure_summary": str(
                    output.get("title") or check_run.get("name") or "check failed"
                ).strip(),
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
                "log_excerpt": str(
                    suite.get("app", {}).get("name") or "check_suite_failure"
                ).strip(),
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


def _build_event_driven_federation_spec(
    source: str, event_name: str, payload: dict[str, Any]
) -> dict[str, Any] | None:
    source_key = str(source or "").strip().lower()
    event_key = str(event_name or "").strip().lower()
    data = dict(payload or {})

    if source_key in {"jira", "atlassian", "jira_cloud"}:
        issue = dict(data.get("issue") or data)
        action = (
            str(data.get("action") or data.get("webhookEvent") or event_key or "").strip().lower()
        )
        issue_key = str(issue.get("key") or issue.get("id") or data.get("issue_key") or "").strip()
        summary = str(
            issue.get("title") or issue.get("summary") or data.get("summary") or ""
        ).strip()
        if issue_key and (
            "created" in action
            or event_key in {"issue_created", "issue_opened", "jira_issue_created"}
        ):
            project_key = str(
                (issue.get("fields") or {}).get("project", {}).get("key")
                or data.get("project")
                or ""
            ).strip()
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
                    "issue_status": str(
                        (issue.get("fields") or {}).get("status", {}).get("name")
                        or data.get("status")
                        or ""
                    ).strip(),
                    "issue_type": str(
                        (issue.get("fields") or {}).get("issuetype", {}).get("name")
                        or data.get("issue_type")
                        or ""
                    ).strip(),
                },
                "inputs": [
                    f"issue_key={issue_key}",
                    f"summary={summary}",
                    f"description={_trim_autonomy_text((issue.get('fields') or {}).get('description') or data.get('description') or '', 1000)}",
                ],
                "correlation_id": derive_correlation_id(
                    data.get("correlation_id", ""), issue_key, summary
                ),
            }

    if source_key == "github":
        pr = dict(data.get("pull_request") or {})
        action = str(data.get("action") or event_key or "").strip().lower()
        pr_number = str(pr.get("number") or data.get("number") or "").strip()
        pr_title = str(pr.get("title") or data.get("title") or "").strip()
        if pr_number and action in {"opened", "reopened", "ready_for_review", "synchronize"}:
            repo = str(
                (data.get("repository") or {}).get("full_name") or data.get("repo") or ""
            ).strip()
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
                    "base_branch": str(
                        (pr.get("base") or {}).get("ref") or data.get("base_branch") or ""
                    ).strip(),
                    "head_branch": str(
                        (pr.get("head") or {}).get("ref") or data.get("branch") or ""
                    ).strip(),
                    "author": str(
                        (pr.get("user") or {}).get("login")
                        or data.get("sender", {}).get("login")
                        or ""
                    ).strip(),
                },
                "inputs": [
                    f"pr_number={pr_number}",
                    f"title={pr_title}",
                    f"body={_trim_autonomy_text(pr.get('body') or data.get('body') or '', 1000)}",
                ],
                "correlation_id": derive_correlation_id(
                    data.get("correlation_id", ""), pr.get("node_id", ""), pr_number
                ),
            }

    if source_key in {"system_monitor", "monitor", "observability", "system"}:
        severity = (
            str(data.get("severity") or data.get("level") or data.get("status") or "")
            .strip()
            .lower()
        )
        alert_name = str(
            data.get("alert_name") or data.get("service") or data.get("title") or event_key
        ).strip()
        if severity in {"error", "critical", "fatal"} or event_key in {
            "system_error",
            "monitor_alert",
            "incident",
            "error_detected",
        }:
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
                "correlation_id": derive_correlation_id(
                    data.get("correlation_id", ""), data.get("alert_id", ""), alert_name
                ),
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
    correlation_id = str(
        spec.get("correlation_id") or derive_correlation_id(spec.get("task_id", ""), event_name)
    ).strip()
    task_context = {
        **{str(k): str(v) for k, v in dict(spec.get("context") or {}).items()},
        "event_name": str(event_name or ""),
        "event_source": str(source or ""),
        "correlation_id": correlation_id,
        "event_payload_excerpt": _trim_autonomy_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), 1200
        ),
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
        context={
            **task_context,
            "workflow_type": str(spec.get("workflow_type") or "external_event"),
        },
        inputs=[str(item) for item in list(spec.get("inputs") or [])],
        meta={"initiative": "event_driven_swarm", "event_name": str(event_name or "")},
        correlation_id=correlation_id,
    )
    coder_result = pipeline[0] if pipeline else None
    reviewer_result = pipeline[-1] if pipeline else None
    reviewer_summary = _trim_autonomy_text(
        getattr(reviewer_result, "summary", "") or getattr(coder_result, "summary", "") or "", 2400
    )
    fed_result = FederationTaskResult(
        task_id=envelope.task_id,
        source_system="sidar",
        source_agent="supervisor",
        target_system=envelope.source_system,
        target_agent=envelope.source_agent,
        status=(
            getattr(reviewer_result, "status", "")
            or getattr(coder_result, "status", "")
            or "failed"
        ),
        summary=reviewer_summary or "Event-driven swarm sonucu üretilemedi.",
        protocol=envelope.protocol,
        evidence=[
            _trim_autonomy_text(getattr(item, "summary", "") or "", 800)
            for item in pipeline
            if getattr(item, "summary", "")
        ],
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


def _embed_event_driven_federation_payload(
    base_payload: dict[str, Any], workflow: dict[str, Any]
) -> dict[str, Any]:
    return {
        "kind": "federation_task",
        "federation_task": dict(workflow.get("federation_task") or {}),
        "federation_prompt": str(workflow.get("federation_prompt") or ""),
        "event_payload": dict(base_payload or {}),
        "event_driven_federation": dict(workflow or {}),
        "task_id": str((workflow.get("federation_task") or {}).get("task_id", "") or ""),
        "source_system": str(
            (workflow.get("federation_task") or {}).get("source_system", "") or ""
        ),
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
                logger.info(
                    "Nightly memory maintenance sonucu: %s", report.get("status", "unknown")
                )
            except Exception as exc:
                logger.warning("Nightly memory maintenance hatası: %s", exc)


# ─────────────────────────────────────────────
#  FASTAPI UYGULAMASI
# ─────────────────────────────────────────────


@asynccontextmanager
async def _app_lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    global _rag_prewarm_task, _agent_lock, _redis_lock, _local_rate_lock
    global _autonomy_cron_task, _autonomy_cron_stop, _nightly_memory_task, _nightly_memory_stop
    # Kilitleri event loop ayaktayken kesin olarak başlat (lazy başlatma race-condition'ı önler)
    _agent_lock = asyncio.Lock()
    _redis_lock = asyncio.Lock()
    _local_rate_lock = asyncio.Lock()
    runtime_state = _runtime_state(_app)
    runtime_state.agent = _agent
    runtime_state.agent_lock = _agent_lock
    runtime_state.redis_lock = _redis_lock
    runtime_state.local_rate_lock = _local_rate_lock
    # Config doğrulamasını thread'de çalıştır — sync httpx Ollama çağrısı event loop'u bloklamaz (O-4)
    settings_valid = await asyncio.to_thread(Config.validate_critical_settings)
    skip_boot_checks = os.getenv("SIDAR_SKIP_BOOT_CHECKS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if not settings_valid and not skip_boot_checks:
        raise RuntimeError(
            "Kritik yapılandırma doğrulaması başarısız; web sunucusu başlatılamıyor. "
            "Detaylar için loglara bakın (SIDAR_SKIP_BOOT_CHECKS=1 ile bilinçli olarak atlanabilir)."
        )
    await asyncio.to_thread(_reload_persisted_marketplace_plugins)
    _rag_prewarm_task = asyncio.create_task(_prewarm_rag_embeddings())
    runtime_state.rag_prewarm_task = _rag_prewarm_task
    if bool(getattr(cfg, "ENABLE_AUTONOMOUS_CRON", False)):
        _autonomy_cron_stop = asyncio.Event()
        _autonomy_cron_task = asyncio.create_task(_autonomous_cron_loop(_autonomy_cron_stop))
        runtime_state.autonomy_cron_stop = _autonomy_cron_stop
        runtime_state.autonomy_cron_task = _autonomy_cron_task
    if bool(getattr(cfg, "ENABLE_NIGHTLY_MEMORY_PRUNING", False)):
        _nightly_memory_stop = asyncio.Event()
        _nightly_memory_task = asyncio.create_task(_nightly_memory_loop(_nightly_memory_stop))
        runtime_state.nightly_memory_stop = _nightly_memory_stop
        runtime_state.nightly_memory_task = _nightly_memory_task
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


def _build_user_from_jwt_payload(payload: dict[str, Any]) -> Any:
    return build_user_from_jwt_payload(payload)


def _get_jwt_secret() -> str:
    return get_jwt_secret(cfg, logger)


async def _resolve_user_from_token(_agent: SidarAgent | None, token: str) -> Any:
    return await resolve_user_from_token(_agent, token, config=cfg, logger_obj=logger)


async def _issue_auth_token(agent: SidarAgent, user: Any) -> str:
    return await issue_auth_token(agent, user, config=cfg, logger_obj=logger)


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


_register_exception_handlers = _app_factory.register_exception_handlers
app = _app_factory.create_app(
    lifespan=_app_lifespan,
    version=str(getattr(cfg, "VERSION", "") or ""),
)


def _runtime_state(application: FastAPI | None = None) -> Any:
    """Return app-scoped runtime state while keeping legacy globals as aliases."""

    return _app_factory.get_runtime_state(application or app)


async def basic_auth_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Bearer token ile stateless JWT kullanıcı doğrulaması uygular."""
    open_paths = {
        "/",
        "/health",
        "/healthz",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/auth/login",
        "/auth/register",
    }
    webhook_signature_paths = {"/api/webhook"}
    webhook_signature_prefixes = ("/api/autonomy/webhook/",)
    is_signature_verified_webhook = request.method == "POST" and (
        request.url.path in webhook_signature_paths
        or request.url.path.startswith(webhook_signature_prefixes)
    )
    if (
        request.method == "OPTIONS"
        or request.url.path in open_paths
        or is_signature_verified_webhook
        or request.url.path.startswith("/static/")
        or request.url.path.startswith("/vendor/")
        or request.url.path == "/favicon.ico"
    ):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Yetkisiz erişim"}, status_code=401)

    access_token = auth_header[7:].strip()
    if not access_token:
        return JSONResponse({"error": "Geçersiz token"}, status_code=401)

    user = await _resolve_user_from_token(None, access_token)
    if not user:
        return JSONResponse({"error": "Oturum geçersiz veya süresi dolmuş"}, status_code=401)

    agent = await _await_if_needed(_resolve_agent_instance())
    request.state.user = user
    set_active_user = getattr(agent.memory, "set_active_user", None)
    if callable(set_active_user):
        await set_active_user(user.id, user.username)
    metrics_token = set_current_metrics_user_id(user.id)
    try:
        return await call_next(request)
    finally:
        reset_current_metrics_user_id(metrics_token)


# ─────────────────────────────────────────────
#  OBSERVABILITY (OpenTelemetry)
# ─────────────────────────────────────────────
def _setup_tracing() -> None:
    if hasattr(cfg, "init_telemetry"):
        cfg.init_telemetry(
            service_name=getattr(cfg, "OTEL_SERVICE_NAME", "sidar-web"),
            fastapi_app=app,
            logger_obj=logger,
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


def _get_request_user(request: Request) -> Any:
    return get_request_user(request)


def _is_admin_user(user: Any) -> bool:
    return is_admin_user(user)


def _require_admin_user(user: Any = Depends(_get_request_user)) -> Any:
    return require_admin_user(user)


def _require_metrics_access(request: Request, user: Any = Depends(_get_request_user)) -> Any:
    return require_metrics_access(request, user, config=cfg)


def _get_user_tenant(user: Any) -> str:
    return str(getattr(user, "tenant_id", "default") or "default").strip() or "default"


def _serialize_policy(record: Any) -> dict[str, Any]:
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
    if path.startswith("/api/operations/"):
        return ("operations", "write" if request.method != "GET" else "read", "*")
    if path.startswith("/api/qa/coverage/"):
        return ("coverage", "write" if request.method != "GET" else "read", "*")
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
    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=128)
    tenant_id: str = Field(default="default", min_length=1, max_length=64)


class _LoginRequest(BaseModel):
    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=128)


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


def _serialize_audit_log(record: Any) -> dict[str, Any]:
    return {
        "id": int(getattr(record, "id", 0) or 0),
        "user_id": str(getattr(record, "user_id", "") or ""),
        "tenant_id": str(getattr(record, "tenant_id", "default") or "default"),
        "action": str(getattr(record, "action", "") or ""),
        "resource": str(getattr(record, "resource", "") or ""),
        "ip_address": str(getattr(record, "ip_address", "") or ""),
        "allowed": bool(getattr(record, "allowed", False)),
        "timestamp": str(getattr(record, "timestamp", "") or ""),
    }


def _serialize_prompt(record: Any) -> dict[str, Any]:
    prompt_id = getattr(record, "id", 0)
    serialized_id: int | str
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


def _serialize_swarm_result(record: Any) -> dict[str, Any]:
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


_serialize_campaign = operations_routes.serialize_campaign
_serialize_content_asset = operations_routes.serialize_content_asset
_serialize_operation_checklist = operations_routes.serialize_operation_checklist

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


# ─────────────────────────────────────────────
#  PLUGIN AGENT SANDBOX — bilinen kapsam sınırlaması
# ─────────────────────────────────────────────
# Bu sandbox bir AST kara listesi + kısıtlı `__builtins__` haritasıdır; işletim
# sistemi/process seviyesinde GERÇEK bir izolasyon SAĞLAMAZ. Statik izin/red
# listeleri tarihsel olarak bypass edilebilir (dolaylı öznitelik zincirleri,
# izin verilen modüller üzerinden erişilen üçüncü parti kod, bytecode/marshal
# manipülasyonu vb.). Buradaki gerçek güvenlik sınırı, bu yola erişimin
# `require_admin_user`'a (bkz. web/routes/agent.py) sıkı biçimde bağlı olması
# ve dolayısıyla sadece zaten güvenilen adminlerin plugin kodu
# kaydedebilmesidir — AST/builtins kısıtlaması burada savunma-derinliği
# katmanıdır, birincil güvenlik sınırı değildir.
#
# Gerçek izolasyon (plugin kodunu ayrı bir subprocess/container'da çalıştırıp
# orchestration'a IPC üzerinden bağlamak) kasıtlı olarak bu bulgunun kapsamı
# dışında bırakıldı: plugin sınıfları şu an AgentRegistry'ye doğrudan
# in-process yükleniyor ve `BaseAgent` arayüzü üzerinden diğer agent'larla aynı
# çağrı yüzeyini (memory, tool çağrıları, event bus) paylaşıyor. Süreç/container
# izolasyonuna geçmek bu çalışma modelini IPC tabanlı mesajlaşmaya taşımayı
# gerektiren ayrı, büyük bir mimari değişikliktir ve ayrı bir proje olarak takip
# edilmelidir.
_PLUGIN_BANNED_BUILTINS: frozenset[str] = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "open",
        "input",
        "breakpoint",
        "globals",
        "vars",
        "memoryview",
    }
)
_PLUGIN_SAFE_IMPORT_ROOTS: frozenset[str] = frozenset(
    {"abc", "asyncio", "collections", "dataclasses", "math", "pydantic", "typing"}
)
_PLUGIN_SAFE_WEB_SERVER_FROM_IMPORTS: frozenset[str] = frozenset({"BaseAgent"})
_PLUGIN_SAFE_FASTAPI_FROM_IMPORTS: frozenset[str] = frozenset({"HTTPException"})


def _restricted_plugin_import(
    name: str,
    globals: dict[str, Any] | None = None,
    locals: dict[str, Any] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    """Plugin kodu için allowlist tabanlı import kapısı."""

    del globals, locals
    if level != 0:
        raise ImportError("Plugin güvenlik politikası: relative import engellendi.")
    module_name = str(name or "").strip()
    root = module_name.split(".", 1)[0]
    requested = tuple(str(item) for item in (fromlist or ()))

    if module_name == "web_server":
        if requested and any(
            item not in _PLUGIN_SAFE_WEB_SERVER_FROM_IMPORTS for item in requested
        ):
            raise ImportError("Plugin güvenlik politikası: web_server import kapsamı engellendi.")
        return SimpleNamespace(BaseAgent=BaseAgent)

    if module_name == "fastapi":
        if requested and any(item not in _PLUGIN_SAFE_FASTAPI_FROM_IMPORTS for item in requested):
            raise ImportError("Plugin güvenlik politikası: fastapi import kapsamı engellendi.")
        return SimpleNamespace(HTTPException=HTTPException)

    if module_name == "agent.base_agent":
        if requested and any(item != "BaseAgent" for item in requested):
            raise ImportError(
                "Plugin güvenlik politikası: agent.base_agent import kapsamı engellendi."
            )
        return builtins.__import__(module_name, {}, {}, requested, 0)

    if root not in _PLUGIN_SAFE_IMPORT_ROOTS:
        raise ImportError("Plugin güvenlik politikası: import allowlist dışında.")
    return builtins.__import__(module_name, {}, {}, requested, 0)


def _build_restricted_plugin_builtins() -> dict[str, Any]:
    """Plugin exec'i için tehlikeli built-in'leri elenmiş bir __builtins__ haritası üretir.

    AST doğrulayıcı statik olarak `exec`, `eval`, `compile`, `__import__`, `open`, `input`
    çağrılarını engeller; bu fonksiyon ise runtime'da bu sembolleri tamamen erişilmez
    kılarak defense-in-depth sağlar. `from ... import ...` deyiminin çalışabilmesi için
    sadece güvenli modülleri döndüren allowlist tabanlı `__import__` kullanılır.
    """
    safe: dict[str, Any] = {}
    for name in dir(builtins):
        if name in _PLUGIN_BANNED_BUILTINS:
            continue
        safe[name] = getattr(builtins, name)
    safe["__import__"] = _restricted_plugin_import
    return safe


def _validate_plugin_source(source_code: str) -> None:
    """Plugin kaynağını çalıştırmadan önce temel güvenlik politikalarını uygular."""
    try:
        tree = ast.parse(source_code, mode="exec")
    except SyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"Plugin söz dizimi hatası: {exc}") from exc

    banned_calls = {
        "exec",
        "eval",
        "compile",
        "__import__",
        "open",
        "input",
        "getattr",
        "setattr",
        "delattr",
    }
    banned_import_roots = {"os", "subprocess", "socket", "ctypes", "multiprocessing"}
    banned_attribute_roots = banned_import_roots | {"builtins", "importlib", "pathlib", "shutil"}
    banned_introspection_attrs = {
        "__base__",
        "__bases__",
        "__class__",
        "__closure__",
        "__code__",
        "__dict__",
        "__getattribute__",
        "__globals__",
        "__mro__",
        "__subclasses__",
    }

    def _attribute_root_name(expr: ast.AST) -> str:
        """Return the left-most name in a chained attribute expression, if any."""
        current = expr
        while isinstance(current, ast.Attribute):
            current = current.value
        if isinstance(current, ast.Name):
            return current.id
        if isinstance(current, ast.Call):
            return _attribute_root_name(current.func)
        if isinstance(current, ast.Subscript):
            return _attribute_root_name(current.value)
        return ""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            else:
                modules = [(node.module or "").split(".")[0]]
            if any(mod in banned_import_roots for mod in modules if mod):
                raise HTTPException(
                    status_code=400,
                    detail="Plugin güvenlik politikası: tehlikeli modül import'u engellendi.",
                )
        if isinstance(node, ast.Attribute) and node.attr in banned_introspection_attrs:
            raise HTTPException(
                status_code=400,
                detail="Plugin güvenlik politikası: tehlikeli introspection erişimi engellendi.",
            )
        if isinstance(node, ast.Call):
            fn_name = ""
            if isinstance(node.func, ast.Name):
                fn_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                root_name = _attribute_root_name(node.func)
                fn_name = f"{root_name}.{node.func.attr}" if root_name else node.func.attr
            if fn_name in banned_calls or fn_name.endswith(".exec") or fn_name.endswith(".eval"):
                raise HTTPException(
                    status_code=400,
                    detail="Plugin güvenlik politikası: dinamik kod çalıştırma çağrısı engellendi.",
                )
            if (
                isinstance(node.func, ast.Attribute)
                and _attribute_root_name(node.func) in banned_attribute_roots
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Plugin güvenlik politikası: tehlikeli modül çağrısı engellendi.",
                )


def _execute_validated_plugin_source(
    source_code: str, module_label: str, namespace: dict[str, Any]
) -> None:
    """Derlenmiş plugin kaynağını daraltılmış namespace içinde çalıştırır."""

    code = compile(source_code, _plugin_source_filename(module_label), "exec")
    exec(code, namespace)  # nosec B102


def _run_plugin_source_in_sandbox(source_code: str, module_label: str) -> dict[str, Any]:
    """Validate plugin source and execute it with restricted builtins only.

    Not a process/container-level sandbox — see the "PLUGIN AGENT SANDBOX"
    note above `_PLUGIN_BANNED_BUILTINS` for the residual risk this accepts
    and why the admin-only gate on the callers of this function is the real
    security boundary.
    """

    try:
        _validate_plugin_source(source_code)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Plugin kaynağı doğrulanamadı: {exc}") from exc

    # Defense-in-depth: AST doğrulamasının yanında runtime namespace'ini de daraltıyoruz.
    # Tehlikeli built-in'ler (`exec`, `eval`, `compile`, `open`, `input`, `breakpoint`, ...)
    # plugin koduna sızdırılmadığı için statik kontrol bypass edilse bile çağrı yapılamaz.
    namespace: dict[str, Any] = {
        "__name__": module_label,
        "__builtins__": _build_restricted_plugin_builtins(),
    }
    try:
        _execute_validated_plugin_source(source_code, module_label, namespace)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Plugin kodu derlenemedi/çalıştırılamadı: {exc}"
        ) from exc
    return namespace


def _load_plugin_agent_class(
    source_code: str, class_name: str | None, module_label: str
) -> type[BaseAgent]:
    def _baseagent_candidates() -> list[Any]:
        # Resolve the canonical class on every call so stale monkeypatches or reloads of
        # the web_server module cannot override an available agent.base_agent module.
        base_agent_module = sys.modules.get("agent.base_agent")
        canonical_base = (
            getattr(base_agent_module, "BaseAgent", None) if base_agent_module is not None else None
        )
        candidates: list[Any] = []
        seen: set[int] = set()
        for base in (canonical_base, BaseAgent):
            if (
                base is not None
                and base is not object
                and inspect.isclass(base)
                and id(base) not in seen
            ):
                seen.add(id(base))
                candidates.append(base)
        return candidates

    def _is_baseagent_derived(candidate: Any) -> bool:
        if not inspect.isclass(candidate):
            return False
        for base_cls in _baseagent_candidates():
            try:
                if issubclass(candidate, base_cls):
                    return candidate is not base_cls
            except TypeError as exc:
                raise HTTPException(
                    status_code=400, detail="Plugin BaseAgent doğrulanamadı"
                ) from exc
        # Bazı ortamlarda BaseAgent birden fazla modül kimliğiyle yüklenebilir.
        # Bu durumda isim bazlı MRO kontrolü ile eşdeğer türevleri yakalayalım.
        for base in inspect.getmro(candidate)[1:]:
            if base is object:
                continue
            base_name = getattr(base, "__name__", "")
            base_qualname = getattr(base, "__qualname__", "")
            base_module = getattr(base, "__module__", "")
            if base_name == "BaseAgent" or base_qualname.endswith("BaseAgent"):
                return True
            if base_module == "agent.base_agent":
                return True
        return False

    namespace = _run_plugin_source_in_sandbox(source_code, module_label)

    if class_name:
        candidate = namespace.get(class_name)
        if not inspect.isclass(candidate):
            raise HTTPException(
                status_code=400, detail=f"Belirtilen sınıf bulunamadı: {class_name}"
            )
        if not _is_baseagent_derived(candidate):
            raise HTTPException(status_code=400, detail="Plugin sınıfı BaseAgent türetmelidir")
        return candidate

    discovered: list[type[BaseAgent]] = []
    for obj in namespace.values():
        if _is_baseagent_derived(obj):
            discovered.append(cast(type[BaseAgent], obj))

    if not discovered:
        raise HTTPException(
            status_code=400, detail="Plugin içinde BaseAgent türevi bir sınıf bulunamadı"
        )
    return discovered[0]


def _validate_and_persist_plugin_file(filename: str, source_code: str, module_label: str) -> Path:
    """Validate uploaded plugin source in the shared sandbox before persisting it."""

    _run_plugin_source_in_sandbox(source_code, module_label)

    safe_name = Path(filename or "plugin.py").name
    if not safe_name.endswith(".py"):
        safe_name = f"{safe_name}.py"

    plugins_dir = Path("plugins")
    plugins_dir.mkdir(parents=True, exist_ok=True)
    plugin_path = plugins_dir / safe_name
    plugin_path.write_text(source_code, encoding="utf-8")
    return plugin_path


def _persist_and_import_plugin_file(filename: str, data: bytes, module_label: str) -> Path:
    """Backward-compatible secure wrapper for router-level uploaded plugin persistence."""

    try:
        source_code = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Plugin dosyası UTF-8 olmalıdır") from exc
    return _validate_and_persist_plugin_file(filename, source_code, module_label)


# Plugin marketplace catalog/state-persistence/(un)install orchestration lives in
# web/routes/plugin_marketplace.py. These wrappers stay so every existing
# monkeypatch target (web_server.PLUGIN_MARKETPLACE_CATALOG, web_server.
# _read_plugin_marketplace_state, etc.) keeps working: each wrapper resolves its
# sibling collaborators as bare globals at call time and threads them through as
# explicit arguments, so patching one wrapper is observed by every other wrapper
# that calls it, exactly as before the extraction.
PLUGIN_SOURCE_DIR = plugin_marketplace_routes.PLUGIN_SOURCE_DIR
PLUGIN_MARKETPLACE_CATALOG = plugin_marketplace_routes.PLUGIN_MARKETPLACE_CATALOG


def _plugin_marketplace_state_path() -> Path:
    return plugin_marketplace_routes.plugin_marketplace_state_path()


def _read_plugin_marketplace_state() -> dict[str, Any]:
    return plugin_marketplace_routes.read_plugin_marketplace_state(logger_obj=logger)


def _write_plugin_marketplace_state(state: dict[str, Any]) -> None:
    plugin_marketplace_routes.write_plugin_marketplace_state(state)


def _get_plugin_marketplace_entry(plugin_id: str) -> dict[str, Any]:
    return plugin_marketplace_routes.get_plugin_marketplace_entry(
        plugin_id, catalog=PLUGIN_MARKETPLACE_CATALOG
    )


def _serialize_marketplace_plugin(
    plugin_id: str, *, installed_state: dict[str, Any] | None = None
) -> dict[str, Any]:
    return plugin_marketplace_routes.serialize_marketplace_plugin(
        plugin_id,
        catalog=PLUGIN_MARKETPLACE_CATALOG,
        agent_registry=AgentRegistry,
        read_state=lambda: _read_plugin_marketplace_state(),
        installed_state=installed_state,
    )


def _install_marketplace_plugin(plugin_id: str, *, persist: bool = True) -> dict[str, Any]:
    return plugin_marketplace_routes.install_marketplace_plugin(
        plugin_id,
        catalog=PLUGIN_MARKETPLACE_CATALOG,
        agent_registry=AgentRegistry,
        register_plugin_agent=lambda **kwargs: _register_plugin_agent(**kwargs),
        read_state=lambda: _read_plugin_marketplace_state(),
        write_state=lambda state: _write_plugin_marketplace_state(state),
        serialize=lambda plugin_id: _serialize_marketplace_plugin(plugin_id),
        persist=persist,
    )


def _uninstall_marketplace_plugin(plugin_id: str) -> dict[str, Any]:
    return plugin_marketplace_routes.uninstall_marketplace_plugin(
        plugin_id,
        catalog=PLUGIN_MARKETPLACE_CATALOG,
        agent_registry=AgentRegistry,
        read_state=lambda: _read_plugin_marketplace_state(),
        write_state=lambda state: _write_plugin_marketplace_state(state),
        serialize=lambda plugin_id: _serialize_marketplace_plugin(plugin_id),
    )


def _reload_persisted_marketplace_plugins() -> list[dict[str, Any]]:
    return plugin_marketplace_routes.reload_persisted_marketplace_plugins(
        catalog=PLUGIN_MARKETPLACE_CATALOG,
        read_state=lambda: _read_plugin_marketplace_state(),
        install=lambda plugin_id: _install_marketplace_plugin(plugin_id),
        logger_obj=logger,
    )


def _register_plugin_agent(
    *,
    role_name: str,
    source_code: str,
    class_name: str | None,
    capabilities: list[str] | None,
    description: str,
    version: str,
) -> dict[str, Any]:
    normalized_role = _validate_plugin_role_name(role_name)
    module_label = f"sidar_plugin_{normalized_role}_{secrets.token_hex(4)}"
    plugin_cls = _load_plugin_agent_class(source_code, class_name, module_label)
    plugin_description = (description or "").strip() or (plugin_cls.__doc__ or "").strip().split(
        "\n"
    )[0]

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


# ─────────────────────────────────────────────
#  HITL — Human-in-the-Loop Onay Geçidi
# ─────────────────────────────────────────────


@app.middleware("http")
async def access_policy_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
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
        return JSONResponse(
            status_code=403,
            content={"error": "Yetki yok", "resource": resource_type, "action": action},
        )
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
    "/git-info",
    "/git-branches",
    "/files",
    "/file-content",
    "/github-prs",
    "/github-repos",
    "/todo",
    "/rag/",
    "/sessions",
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
                        max_connections=max(
                            1, int(getattr(cfg, "REDIS_MAX_CONNECTIONS", 50) or 50)
                        ),
                    )
                    await client.ping()
                    _redis_client = client
                except Exception as exc:
                    logger.warning(
                        "Redis bağlantısı kurulamadı (%s). Local rate limit fallback kullanılacak.",
                        exc,
                    )
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
    """Geriye dönük uyumluluk için Redis destekli hız sınırlama sarmalayıcısı."""
    return await _redis_is_rate_limited("default", key, limit, window_sec)


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
        return bool(count > limit)
    except Exception as exc:
        logger.warning("Redis rate limit komutu başarısız (%s). Local fallback kullanılacak.", exc)
        return await _local_is_rate_limited(redis_key, limit, window_sec)


def _parse_forwarded_ip(value: str) -> str | None:
    """Return a normalized IP from a proxy header or None when invalid."""
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if any(ch in candidate for ch in "\r\n\t "):
        return None
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _trusted_proxy_matches(direct_ip: str) -> bool:
    """Return whether the direct peer is allowed to supply forwarding headers."""
    trusted_proxies: frozenset[str] = getattr(Config, "TRUSTED_PROXIES", frozenset())
    if "*" in trusted_proxies:
        return True
    if direct_ip in trusted_proxies:
        return True
    try:
        peer_ip = ipaddress.ip_address(direct_ip)
    except ValueError:
        return False
    for proxy in trusted_proxies:
        try:
            if peer_ip in ipaddress.ip_network(str(proxy), strict=False):
                return True
        except ValueError:
            continue
    return False


def _get_client_ip(request: Request) -> str:
    """İstemci IP'sini doğrulanmış proxy başlıklarından ya da direkt bağlantıdan döndürür.

    Proxy başlıkları (X-Forwarded-For, X-Real-IP) yalnızca direkt bağlantının
    Config.TRUSTED_PROXIES listesindeki bir adresten gelmesi durumunda okunur.
    Header değeri IP parser ile doğrulanır; boş, çok satırlı, port ekli veya
    IP olmayan değerler header injection/rate-limit bypass riskine karşı yok sayılır.
    """
    direct_ip = request.client.host if request.client else "unknown"
    if _trusted_proxy_matches(direct_ip):
        xff = request.headers.get("X-Forwarded-For", "")
        first_forwarded = xff.split(",", 1)[0] if xff else ""
        parsed_xff = _parse_forwarded_ip(first_forwarded)
        if parsed_xff:
            return parsed_xff
        parsed_real_ip = _parse_forwarded_ip(request.headers.get("X-Real-IP", ""))
        if parsed_real_ip:
            return parsed_real_ip
    return direct_ip


def _get_rate_limit_key(request: Request, fallback_ip: str) -> str:
    """Return a user-scoped rate-limit key after JWT auth, falling back to IP."""
    user = getattr(request.state, "user", None)
    user_id = str(getattr(user, "id", "") or "").strip()
    if user_id:
        tenant_id = _get_user_tenant(user)
        return f"user:{tenant_id}:{user_id}"
    return f"ip:{fallback_ip}"


async def ddos_rate_limit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    return await ddos_rate_limit_middleware_impl(
        request,
        call_next,
        get_client_ip=_get_client_ip,
        redis_is_rate_limited=_redis_is_rate_limited,
        max_requests=RATE_LIMIT_MAX_REQUESTS,
        window_sec=RATE_LIMIT_WINDOW_SEC,
        bypass_paths=("/health", "/healthz", "/readyz"),
        bypass_prefixes=("/ui/", "/static/"),
    )


async def rate_limit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    return await rate_limit_middleware_impl(
        request,
        call_next,
        get_client_ip=_get_client_ip,
        redis_is_rate_limited=_redis_is_rate_limited,
        chat_limit=_RATE_LIMIT,
        mutation_limit=_RATE_LIMIT_MUTATIONS,
        get_io_limit=_RATE_LIMIT_GET_IO,
        window_sec=_RATE_WINDOW,
        get_io_paths=_RATE_GET_IO_PATHS,
        get_rate_limit_key=_get_rate_limit_key,
    )


# Starlette inserts function middleware at the front of ``app.user_middleware``.
# Keep DDoS throttling outermost, then authenticate, then apply user-scoped
# rate limits and fine-grained ACL checks with ``request.state.user`` populated.
app.middleware("http")(rate_limit_middleware)
app.middleware("http")(basic_auth_middleware)
app.middleware("http")(ddos_rate_limit_middleware)


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
            logger.debug(
                "Redis istemcisi event loop kapandıktan sonra kapatılmaya çalışıldı: %s", exc
            )
        _redis_client = None


# CORS: localhost/loopback kökenlerine porttan bağımsız izin ver.
configure_loopback_cors(app)

# React SPA yalnızca web_ui_react/dist üzerinden sunulur.
REACT_DIST_DIR = web_dist_path()
WEB_DIR = REACT_DIST_DIR


def _make_static_files(directory: Path) -> Any:
    """Legacy wrapper for frontend bootstrap tests/imports."""
    return _make_static_files_with_staticfiles(directory, StaticFiles)


def _mount_frontend_static_routes(target_app: FastAPI, web_dir: Path) -> None:
    """Legacy wrapper for frontend static route mounting."""
    web_bootstrap.mount_frontend_static_routes(target_app, web_dir)


# React build çıktısı /static altında servis edilir.
_mount_frontend_static_routes(app, WEB_DIR)


# ─────────────────────────────────────────────
#  ROTALAR
# ─────────────────────────────────────────────


async def _ws_close_policy_violation(websocket: WebSocket, reason: str) -> None:
    if hasattr(websocket, "close"):
        await websocket.close(code=1008, reason=reason)


def _build_ws_chat_dependencies() -> SimpleNamespace:
    return SimpleNamespace(
        anyio_closed=_ANYIO_CLOSED,
        append_room_message=_append_room_message,
        append_room_telemetry=_append_room_telemetry,
        await_if_needed=_await_if_needed,
        broadcast_room_payload=_broadcast_room_payload,
        build_collaboration_prompt=_build_collaboration_prompt,
        build_room_message=_build_room_message,
        cfg=cfg,
        collaboration_command_requires_write=_collaboration_command_requires_write,
        collaboration_now_iso=_collaboration_now_iso,
        collaboration_rooms=_collaboration_rooms,
        get_agent_event_bus=get_agent_event_bus,
        is_sidar_mention=_is_sidar_mention,
        iter_stream_chunks=_iter_stream_chunks,
        join_collaboration_room=_join_collaboration_room,
        leave_collaboration_room=_leave_collaboration_room,
        llm_api_error_cls=LLMAPIError,
        logger=logger,
        extract_ws_header_token=web_security.extract_ws_header_token,
        mask_collaboration_text=_mask_collaboration_text,
        normalize_collaboration_role=_normalize_collaboration_role,
        rate_limit=_RATE_LIMIT,
        rate_window=_RATE_WINDOW,
        redis_is_rate_limited=_redis_is_rate_limited,
        reset_current_metrics_user_id=reset_current_metrics_user_id,
        resolve_agent_instance=_resolve_agent_instance,
        resolve_user_from_token=_resolve_user_from_token,
        set_current_metrics_user_id=set_current_metrics_user_id,
        socket_key=_socket_key,
        strip_sidar_mention=_strip_sidar_mention,
        ws_close_policy_violation=_ws_close_policy_violation,
    )


async def _ws_stream_agent_text_response(
    websocket: WebSocket, agent: SidarAgent, prompt: str
) -> None:
    await ws_chat_routes.ws_stream_agent_text_response(websocket, agent, prompt)


async def websocket_chat(websocket: WebSocket) -> Any:
    return await ws_chat_routes.websocket_chat(websocket, _build_ws_chat_dependencies())


def _build_ws_voice_dependencies() -> SimpleNamespace:
    return SimpleNamespace(
        anyio_closed=_ANYIO_CLOSED,
        await_if_needed=_await_if_needed,
        cfg=cfg,
        llm_api_error_cls=LLMAPIError,
        logger=logger,
        extract_ws_header_token=web_security.extract_ws_header_token,
        resolve_agent_instance=_resolve_agent_instance,
        resolve_user_from_token=_resolve_user_from_token,
        ws_close_policy_violation=_ws_close_policy_violation,
        ws_stream_agent_text_response=_ws_stream_agent_text_response,
        ws_voice_protocol=web_security.SIDAR_WS_VOICE_PROTOCOL,
    )


async def websocket_voice(websocket: WebSocket) -> Any:
    return await ws_voice_routes.websocket_voice(websocket, _build_ws_voice_dependencies())


def _expose_operational_error_details() -> bool:
    return health_runtime_routes.expose_operational_error_details(_app_factory)


def _health_error_payload(error: str, exc: Exception) -> dict[str, Any]:
    return health_runtime_routes.health_error_payload(
        error,
        exc,
        expose_details=_expose_operational_error_details(),
    )


async def _health_response(require_dependencies: bool = False) -> JSONResponse:
    return await health_runtime_routes.build_health_response(
        require_dependencies=require_dependencies,
        resolve_agent_instance=_resolve_agent_instance,
        expose_details=_expose_operational_error_details,
        logger=logger,
        start_time=_start_time,
    )


async def _status_response() -> JSONResponse:
    return await health_runtime_routes.build_status_response(
        resolve_agent_instance=_resolve_agent_instance,
        metrics_snapshot=lambda: get_llm_metrics_collector().snapshot(),
        start_time=_start_time,
    )


frontend_router = build_frontend_router(
    web_dir=lambda: WEB_DIR,
    grafana_url=lambda: str(
        getattr(cfg, "GRAFANA_URL", "http://localhost:3000") or "http://localhost:3000"
    ),
)

health_router = build_health_router(
    lambda require_dependencies: _health_response(require_dependencies=require_dependencies),
    _status_response,
)
agent_router = build_agent_router(
    require_admin_user=_require_admin_user,
    register_plugin_agent=lambda **kwargs: _register_plugin_agent(**kwargs),
    persist_and_import_plugin_file=lambda filename, data, module_label: (
        _persist_and_import_plugin_file(filename, data, module_label)
    ),
    max_file_content_bytes=lambda: MAX_FILE_CONTENT_BYTES,
    read_plugin_marketplace_state=lambda: _read_plugin_marketplace_state(),
    serialize_marketplace_plugin=(
        lambda plugin_id, *, installed_state=None: _serialize_marketplace_plugin(
            plugin_id, installed_state=installed_state
        )
    ),
    plugin_marketplace_catalog=lambda: PLUGIN_MARKETPLACE_CATALOG,
    install_marketplace_plugin=lambda plugin_id: _install_marketplace_plugin(plugin_id),
    uninstall_marketplace_plugin=lambda plugin_id: _uninstall_marketplace_plugin(plugin_id),
    agent_plugin_register_request_model=_AgentPluginRegisterRequest,
    plugin_marketplace_install_request_model=_PluginMarketplaceInstallRequest,
)

rag_router = build_rag_router(
    resolve_agent_instance=lambda: _resolve_agent_instance(),
    await_if_needed=_await_if_needed,
    max_rag_upload_bytes=lambda: Config.MAX_RAG_UPLOAD_BYTES,
    server_root=lambda: Path(__file__).parent.resolve(),
    logger=logger,
)

auth_admin_router = build_auth_admin_router(
    resolve_agent_instance=lambda: _resolve_agent_instance(),
    await_if_needed=_await_if_needed,
    get_request_user=_get_request_user,
    require_admin_user=_require_admin_user,
    issue_auth_token=lambda agent, user: _issue_auth_token(agent, user),
    serialize_prompt=_serialize_prompt,
    serialize_policy=_serialize_policy,
    serialize_audit_log=_serialize_audit_log,
    get_admin_stats=lambda agent: agent.memory.db.get_admin_stats(),
    register_request_model=_RegisterRequest,
    login_request_model=_LoginRequest,
    prompt_upsert_request_model=_PromptUpsertRequest,
    prompt_activate_request_model=_PromptActivateRequest,
    policy_upsert_request_model=_PolicyUpsertRequest,
)

hitl_router = build_hitl_router(
    get_request_user=_get_request_user,
    resolve_agent_instance=lambda: _resolve_agent_instance(),
    await_if_needed=_await_if_needed,
    resolve_user_from_token=lambda agent, token: _resolve_user_from_token(agent, token),
    ws_close_policy_violation=lambda ws, reason: _ws_close_policy_violation(ws, reason),
    hitl_ws_clients=_hitl_ws_clients,
    get_hitl_store=lambda: get_hitl_store(),
    get_hitl_gate=lambda: get_hitl_gate(),
    extract_ws_header_token=web_security.extract_ws_header_token,
    ws_hitl_protocol=web_security.SIDAR_WS_HITL_PROTOCOL,
)

ws_chat_router = ws_chat_routes.build_ws_chat_router(_build_ws_chat_dependencies)

ws_voice_router = ws_voice_routes.build_ws_voice_router(_build_ws_voice_dependencies)

metrics_router = build_metrics_router(
    require_metrics_access=_require_metrics_access,
    resolve_agent_instance=lambda: _resolve_agent_instance(),
    start_time=_start_time,
    local_rate_limits=lambda: _local_rate_limits,
    get_llm_metrics_collector=lambda: get_llm_metrics_collector(),
    render_llm_metrics_prometheus=render_llm_metrics_prometheus,
    set_current_metrics_user_id=set_current_metrics_user_id,
    reset_current_metrics_user_id=reset_current_metrics_user_id,
    logger=logger,
)

project_ops_router = build_project_ops_router(
    get_request_user=_get_request_user,
    resolve_agent_instance=lambda: _resolve_agent_instance(),
    max_file_content_bytes=lambda: MAX_FILE_CONTENT_BYTES,
    server_root=lambda: Path(__file__).parent.resolve(),
    cfg=cfg,
    logger=logger,
)

orchestration_router = build_orchestration_router(
    get_request_user=_get_request_user,
    require_admin_user=_require_admin_user,
    resolve_agent_instance=lambda: _resolve_agent_instance(),
    await_if_needed=_await_if_needed,
    swarm_orchestrator_cls=SwarmOrchestrator,
    swarm_task_cls=SwarmTask,
    cfg=cfg,
    swarm_execute_request_model=_SwarmExecuteRequest,
    serialize_swarm_result=_serialize_swarm_result,
)


def _build_webhook_dependencies() -> SimpleNamespace:
    return SimpleNamespace(
        await_if_needed=_await_if_needed,
        cfg=cfg,
        cfg_getter=lambda: cfg,
        dispatch_autonomy_trigger=lambda **kwargs: _dispatch_autonomy_trigger(**kwargs),
        embed_event_driven_federation_payload=(
            lambda payload, workflow: _embed_event_driven_federation_payload(payload, workflow)
        ),
        logger=logger,
        resolve_agent_instance=lambda: _resolve_agent_instance(),
        resolve_ci_failure_context=lambda event_name, payload: _resolve_ci_failure_context(
            event_name, payload
        ),
        run_event_driven_federation_workflow=(
            lambda **kwargs: _run_event_driven_federation_workflow(**kwargs)
        ),
        verify_hmac_signature=lambda *args, **kwargs: _verify_hmac_signature(*args, **kwargs),
    )


_webhook_deps = _build_webhook_dependencies()
webhooks_router = build_webhooks_router(
    cfg=_webhook_deps.cfg,
    cfg_getter=_webhook_deps.cfg_getter,
    logger=_webhook_deps.logger,
    resolve_agent_instance=_webhook_deps.resolve_agent_instance,
    await_if_needed=_webhook_deps.await_if_needed,
    verify_hmac_signature=_webhook_deps.verify_hmac_signature,
    resolve_ci_failure_context=_webhook_deps.resolve_ci_failure_context,
    run_event_driven_federation_workflow=_webhook_deps.run_event_driven_federation_workflow,
    embed_event_driven_federation_payload=_webhook_deps.embed_event_driven_federation_payload,
    dispatch_autonomy_trigger=_webhook_deps.dispatch_autonomy_trigger,
)

_legacy_route_exports = _app_factory.register_routers(
    app,
    [
        frontend_router,
        health_router,
        agent_router,
        rag_router,
        auth_admin_router,
        hitl_router,
        ws_chat_router,
        ws_voice_router,
        metrics_router,
        project_ops_router,
        orchestration_router,
        webhooks_router,
    ],
)
globals().update(_legacy_route_exports)

# Explicit legacy re-exports for static analyzers (ruff/mypy).
favicon = frontend_router.legacy_exports["favicon"]
serve_vendor = frontend_router.legacy_exports["serve_vendor"]
index = frontend_router.legacy_exports["index"]
status = health_router.legacy_exports["status"]
register_user = auth_admin_router.legacy_exports["register_user"]
login_user = auth_admin_router.legacy_exports["login_user"]
auth_me = auth_admin_router.legacy_exports["auth_me"]
admin_stats = auth_admin_router.legacy_exports["admin_stats"]
admin_list_prompts = auth_admin_router.legacy_exports["admin_list_prompts"]
admin_upsert_prompt = auth_admin_router.legacy_exports["admin_upsert_prompt"]
admin_activate_prompt = auth_admin_router.legacy_exports["admin_activate_prompt"]
github_webhook = webhooks_router.legacy_exports["github_webhook"]


# Legacy endpoint declarations kept in web_server.py for backwards-compatible
# static route discovery tests that scan this file for @app.<method>(...) usage.
@app.post("/auth/register")
async def _legacy_route_auth_register(payload: dict[str, Any]) -> Any:
    return await register_user(payload)


@app.post("/auth/login")
async def _legacy_route_auth_login(payload: dict[str, Any]) -> Any:
    return await login_user(payload)


@app.get("/auth/me")
async def _legacy_route_auth_me(request: Request, user: Any = Depends(_get_request_user)) -> Any:
    return await auth_me(request, user)


@app.get("/admin/stats")
async def _legacy_route_admin_stats(_user: Any = Depends(_require_admin_user)) -> Any:
    return await admin_stats(_user)


@app.get("/admin/prompts")
async def _legacy_route_admin_prompts(
    role_name: str = "", _user: Any = Depends(_require_admin_user)
) -> Any:
    return await admin_list_prompts(role_name, _user)


@app.post("/admin/prompts")
async def _legacy_route_admin_upsert_prompt(
    payload: Annotated[dict[str, Any], Body()],
    _user: Any = Depends(_require_admin_user),
) -> Any:
    return await admin_upsert_prompt(payload, _user)


@app.post("/admin/prompts/activate")
async def _legacy_route_admin_activate_prompt(
    payload: Annotated[dict[str, Any], Body()],
    _user: Any = Depends(_require_admin_user),
) -> Any:
    return await admin_activate_prompt(payload, _user)


@app.post("/api/agents/register")
@app.post("/api/agents/register-file")
@app.get("/api/plugin-marketplace/catalog")
@app.post("/api/plugin-marketplace/install")
@app.delete("/api/plugin-marketplace/install/{plugin_id}")
@app.post("/api/swarm/execute")
@app.get("/api/hitl/pending")
@app.post("/api/hitl/request")
@app.post("/api/hitl/respond/{request_id}")
@app.get("/healthz")
@app.get("/readyz")
@app.get("/metrics")
@app.get("/metrics/llm/prometheus")
@app.get("/metrics/llm")
@app.get("/api/budget")
@app.get("/sessions/{session_id}")
@app.post("/sessions/new")
@app.delete("/sessions/{session_id}")
@app.get("/files")
@app.get("/file-content")
@app.get("/git-info")
@app.get("/git-branches")
@app.post("/set-branch")
@app.get("/github-repos")
@app.post("/set-repo")
@app.get("/rag/docs")
@app.post("/rag/add-url")
@app.delete("/rag/docs/{doc_id}")
@app.post("/api/rag/upload")
async def _legacy_route_declaration_marker(*_args: Any, **_kwargs: Any) -> Any:
    raise HTTPException(status_code=410, detail="Legacy marker route should not be called.")


async def register_agent_plugin_file(
    file: UploadFile = File(...),
    role_name: str = "",
    class_name: str = "",
    capabilities: str = "",
    description: str = "",
    version: str = "1.0.0",
    _user: Any = Depends(_require_admin_user),
) -> Any:
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
    _validate_and_persist_plugin_file(file.filename or target_role_name, source_code, module_label)
    result = _register_plugin_agent(
        role_name=target_role_name,
        source_code=source_code,
        class_name=class_name.strip() or None,
        capabilities=parsed_capabilities,
        description=description,
        version=version,
    )
    return JSONResponse({"success": True, "agent": result})


async def llm_prometheus_metrics(
    _user: dict[str, Any] = Depends(_require_metrics_access),
) -> Response:
    snapshot = get_llm_metrics_collector().snapshot()
    llm_part = render_llm_metrics_prometheus(snapshot)
    delegation_part = ""
    try:
        from core.agent_metrics import get_agent_metrics_collector

        delegation_part = get_agent_metrics_collector().render_prometheus()
    except Exception as exc:
        logger.debug("Delegation metrikleri render edilemedi: %s", exc)
    return Response(content=llm_part + delegation_part, media_type="text/plain; version=0.0.4")


# ─────────────────────────────────────────────
#  ÇOKLU SOHBET (SESSIONS) ROTALARI
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────
#  Bulgu O-7: Faz 4/5 Modül API Endpoint'leri
#  VisionPipeline · EntityMemory · FeedbackStore
#  Slack · Jira · Teams
# ─────────────────────────────────────────────

# ── Vision ──────────────────────────────────


# Vision, entity-memory, feedback, and external integration routes live in
# focused route modules to keep this compatibility entrypoint thin.
_VisionAnalyzeRequest = vision_routes.VisionAnalyzeRequest
_VisionMockupRequest = vision_routes.VisionMockupRequest
_EntityUpsertRequest = memory_feedback_routes.EntityUpsertRequest
_FeedbackRecordRequest = memory_feedback_routes.FeedbackRecordRequest
_SlackSendRequest = integrations_routes.SlackSendRequest
_JiraCreateRequest = integrations_routes.JiraCreateRequest
_TeamsSendRequest = integrations_routes.TeamsSendRequest

_entity_memory_cache: dict[str, Any] = {}
_feedback_store_cache: dict[str, Any] = {}
_slack_mgr_cache: dict[str, Any] = {}
_jira_mgr_cache: dict[str, Any] = {}
_teams_mgr_cache: dict[str, Any] = {}

vision_router = vision_routes.build_vision_router(
    cfg=cfg,
    resolve_agent_instance=_resolve_agent_instance,
    resolve_vision_components=lambda: (
        importlib.import_module("core.vision").VisionPipeline,
        getattr(
            importlib.import_module("core.vision"),
            "build_analyze_prompt",
            lambda analysis_type="general": f"Görseli '{analysis_type}' odaklı analiz et.",
        ),
    ),
)
memory_feedback_router = memory_feedback_routes.build_memory_feedback_router(
    cfg=cfg,
    entity_memory_cache=_entity_memory_cache,
    feedback_store_cache=_feedback_store_cache,
    get_request_user=_get_request_user,
)
integrations_router = integrations_routes.build_integrations_router(
    cfg_provider=lambda: cfg,
    slack_cache=_slack_mgr_cache,
    jira_cache=_jira_mgr_cache,
    teams_cache=_teams_mgr_cache,
    require_admin_user=_require_admin_user,
)
_app_factory.register_routers(app, [vision_router, memory_feedback_router, integrations_router])

api_vision_analyze = vision_router.legacy_exports["api_vision_analyze"]
api_vision_mockup = vision_router.legacy_exports["api_vision_mockup"]

_entity_memory_instance = None
_feedback_store_instance = None
_slack_mgr_instance = None
_jira_mgr_instance = None
_teams_mgr_instance = None


async def _get_entity_memory() -> Any:
    global _entity_memory_instance
    if _entity_memory_instance is None:
        _entity_memory_cache.pop("instance", None)
    else:
        _entity_memory_cache["instance"] = _entity_memory_instance
    result = await memory_feedback_router.legacy_exports["_get_entity_memory"]()
    _entity_memory_instance = result
    return result


async def _get_feedback_store() -> Any:
    global _feedback_store_instance
    if _feedback_store_instance is None:
        _feedback_store_cache.pop("instance", None)
    else:
        _feedback_store_cache["instance"] = _feedback_store_instance
    result = await memory_feedback_router.legacy_exports["_get_feedback_store"]()
    _feedback_store_instance = result
    return result


async def _get_slack_manager() -> Any:
    global _slack_mgr_instance
    if _slack_mgr_instance is None:
        _slack_mgr_cache.pop("instance", None)
    else:
        _slack_mgr_cache["instance"] = _slack_mgr_instance
    result = await integrations_router.legacy_exports["_get_slack_manager"]()
    _slack_mgr_instance = result
    return result


def _get_jira_manager() -> Any:
    global _jira_mgr_instance
    if _jira_mgr_instance is None:
        _jira_mgr_cache.pop("instance", None)
    else:
        _jira_mgr_cache["instance"] = _jira_mgr_instance
    result = integrations_router.legacy_exports["_get_jira_manager"]()
    _jira_mgr_instance = result
    return result


def _get_teams_manager() -> Any:
    global _teams_mgr_instance
    if _teams_mgr_instance is None:
        _teams_mgr_cache.pop("instance", None)
    else:
        _teams_mgr_cache["instance"] = _teams_mgr_instance
    result = integrations_router.legacy_exports["_get_teams_manager"]()
    _teams_mgr_instance = result
    return result


async def api_entity_upsert(
    req: _EntityUpsertRequest, user: Any = Depends(_get_request_user)
) -> Any:
    if _entity_memory_instance is not None:
        _entity_memory_cache["instance"] = _entity_memory_instance
    return await memory_feedback_router.legacy_exports["api_entity_upsert"](req, user)


async def api_entity_get_profile(user_id: str, user: Any = Depends(_get_request_user)) -> Any:
    if _entity_memory_instance is not None:
        _entity_memory_cache["instance"] = _entity_memory_instance
    return await memory_feedback_router.legacy_exports["api_entity_get_profile"](user_id, user)


async def api_entity_delete(user_id: str, key: str, user: Any = Depends(_get_request_user)) -> Any:
    if _entity_memory_instance is not None:
        _entity_memory_cache["instance"] = _entity_memory_instance
    return await memory_feedback_router.legacy_exports["api_entity_delete"](user_id, key, user)


async def api_feedback_record(
    req: _FeedbackRecordRequest, user: Any = Depends(_get_request_user)
) -> Any:
    if _feedback_store_instance is not None:
        _feedback_store_cache["instance"] = _feedback_store_instance
    return await memory_feedback_router.legacy_exports["api_feedback_record"](req, user)


async def api_feedback_stats(user: Any = Depends(_get_request_user)) -> Any:
    if _feedback_store_instance is not None:
        _feedback_store_cache["instance"] = _feedback_store_instance
    return await memory_feedback_router.legacy_exports["api_feedback_stats"](user)


async def _prime_slack_manager_cache() -> None:
    maybe_mgr = _get_slack_manager()
    _slack_mgr_cache["instance"] = await maybe_mgr if inspect.isawaitable(maybe_mgr) else maybe_mgr


async def api_slack_send(req: _SlackSendRequest, user: Any = Depends(_require_admin_user)) -> Any:
    await _prime_slack_manager_cache()
    return await integrations_router.legacy_exports["api_slack_send"](req, user)


async def api_slack_channels(user: Any = Depends(_require_admin_user)) -> Any:
    await _prime_slack_manager_cache()
    return await integrations_router.legacy_exports["api_slack_channels"](user)


def _prime_jira_manager_cache() -> None:
    _jira_mgr_cache["instance"] = _get_jira_manager()


async def api_jira_create_issue(
    req: _JiraCreateRequest, user: Any = Depends(_require_admin_user)
) -> Any:
    _prime_jira_manager_cache()
    return await integrations_router.legacy_exports["api_jira_create_issue"](req, user)


async def api_jira_search_issues(
    jql: str = "", max_results: int = 20, user: Any = Depends(_require_admin_user)
) -> Any:
    _prime_jira_manager_cache()
    return await integrations_router.legacy_exports["api_jira_search_issues"](
        jql=jql, max_results=max_results, _user=user
    )


def _prime_teams_manager_cache() -> None:
    _teams_mgr_cache["instance"] = _get_teams_manager()


async def api_teams_send(req: _TeamsSendRequest, user: Any = Depends(_require_admin_user)) -> Any:
    _prime_teams_manager_cache()
    return await integrations_router.legacy_exports["api_teams_send"](req, user)


# Operations/Poyraz/Coverage HTTP request models and route handlers live in
# web.routes.operations_models; aliases are kept for existing direct unit-test imports.
_OperationChecklistCreateRequest = operations_route_models.OperationChecklistCreateRequest
_ContentAssetCreateRequest = operations_route_models.ContentAssetCreateRequest
_CampaignCreateRequest = operations_route_models.CampaignCreateRequest
_PoyrazToolRunRequest = operations_route_models.PoyrazToolRunRequest
_LandingPageDraftRequest = operations_route_models.LandingPageDraftRequest
_CampaignCopyGenerateRequest = operations_route_models.CampaignCopyGenerateRequest
_ServiceOperationsPlanRequest = operations_route_models.ServiceOperationsPlanRequest
_CoverageAnalyzeRequest = operations_route_models.CoverageAnalyzeRequest
_CoverageGenerateRequest = operations_route_models.CoverageGenerateRequest
_CoverageBatchRequest = operations_route_models.CoverageBatchRequest

_poyraz_agent_instance: Any | None = None
_coverage_agent_instance: Any | None = None


async def _get_poyraz_agent_instance() -> Any:
    """Return a reusable PoyrazAgent for REST operations endpoints."""
    global _poyraz_agent_instance
    if _poyraz_agent_instance is None:
        from agent.roles.poyraz_agent import PoyrazAgent

        _poyraz_agent_instance = PoyrazAgent(config=cfg)
    return _poyraz_agent_instance


async def _get_coverage_agent_instance() -> Any:
    """Return a reusable CoverageAgent for QA/Coverage REST endpoints."""
    global _coverage_agent_instance
    if _coverage_agent_instance is None:
        from agent.roles.coverage_agent import CoverageAgent

        _coverage_agent_instance = CoverageAgent(config=cfg)
    return _coverage_agent_instance


def _decode_agent_tool_result(raw_result: Any) -> dict[str, Any]:
    return operations_routes.decode_agent_tool_result(raw_result)


def _serialize_coverage_task(record: Any) -> dict[str, Any]:
    return operations_routes.serialize_coverage_task(record)


def _build_operations_dependencies() -> SimpleNamespace:
    return SimpleNamespace(
        await_if_needed=_await_if_needed,
        emit_control_room_event=_emit_control_room_event,
        get_coverage_agent_instance=lambda: _get_coverage_agent_instance(),
        get_poyraz_agent_instance=lambda: _get_poyraz_agent_instance(),
        get_request_user=_get_request_user,
        get_user_tenant=_get_user_tenant,
        resolve_agent_instance=_resolve_agent_instance,
    )


def _reset_operations_route_dependencies() -> None:
    """Keep direct web_server route calls isolated from route-module test overrides."""
    operations_routes.configure_operations_dependencies(_build_operations_dependencies)


async def api_operations_list_campaigns(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_operations_list_campaigns(*args, **kwargs)


async def api_operations_create_campaign(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_operations_create_campaign(*args, **kwargs)


async def api_operations_list_assets(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_operations_list_assets(*args, **kwargs)


async def api_operations_add_asset(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_operations_add_asset(*args, **kwargs)


async def api_operations_list_checklists(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_operations_list_checklists(*args, **kwargs)


async def api_operations_add_checklist(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_operations_add_checklist(*args, **kwargs)


async def api_operations_poyraz_run(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_operations_poyraz_run(*args, **kwargs)


async def api_operations_generate_landing_page(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_operations_generate_landing_page(*args, **kwargs)


async def api_operations_generate_campaign_copy(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_operations_generate_campaign_copy(*args, **kwargs)


async def api_operations_plan_service(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_operations_plan_service(*args, **kwargs)


async def api_qa_coverage_tasks(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_qa_coverage_tasks(*args, **kwargs)


async def api_qa_coverage_analyze(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_qa_coverage_analyze(*args, **kwargs)


async def api_qa_coverage_generate(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_qa_coverage_generate(*args, **kwargs)


async def api_qa_coverage_batch(*args: Any, **kwargs: Any) -> Any:
    _reset_operations_route_dependencies()
    return await operations_routes.api_qa_coverage_batch(*args, **kwargs)


operations_router = operations_routes.build_operations_router(_build_operations_dependencies)
_app_factory.register_routers(app, [operations_router])


# ─────────────────────────────────────────────
#  Proaktif Otonomi / Federation
# ─────────────────────────────────────────────


_FederationTaskRequest = federation_routes.FederationTaskRequest
_FederationFeedbackRequest = federation_routes.FederationFeedbackRequest
_AutonomyWakeRequest = autonomy_routes.AutonomyWakeRequest


def _verify_hmac_signature(
    payload_body: bytes, secret_value: str, signature_header: str, *, label: str
) -> None:
    secret = str(secret_value or "").encode("utf-8")
    if not secret:
        return
    if not signature_header:
        raise HTTPException(status_code=401, detail=f"{label} imza başlığı eksik.")
    expected_signature = "sha256=" + hmac.new(secret, payload_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, signature_header):
        raise HTTPException(status_code=401, detail="Geçersiz imza.")


def _build_autonomy_dependencies() -> SimpleNamespace:
    return SimpleNamespace(
        await_if_needed=_await_if_needed,
        cfg=cfg,
        dispatch_autonomy_trigger=lambda **kwargs: _dispatch_autonomy_trigger(**kwargs),
        embed_event_driven_federation_payload=(
            lambda payload, workflow: _embed_event_driven_federation_payload(payload, workflow)
        ),
        resolve_agent_instance=_resolve_agent_instance,
        resolve_ci_failure_context=_resolve_ci_failure_context,
        run_event_driven_federation_workflow=(
            lambda **kwargs: _run_event_driven_federation_workflow(**kwargs)
        ),
        verify_hmac_signature=lambda *args, **kwargs: _verify_hmac_signature(*args, **kwargs),
    )


def _build_federation_dependencies() -> SimpleNamespace:
    return SimpleNamespace(
        action_feedback_cls=ActionFeedback,
        cfg=cfg,
        derive_correlation_id=derive_correlation_id,
        dispatch_autonomy_trigger=lambda **kwargs: _dispatch_autonomy_trigger(**kwargs),
        federation_task_envelope_cls=FederationTaskEnvelope,
        federation_task_result_cls=FederationTaskResult,
        legacy_federation_protocol_v1=LEGACY_FEDERATION_PROTOCOL_V1,
        normalize_federation_protocol=normalize_federation_protocol,
        verify_hmac_signature=lambda *args, **kwargs: _verify_hmac_signature(*args, **kwargs),
    )


autonomy_webhook = autonomy_routes.autonomy_webhook
autonomy_wake = autonomy_routes.autonomy_wake
autonomy_activity = autonomy_routes.autonomy_activity
swarm_federation_execute = federation_routes.swarm_federation_execute
swarm_federation_feedback = federation_routes.swarm_federation_feedback


autonomy_router = autonomy_routes.build_autonomy_router(_build_autonomy_dependencies)
_app_factory.register_routers(app, [autonomy_router])

federation_router = federation_routes.build_federation_router(_build_federation_dependencies)
_app_factory.register_routers(app, [federation_router])


# ─────────────────────────────────────────────
#  GitHub Webhook routes live in web/routes/webhooks.py
# ─────────────────────────────────────────────


spa_fallback = web_bootstrap.build_spa_fallback_handler(
    index=lambda: index(),
    await_value=_await_if_needed,
)
app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)(spa_fallback)


# ─────────────────────────────────────────────
#  BAŞLATMA
# ─────────────────────────────────────────────


def main() -> None:
    """Run the Sidar web CLI entrypoint."""
    from web.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
