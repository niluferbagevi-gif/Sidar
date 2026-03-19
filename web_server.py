"""
Sidar Project - Web Arayüzü Sunucusu
FastAPI + WebSocket ile asenkron (async) çift yönlü akış destekli chat arayüzü.

Başlatmak için:
    python web_server.py
    python web_server.py --host 0.0.0.0 --port 7860
"""

import argparse
import asyncio
import atexit
import base64
import contextlib
import hashlib
import hmac
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
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Union

import jwt

try:
    import anyio
    _ANYIO_CLOSED = anyio.ClosedResourceError
except ImportError:  # anyio FastAPI/uvicorn bağımlılığıdır; normalde hep kurulu gelir
    _ANYIO_CLOSED = None

import uvicorn
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis.asyncio import Redis

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except Exception:  # OpenTelemetry opsiyoneldir
    trace = None
    OTLPSpanExporter = None
    FastAPIInstrumentor = None
    HTTPXClientInstrumentor = None
    TracerProvider = None
    Resource = None
    BatchSpanProcessor = None

from agent.base_agent import BaseAgent
from agent.core.contracts import ExternalTrigger, FederationTaskEnvelope, FederationTaskResult
from agent.core.event_stream import get_agent_event_bus
from agent.registry import AgentRegistry
from agent.sidar_agent import SidarAgent
from agent.swarm import SwarmOrchestrator, SwarmTask
from config import Config
from core.hitl import get_hitl_gate, get_hitl_store, set_hitl_broadcast_hook
from core.llm_client import LLMAPIError
from core.llm_metrics import get_llm_metrics_collector
from managers.system_health import render_llm_metrics_prometheus

try:
    from core.llm_metrics import reset_current_metrics_user_id, set_current_metrics_user_id
except Exception:  # test stub/fallback
    def set_current_metrics_user_id(_user_id: str):
        return None

    def reset_current_metrics_user_id(_token) -> None:
        return None

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  HITL WebSocket Yayın Kümesi
# ─────────────────────────────────────────────
_hitl_ws_clients: set = set()


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
_shutdown_cleanup_done = False
MAX_FILE_CONTENT_BYTES = 1_048_576  # 1 MB



def _list_child_ollama_pids() -> list[int]:
    """Bu prosesin çocukları arasında ollama süreçlerini bulur."""
    try:
        out = subprocess.check_output(["ps", "-eo", "pid=,ppid=,comm=,args="], stderr=subprocess.DEVNULL).decode("utf-8", errors="replace")
    except Exception:
        return []

    me = os.getpid()
    pids: list[int] = []
    for line in out.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except Exception:
            continue
        comm = parts[2].strip().lower()
        args = parts[3].strip().lower()
        if ppid != me:
            continue
        if comm == "ollama" or "ollama serve" in args:
            pids.append(pid)
    return pids


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
        agent = await get_agent()
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
    agent = await get_agent()
    trigger = ExternalTrigger(
        trigger_id=f"trigger-{secrets.token_hex(6)}",
        source=trigger_source,
        event_name=event_name,
        payload=payload,
        meta=dict(meta or {}),
    )
    if hasattr(agent, "handle_external_trigger"):
        result = await agent.handle_external_trigger(trigger)
    else:
        summary = await _collect_agent_response(agent, trigger.to_prompt())
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
        except asyncio.TimeoutError:
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


# ─────────────────────────────────────────────
#  FASTAPI UYGULAMASI
# ─────────────────────────────────────────────

@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    global _rag_prewarm_task, _agent_lock, _redis_lock, _local_rate_lock, _autonomy_cron_task, _autonomy_cron_stop
    # Kilitleri event loop ayaktayken kesin olarak başlat (lazy başlatma race-condition'ı önler)
    _agent_lock = asyncio.Lock()
    _redis_lock = asyncio.Lock()
    _local_rate_lock = asyncio.Lock()
    # Config doğrulamasını thread'de çalıştır — sync httpx Ollama çağrısı event loop'u bloklamaz (O-4)
    await asyncio.to_thread(Config.validate_critical_settings)
    _rag_prewarm_task = asyncio.create_task(_prewarm_rag_embeddings())
    if bool(getattr(cfg, "ENABLE_AUTONOMOUS_CRON", False)):
        _autonomy_cron_stop = asyncio.Event()
        _autonomy_cron_task = asyncio.create_task(_autonomous_cron_loop(_autonomy_cron_stop))
    try:
        yield
    finally:
        if _autonomy_cron_stop is not None:
            _autonomy_cron_stop.set()
        if _autonomy_cron_task and not _autonomy_cron_task.done():
            _autonomy_cron_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _autonomy_cron_task
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


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    """Bearer token ile stateless JWT kullanıcı doğrulaması uygular."""
    open_paths = {
        "/", "/health", "/docs", "/redoc", "/openapi.json",
        "/auth/login", "/auth/register",
    }
    if (
        request.method == "OPTIONS"
        or request.url.path in open_paths
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

    agent = await get_agent()
    request.state.user = user
    await agent.memory.set_active_user(user.id, user.username)
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
    if not all([trace, OTLPSpanExporter, FastAPIInstrumentor, TracerProvider, Resource, BatchSpanProcessor]):
        logger.warning("ENABLE_TRACING açık fakat OpenTelemetry bağımlılıkları yüklenemedi.")
        return

    resource = Resource.create({"service.name": getattr(cfg, "OTEL_SERVICE_NAME", "sidar-web")})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=cfg.OTEL_EXPORTER_ENDPOINT, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    if HTTPXClientInstrumentor is not None:
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
            agent = await get_agent()
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
    return {
        "id": int(record.id),
        "role_name": str(record.role_name),
        "prompt_text": str(record.prompt_text),
        "version": int(record.version),
        "is_active": bool(record.is_active),
        "created_at": str(record.created_at),
        "updated_at": str(record.updated_at),
    }


def _serialize_swarm_result(record) -> dict:
    return {
        "task_id": str(getattr(record, "task_id", "") or ""),
        "agent_role": str(getattr(record, "agent_role", "") or ""),
        "status": str(getattr(record, "status", "") or ""),
        "summary": str(getattr(record, "summary", "") or ""),
        "elapsed_ms": int(getattr(record, "elapsed_ms", 0) or 0),
        "evidence": list(getattr(record, "evidence", []) or []),
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


def _load_plugin_agent_class(source_code: str, class_name: str | None, module_label: str) -> type[BaseAgent]:
    namespace = {"__name__": module_label}
    try:
        exec(compile(source_code, module_label, "exec"), namespace)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Plugin kodu derlenemedi/çalıştırılamadı: {exc}") from exc

    if class_name:
        candidate = namespace.get(class_name)
        if not inspect.isclass(candidate):
            raise HTTPException(status_code=400, detail=f"Belirtilen sınıf bulunamadı: {class_name}")
        if not issubclass(candidate, BaseAgent):
            raise HTTPException(status_code=400, detail="Plugin sınıfı BaseAgent türetmelidir")
        return candidate

    discovered: list[type[BaseAgent]] = []
    for obj in namespace.values():
        if inspect.isclass(obj) and issubclass(obj, BaseAgent) and obj is not BaseAgent:
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

    agent = await get_agent()
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
    agent = await get_agent()
    user = await agent.memory.db.authenticate_user(username=username, password=password)
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya şifre hatalı")

    token = await _issue_auth_token(agent, user)
    return JSONResponse({"user": {"id": user.id, "username": user.username, "role": user.role}, "access_token": token})


@app.get("/auth/me")
async def auth_me(request: Request, user=Depends(_get_request_user)):
    return JSONResponse({"id": user.id, "username": user.username, "role": user.role})


@app.get("/admin/stats")
async def admin_stats(_user=Depends(_require_admin_user)):
    agent = await get_agent()
    stats = await agent.memory.db.get_admin_stats()
    return JSONResponse(stats)


@app.get("/admin/prompts")
async def admin_list_prompts(role_name: str = "", _user=Depends(_require_admin_user)):
    agent = await get_agent()
    prompts = await agent.memory.db.list_prompts(role_name=role_name.strip() or None)
    return JSONResponse({"items": [_serialize_prompt(p) for p in prompts]})


@app.get("/admin/prompts/active")
async def admin_active_prompt(role_name: str = "system", _user=Depends(_require_admin_user)):
    agent = await get_agent()
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

    agent = await get_agent()
    record = await agent.memory.db.upsert_prompt(role_name=role_name, prompt_text=prompt_text, activate=bool(payload.activate))
    if role_name == "system" and bool(record.is_active):
        agent.system_prompt = record.prompt_text
    return JSONResponse(_serialize_prompt(record))


@app.post("/admin/prompts/activate")
async def admin_activate_prompt(payload: _PromptActivateRequest, _user=Depends(_require_admin_user)):
    agent = await get_agent()
    active = await agent.memory.db.activate_prompt(payload.prompt_id)
    if not active:
        raise HTTPException(status_code=404, detail="Prompt kaydı bulunamadı")
    if active.role_name == "system":
        agent.system_prompt = active.prompt_text
    return JSONResponse(_serialize_prompt(active))


@app.get("/admin/policies/{user_id}")
async def admin_list_policies(user_id: str, tenant_id: str = "", _user=Depends(_require_admin_user)):
    agent = await get_agent()
    records = await agent.memory.db.list_access_policies(user_id=user_id, tenant_id=tenant_id.strip() or None)
    return JSONResponse({"items": [_serialize_policy(r) for r in records]})


@app.post("/admin/policies")
async def admin_upsert_policy(payload: _PolicyUpsertRequest, _user=Depends(_require_admin_user)):
    agent = await get_agent()
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


@app.post("/api/swarm/execute")
async def execute_swarm(payload: _SwarmExecuteRequest, user=Depends(_get_request_user)):
    agent = await get_agent()
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
        agent = await get_agent()
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
    global _redis_client
    if _redis_client is None:
        async with _redis_lock:
            if _redis_client is None:
                try:
                    client = Redis.from_url(cfg.REDIS_URL, encoding="utf-8", decode_responses=True)
                    await client.ping()
                    _redis_client = client
                except Exception as exc:
                    logger.warning("Redis bağlantısı kurulamadı (%s). Local rate limit fallback kullanılacak.", exc)
                    _redis_client = None
    return _redis_client


async def _local_is_rate_limited(key: str, limit: int, window_sec: int) -> bool:
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
    if request.url.path.startswith("/ui/") or request.url.path.startswith("/static/") or request.url.path == "/health":
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
        await _redis_client.aclose()
        _redis_client = None


# CORS: localhost/loopback kökenlerine porttan bağımsız izin ver.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$",
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

# React SPA (web_ui_react/dist) hazırsa onu, değilse legacy web_ui dizinini sun.
LEGACY_WEB_DIR = Path(__file__).parent / "web_ui"
REACT_DIST_DIR = Path(__file__).parent / "web_ui_react" / "dist"
WEB_DIR = REACT_DIST_DIR if REACT_DIST_DIR.exists() else LEGACY_WEB_DIR

# Legacy kodun /static beklentisi korunur; React build'de de aynı mount kalır.
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# Vite build asset'leri (/assets/*) için ayrı mount.
if (WEB_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")



# ─────────────────────────────────────────────
#  ROTALAR
# ─────────────────────────────────────────────

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Tarayıcının favicon isteğini 404 hatası vermeden sessizce (204) geçiştirir."""
    return Response(status_code=204)


@app.get("/vendor/{file_path:path}", include_in_schema=False)
async def serve_vendor(file_path: str):
    """Yerel vendor kütüphanelerini servis eder (highlight.js, marked.js).
    install_sidar.sh tarafından web_ui/vendor/ dizinine indirilmiş dosyalar buradan sunulur.
    """
    vendor_dir = (WEB_DIR / "vendor").resolve()
    safe_path = (vendor_dir / file_path).resolve()
    if not str(safe_path).startswith(str(vendor_dir)):
        return Response(status_code=403)
    if not safe_path.exists():
        return Response(status_code=404)
    return FileResponse(safe_path)


@app.get("/", response_class=HTMLResponse)
async def index():
    """Ana sayfa — React SPA veya legacy chat arayüzü."""
    html_file = WEB_DIR / "index.html"
    if not html_file.exists():
        return HTMLResponse("<h1>Hata: UI index.html bulunamadı.</h1>", status_code=500)
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

    async for chunk in agent.respond(prompt):
        m_tool = tool_sentinel.match(chunk)
        m_thought = thought_sentinel.match(chunk)
        if m_tool:
            await websocket.send_json({"tool_call": m_tool.group(1)})
        elif m_thought:
            await websocket.send_json({"thought": m_thought.group(1)})
        else:
            await websocket.send_json({"chunk": chunk})


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

    agent = await get_agent()
    active_task: asyncio.Task | None = None
    ws_user_id = ""
    ws_username = ""
    ws_authenticated = False

    # Başlık token'ı varsa bağlantı açılır açılmaz doğrula
    if header_token:
        ws_user = await _resolve_user_from_token(agent, header_token)
        if not ws_user:
            await _ws_close_policy_violation(websocket, "Invalid or expired token")
            return
        ws_user_id = ws_user.id
        ws_username = ws_user.username
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
                    except asyncio.TimeoutError:
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
                ws_user = await _resolve_user_from_token(agent, auth_token)
                if not ws_user:
                    await _ws_close_policy_violation(websocket, "Invalid or expired token")
                    return
                ws_user_id = ws_user.id
                ws_username = ws_user.username
                ws_authenticated = True
                await agent.memory.set_active_user(ws_user_id, ws_username)
                with contextlib.suppress(Exception):
                    await websocket.send_json({'auth_ok': True})
                continue

            if action == "cancel" and active_task and not active_task.done():
                active_task.cancel()
                await websocket.send_json({
                    "chunk": "\n\n*[Sistem: İşlem kullanıcı tarafından iptal edildi]*\n",
                    "done": True,
                })
                continue

            if not user_message:
                continue

            client_ip = websocket.client.host if websocket.client else "unknown"
            if await _redis_is_rate_limited("chat_ws", client_ip, _RATE_LIMIT, _RATE_WINDOW):
                await websocket.send_json({"chunk": "[Hız Sınırı] Çok fazla istek. Lütfen bir dakika bekleyin.", "done": True})
                continue

            if active_task and not active_task.done():
                active_task.cancel()

            active_task = asyncio.create_task(generate_response(user_message))

    except WebSocketDisconnect:
        logger.info("İstemci WebSocket bağlantısını kesti.")
        if active_task and not active_task.done():
            active_task.cancel()
    except Exception as _ws_exc:
        # anyio.ClosedResourceError: uvicorn/anyio üst katmanının bağlantı
        # kapatma sinyali — WebSocketDisconnect ile eşdeğer, normal çıkış.
        if _ANYIO_CLOSED is not None and isinstance(_ws_exc, _ANYIO_CLOSED):
            logger.info("İstemci WebSocket bağlantısını kesti (anyio ClosedResourceError).")
            if active_task and not active_task.done():
                active_task.cancel()
        else:
            logger.warning("WebSocket beklenmedik hata: %s", _ws_exc)


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

    agent = await get_agent()
    pipeline = MultimodalPipeline(agent.llm, cfg)
    max_voice_bytes = int(getattr(cfg, "VOICE_WS_MAX_BYTES", 10 * 1024 * 1024) or 10 * 1024 * 1024)

    audio_buffer = bytearray()
    ws_user_id = ""
    ws_username = ""
    ws_authenticated = False
    session_mime_type = "audio/webm"
    session_language: str | None = None
    session_prompt = ""

    if header_token:
        ws_user = await _resolve_user_from_token(agent, header_token)
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
                ws_user = await _resolve_user_from_token(agent, auth_token)
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
                await websocket.send_json({"voice_session": "ready", "mime_type": session_mime_type})
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
                continue

            if action == "cancel":
                audio_buffer.clear()
                await websocket.send_json({"cancelled": True, "done": True})
                continue

            if action not in {"commit", "process", "end"}:
                continue

            session_mime_type = str(payload.get("mime_type", session_mime_type) or session_mime_type)
            session_language = payload.get("language", session_language)
            session_prompt = str(payload.get("prompt", session_prompt) or session_prompt)

            if not audio_buffer:
                await websocket.send_json({"error": "İşlenecek ses verisi bulunamadı.", "done": True})
                continue

            result = await pipeline.transcribe_bytes(
                bytes(audio_buffer),
                mime_type=session_mime_type,
                language=session_language,
                prompt=session_prompt,
            )
            audio_buffer.clear()

            if not isinstance(result, dict) or not result.get("success"):
                reason = "Ses transkripsiyonu başarısız oldu."
                if isinstance(result, dict):
                    reason = str(result.get("reason", reason) or reason)
                await websocket.send_json({"error": reason, "done": True})
                continue

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
                continue

            try:
                await _ws_stream_agent_text_response(websocket, agent, transcript_text)
            except LLMAPIError as exc:
                await websocket.send_json(
                    {
                        "chunk": f"\n[LLM Hatası] {exc.provider} ({exc.status_code or 'n/a'}): {exc}",
                        "done": True,
                    }
                )
                continue
            except Exception as exc:
                logger.exception("Voice websocket agent yanıtı hatası: %s", exc)
                await websocket.send_json({"chunk": f"\n[Sistem Hatası] {exc}", "done": True})
                continue

            await websocket.send_json({"done": True})
    except WebSocketDisconnect:
        logger.info("İstemci voice WebSocket bağlantısını kesti.")
    except Exception as exc:
        if _ANYIO_CLOSED is not None and isinstance(exc, _ANYIO_CLOSED):
            logger.info("İstemci voice WebSocket bağlantısını kesti (anyio ClosedResourceError).")
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
    a = await get_agent()
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


@app.get(
    "/health",
    summary="Sağlık Kontrolü (Health Check)",
    description="Liveness/readiness kontrolü için sistem sağlık bilgisini döndürür.",
    responses={
        200: {"description": "Sistem sağlıklı"},
        503: {"description": "Sistemde kritik bir sorun var"},
    },
)
async def health_check():
    """
    Kubernetes/Docker monitör sistemleri için yapısal (JSON) sağlık kontrolü.
    (Liveness/Readiness probe endpointi)
    """
    agent = await get_agent()
    health_data = agent.health.get_health_summary()
    health_data["uptime_seconds"] = int(time.monotonic() - _start_time)

    # Eğer ana yapay zeka servisi (Ollama) çöktüyse 503 HTTP kodu döndür
    if agent.cfg.AI_PROVIDER == "ollama" and not health_data["ollama_online"]:
        health_data["status"] = "degraded"
        return JSONResponse(health_data, status_code=503)

    return JSONResponse(health_data)


@app.get("/metrics")
async def metrics(request: Request, _user=Depends(_require_metrics_access)):
    """
    Temel operasyonel metrikler (admin veya METRICS_TOKEN gerektirir).
    - Varsayılan: JSON formatı (her istemci için çalışır).
    - 'Accept: text/plain' başlığı + prometheus_client kurulu ise Prometheus formatı döner.
    """
    agent = await get_agent()
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
    if "text/plain" in accept:
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
    agent = await get_agent()
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
    agent = await get_agent()
    session = await agent.memory.db.load_session(session_id, user.id)
    if not session:
        return JSONResponse({"success": False, "error": "Oturum bulunamadı."}, status_code=404)
    messages = await agent.memory.db.get_session_messages(session_id)
    history = [{"role": m.role, "content": m.content, "timestamp": agent.memory._safe_ts(m.created_at), "tokens_used": m.tokens_used} for m in messages]
    return JSONResponse({"success": True, "history": history})

@app.post("/sessions/new")
async def new_session(request: Request, user=Depends(_get_request_user)):
    """Aktif kullanıcı için yeni bir oturum oluşturur."""
    agent = await get_agent()
    session = await agent.memory.db.create_session(user.id, "Yeni Sohbet")
    return JSONResponse({"success": True, "session_id": session.id})

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request, user=Depends(_get_request_user)):
    """Kullanıcıya ait belirli bir oturumu siler."""
    agent = await get_agent()
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

    # Varsayılan branch (örn. main veya master): refs/remotes/origin/HEAD → "origin/main"
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

    return JSONResponse({"branch": branch, "repo": repo or "sidar_project", "default_branch": default_branch})


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
    agent = await get_agent()

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
    agent = await get_agent()
    if not agent.github.is_available():
        return JSONResponse({"success": False, "error": "GitHub token ayarlanmamış.", "prs": []}, status_code=503)
    ok, prs, err = agent.github.get_pull_requests_detailed(state=state, limit=min(limit, 50))
    if not ok:
        return JSONResponse({"success": False, "error": err, "prs": []}, status_code=500)
    return JSONResponse({"success": True, "prs": prs, "repo": agent.github.repo_name})


@app.get("/github-prs/{number}")
async def github_pr_detail(number: int):
    """Belirli bir PR'ın detaylarını döndürür."""
    agent = await get_agent()
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

    agent = await get_agent()
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
    agent = await get_agent()
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

    agent = await get_agent()
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

    agent = await get_agent()
    session_id = agent.memory.active_session_id or "global"
    ok, msg = await agent.docs.add_document_from_url(url, title=title, session_id=session_id)
    return JSONResponse({"success": ok, "message": msg})


@app.delete("/rag/docs/{doc_id}")
async def rag_delete_doc(doc_id: str):
    """RAG deposundan belge siler (oturum izolasyonuna uygun)."""
    agent = await get_agent()
    session_id = agent.memory.active_session_id or "global"
    msg = await asyncio.to_thread(agent.docs.delete_document, doc_id, session_id)
    success = msg.startswith("✓")
    return JSONResponse({"success": success, "message": msg})




@app.post("/api/rag/upload")
async def upload_rag_file(file: UploadFile = File(...)):
    """Web arayüzünden Sürükle-Bırak ile gelen dosyaları RAG deposuna ekler."""
    agent = await get_agent()
    session_id = agent.memory.active_session_id or "global"

    temp_dir = None
    try:
        # Dosya boyutunu diske yazmadan önce kontrol et (DoS / disk doldurma koruması)
        max_bytes = Config.MAX_RAG_UPLOAD_BYTES
        data = await file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Dosya çok büyük. Maksimum izin verilen boyut: {max_bytes // (1024 * 1024)} MB",
            )

        # Dosyayı orijinal adıyla güvenli bir geçici klasöre kaydet
        temp_dir = Path(tempfile.mkdtemp())
        original_name = file.filename or "uploaded_file.txt"
        safe_filename = "".join(c for c in original_name if c.isalnum() or c in ".-_ ")
        if not safe_filename:
            safe_filename = "uploaded_file.txt"
        tmp_path = temp_dir / safe_filename

        with open(tmp_path, "wb") as buffer:
            buffer.write(data)

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
    agent = await get_agent()
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
    agent = await get_agent()
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
    agent = await get_agent()
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

    agent = await get_agent()
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
    prompt: Optional[str] = Field(None, description="Özel analiz talimatı (opsiyonel)")


class _VisionMockupRequest(BaseModel):
    image_base64: str = Field(..., description="Base64 kodlu mockup görüntüsü")
    mime_type: str = Field("image/png", description="Görüntü MIME türü")
    framework: str = Field("html", description="Hedef framework: html, react, vue")
    prompt: Optional[str] = Field(None, description="Ek talimat (opsiyonel)")


@app.post("/api/vision/analyze", summary="Görüntü Analizi", tags=["Vision"])
async def api_vision_analyze(req: _VisionAnalyzeRequest):
    """VisionPipeline ile görüntüyü analiz eder."""
    try:
        from core.vision import VisionPipeline, build_analyze_prompt
    except ImportError:
        raise HTTPException(status_code=501, detail="core.vision modülü yüklenemedi.")

    agent = await get_agent()
    pipeline = VisionPipeline(agent.llm, cfg)
    prompt = req.prompt or build_analyze_prompt(req.analysis_type)
    result = await pipeline.analyze(
        image_b64=req.image_base64,
        mime_type=req.mime_type,
        prompt=prompt,
    )
    return JSONResponse({"success": True, "result": result})


@app.post("/api/vision/mockup", summary="Mockup → Kod Dönüşümü", tags=["Vision"])
async def api_vision_mockup(req: _VisionMockupRequest):
    """VisionPipeline ile mockup görüntüsünden kod üretir."""
    try:
        from core.vision import VisionPipeline
    except ImportError:
        raise HTTPException(status_code=501, detail="core.vision modülü yüklenemedi.")

    agent = await get_agent()
    pipeline = VisionPipeline(agent.llm, cfg)
    code = await pipeline.mockup_to_code(
        image_b64=req.image_base64,
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
    ttl_days: Optional[int] = Field(None, description="Yaşam süresi (gün); None = kalıcı")


_entity_memory_instance = None


async def _get_entity_memory():
    global _entity_memory_instance
    if _entity_memory_instance is None:
        try:
            from core.entity_memory import get_entity_memory
            _entity_memory_instance = get_entity_memory(cfg)
            await _entity_memory_instance.initialize()
        except Exception as exc:
            raise HTTPException(status_code=501, detail=f"EntityMemory başlatılamadı: {exc}")
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
    note: Optional[str] = Field(None, description="Ek not")


_feedback_store_instance = None


async def _get_feedback_store():
    global _feedback_store_instance
    if _feedback_store_instance is None:
        try:
            from core.active_learning import get_feedback_store
            _feedback_store_instance = get_feedback_store(cfg)
            await _feedback_store_instance.initialize()
        except Exception as exc:
            raise HTTPException(status_code=501, detail=f"FeedbackStore başlatılamadı: {exc}")
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
    channel: Optional[str] = Field(None, description="Hedef kanal (ör. #general)")
    thread_ts: Optional[str] = Field(None, description="Thread zaman damgası")


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
    mgr = await _get_slack_manager()
    if not mgr.is_available():
        raise HTTPException(status_code=503, detail="Slack entegrasyonu yapılandırılmamış.")
    ok, err = await mgr.send_message(text=req.text, channel=req.channel, thread_ts=req.thread_ts)
    if not ok:
        raise HTTPException(status_code=502, detail=f"Slack hatası: {err}")
    return JSONResponse({"success": True})


@app.get("/api/integrations/slack/channels", summary="Slack Kanal Listesi", tags=["Slack"])
async def api_slack_channels():
    """Workspace'deki Slack kanallarını listeler (SDK gerektirir)."""
    mgr = await _get_slack_manager()
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
    description: Optional[str] = Field(None, description="Issue açıklaması")
    issue_type: str = Field("Task", description="Issue türü: Task, Bug, Story")
    priority: Optional[str] = Field(None, description="Öncelik: Highest, High, Medium, Low")


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
    title: Optional[str] = Field(None, description="Mesaj başlığı")


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


# ─────────────────────────────────────────────
#  Proaktif Otonomi / Federation
# ─────────────────────────────────────────────


class _FederationTaskRequest(BaseModel):
    task_id: str = Field(..., description="Dış platform tarafından verilen görev kimliği")
    source_system: str = Field(..., description="Gönderen swarm platformu (örn. crewai, autogen)")
    source_agent: str = Field(..., description="Gönderen ajan veya workflow adı")
    target_agent: str = Field("supervisor", description="Sidar içinde hedef ajan/rol")
    goal: str = Field(..., description="Sidar'ın çalıştıracağı hedef görev")
    intent: str = Field("mixed", description="Görev intent tipi")
    context: dict[str, str] = Field(default_factory=dict, description="Yapısal bağlam")
    inputs: list[str] = Field(default_factory=list, description="Ek girdiler")
    meta: dict[str, str] = Field(default_factory=dict, description="Ek protokol meta verisi")


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

    result = await _dispatch_autonomy_trigger(
        trigger_source=f"webhook:{source}",
        event_name=str(data.get("event_name", source) or source),
        payload=data if isinstance(data, dict) else {"payload": data},
        meta={"source": source},
    )
    return JSONResponse({"success": True, "result": result})


@app.post(
    "/api/autonomy/wake",
    summary="Manuel Otonomi Uyanışı",
    description="SIDAR'ı kullanıcı veya sistem tarafından proaktif görev için uyandırır.",
)
async def autonomy_wake(req: _AutonomyWakeRequest):
    """Webhook dışı manuel/proaktif tetik giriş noktası."""
    payload = dict(req.payload or {})
    payload["prompt"] = req.prompt.strip()
    result = await _dispatch_autonomy_trigger(
        trigger_source=f"manual:{req.source.strip() or 'manual'}",
        event_name=req.event_name.strip() or "manual_wake",
        payload=payload,
        meta=dict(req.meta or {}),
    )
    return JSONResponse({"success": True, "result": result})


@app.get(
    "/api/autonomy/activity",
    summary="Otonomi Aktivite Akışı",
    description="Webhook/cron/manual kaynaklı son proaktif tetik geçmişini döndürür.",
)
async def autonomy_activity(limit: int = 20):
    """Son proaktif tetik kayıtlarını UI ve operasyon panelleri için sunar."""
    agent = await get_agent()
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
        intent=req.intent,
        context=dict(req.context or {}),
        inputs=list(req.inputs or []),
        meta=dict(req.meta or {}),
    )
    summary = await _collect_agent_response(await get_agent(), envelope.to_prompt())
    result = FederationTaskResult(
        task_id=envelope.task_id,
        source_system="sidar",
        source_agent=envelope.target_agent,
        target_system=envelope.source_system,
        target_agent=envelope.source_agent,
        status="success" if summary else "failed",
        summary=summary or "Sidar görev için çıktı üretemedi.",
        meta={"protocol": envelope.protocol},
    )
    return JSONResponse({"success": True, "result": asdict(result)})


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

    agent = await get_agent()
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
                await _dispatch_autonomy_trigger(
                    trigger_source="webhook:github",
                    event_name=x_github_event,
                    payload=data if isinstance(data, dict) else {"payload": data},
                    meta={"provider": "github"},
                )

    return JSONResponse({"success": True, "event": x_github_event, "message": "İşlendi"})


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
    args = parser.parse_args()

    # Dinamik config override
    if args.level:
        cfg.ACCESS_LEVEL = args.level
    if args.provider:
        cfg.AI_PROVIDER = args.provider

    # Ajan önceden başlat (ilk istekte gecikme olmasın).
    # Bellek katmanı native-async olduğu için initialize() adımı burada tamamlanır.
    global _agent
    _agent = SidarAgent(cfg)
    if hasattr(_agent, "initialize"):
        asyncio.run(_agent.initialize())

    display_host = "localhost" if args.host in ("0.0.0.0", "") else args.host
    version_label = f"v{_agent.VERSION}" if _agent.VERSION else "v?"

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
