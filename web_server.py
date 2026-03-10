"""
Sidar Project - Web Arayüzü Sunucusu
FastAPI + WebSocket ile asenkron (async) çift yönlü akış destekli chat arayüzü.

Başlatmak için:
    python web_server.py
    python web_server.py --host 0.0.0.0 --port 7860
"""

import argparse
import base64
import asyncio
import hashlib
import hmac
import json
import logging
import re
import shutil
import secrets
import subprocess
import time
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

try:
    import anyio
    _ANYIO_CLOSED = anyio.ClosedResourceError
except ImportError:  # anyio FastAPI/uvicorn bağımlılığıdır; normalde hep kurulu gelir
    _ANYIO_CLOSED = None

import uvicorn
from fastapi import BackgroundTasks, FastAPI, Request, UploadFile, File, WebSocket, WebSocketDisconnect, Header, HTTPException
from redis.asyncio import Redis
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except Exception:  # OpenTelemetry opsiyoneldir
    trace = None
    OTLPSpanExporter = None
    FastAPIInstrumentor = None
    TracerProvider = None
    Resource = None
    BatchSpanProcessor = None

from config import Config
from agent.sidar_agent import SidarAgent

logger = logging.getLogger(__name__)

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
MAX_FILE_CONTENT_BYTES = 1_048_576  # 1 MB




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
    """Singleton ajan — ilk async çağrıda başlatılır (asyncio.Lock ile korunur)."""
    global _agent, _agent_lock
    if _agent_lock is None:
        _agent_lock = asyncio.Lock()   # event loop başladıktan sonra oluştur
    if _agent is None:
        async with _agent_lock:
            if _agent is None:
                _agent = SidarAgent(cfg)
    return _agent


# ─────────────────────────────────────────────
#  FASTAPI UYGULAMASI
# ─────────────────────────────────────────────

@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    global _rag_prewarm_task
    _rag_prewarm_task = asyncio.create_task(_prewarm_rag_embeddings())
    try:
        yield
    finally:
        if _rag_prewarm_task and not _rag_prewarm_task.done():
            _rag_prewarm_task.cancel()
            try:
                await _rag_prewarm_task
            except asyncio.CancelledError:
                pass
        await _close_redis_client()


app = FastAPI(
    title="Sidar Web UI & REST API",
    description=(
        "Sidar AI Ajanı için Web Arayüzü ve REST API uç noktaları. "
        "RAG, GitHub, Görev Yönetimi ve Sistem İzleme API'lerini içerir."
    ),
    version="2.10.4",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=_app_lifespan,
)


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    """API_KEY ayarlıysa HTTP Basic Auth ile tüm istekleri koru."""
    api_key = getattr(cfg, "API_KEY", "")
    if not api_key:
        return await call_next(request)

    if request.method == "OPTIONS":
        return await call_next(request)

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            _, password = decoded.split(":", 1)
            if secrets.compare_digest(password, api_key):
                return await call_next(request)
        except Exception:
            pass

    return Response(
        content="Yetkisiz Erişim. Lütfen API anahtarınızı şifre alanına girin.",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Sidar Secure Web UI"'},
    )


# ─────────────────────────────────────────────
#  OBSERVABILITY (OpenTelemetry)
# ─────────────────────────────────────────────
def _setup_tracing() -> None:
    if not getattr(cfg, "ENABLE_TRACING", False):
        return
    if not all([trace, OTLPSpanExporter, FastAPIInstrumentor, TracerProvider, Resource, BatchSpanProcessor]):
        logger.warning("ENABLE_TRACING açık fakat OpenTelemetry bağımlılıkları yüklenemedi.")
        return

    resource = Resource.create({"service.name": "sidar-web"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=cfg.OTEL_EXPORTER_ENDPOINT, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    logger.info("✅ OpenTelemetry aktif: %s", cfg.OTEL_EXPORTER_ENDPOINT)


_setup_tracing()

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

# Test uyumluluğu için takma adlar; _local_rate_limits ile aynı sözlük nesnesini paylaşır
_rate_data: dict[str, list[float]] = _local_rate_limits
_rate_lock: asyncio.Lock | None = None

_start_time = time.monotonic()  # Sunucu başlangıç zamanı (/metrics için)


async def _get_redis() -> Redis | None:
    global _redis_client, _redis_lock
    if _redis_lock is None:
        _redis_lock = asyncio.Lock()
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
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        first_ip = xff.split(",")[0].strip()
        if first_ip:
            return first_ip
    xri = request.headers.get("X-Real-IP", "")
    if xri:
        return xri.strip()
    return request.client.host if request.client else "unknown"


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

# Modüler Web UI statik dosyalarını sunmak için
web_ui_dir = Path(__file__).parent / "web_ui"
app.mount("/static", StaticFiles(directory=web_ui_dir), name="static")

WEB_DIR = Path(__file__).parent / "web_ui"



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
    """Ana sayfa — chat arayüzü."""
    html_file = WEB_DIR / "index.html"
    if not html_file.exists():
        return HTMLResponse("<h1>Hata: web_ui/index.html bulunamadı.</h1>", status_code=500)
    return html_file.read_text(encoding="utf-8")


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    Çift yönlü WebSocket chat arayüzü.
    Kullanıcı mesajlarını alır, asenkron LLM yanıtlarını stream eder
    ve anlık iptal (cancel) isteklerini yönetir.
    """
    await websocket.accept()
    agent = await get_agent()
    active_task: asyncio.Task | None = None

    async def generate_response(msg: str) -> None:
        try:
            if len(agent.memory) == 0:
                title = msg[:30] + "..." if len(msg) > 30 else msg
                agent.memory.update_title(title)

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
        except Exception as exc:
            logger.exception("Agent respond hatası: %s", exc)
            try:
                await websocket.send_json({'chunk': f"\n[Sistem Hatası] {exc}", 'done': True})
            except Exception:
                pass

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue

            action = payload.get("action")
            user_message = payload.get("message", "").strip()

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
async def metrics(request: Request):
    """
    Temel operasyonel metrikler.
    - Varsayılan: JSON formatı (her istemci için çalışır).
    - 'Accept: text/plain' başlığı + prometheus_client kurulu ise Prometheus formatı döner.
    """
    agent = await get_agent()
    uptime_s  = int(time.monotonic() - _start_time)
    rag_docs  = agent.docs.doc_count
    sessions  = agent.memory.get_all_sessions()
    rl_total = sum(len(v) for v in _local_rate_limits.values())

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
    }

    # Prometheus formatı: istemci açıkça talep ederse VE kütüphane kuruluysa sun
    accept = request.headers.get("Accept", "")
    if "text/plain" in accept:
        try:
            from prometheus_client import (
                CollectorRegistry, Gauge, generate_latest, CONTENT_TYPE_LATEST,
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


# ─────────────────────────────────────────────
#  ÇOKLU SOHBET (SESSIONS) ROTALARI
# ─────────────────────────────────────────────

@app.get(
    "/sessions",
    summary="Tüm Oturumları Listele",
    description="Kayıtlı sohbet oturumları listesini ve aktif oturum kimliğini döndürür.",
    responses={200: {"description": "Oturum listesi başarıyla alındı"}},
)
async def get_sessions():
    """Tüm oturumların listesini döndürür."""
    agent = await get_agent()
    return JSONResponse({
        "active_session": agent.memory.active_session_id,
        "sessions": agent.memory.get_all_sessions()
    })

@app.get("/sessions/{session_id}")
async def load_session(session_id: str):
    """Belirli bir oturumu yükler ve geçmişini döndürür."""
    agent = await get_agent()
    if agent.memory.load_session(session_id):
        return JSONResponse({"success": True, "history": agent.memory.get_history()})
    return JSONResponse({"success": False, "error": "Oturum bulunamadı."}, status_code=404)

@app.post("/sessions/new")
async def new_session():
    """Yeni bir oturum oluşturur."""
    agent = await get_agent()
    session_id = agent.memory.create_session("Yeni Sohbet")
    return JSONResponse({"success": True, "session_id": session_id})

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Belirli bir oturumu siler."""
    agent = await get_agent()
    if agent.memory.delete_session(session_id):
        return JSONResponse({
            "success": True, 
            "active_session": agent.memory.active_session_id
        })
    return JSONResponse({"success": False, "error": "Silinemedi."}, status_code=500)

@app.get("/files")
async def list_project_files(path: str = ""):
    """
    Proje dizinindeki dosya ve klasörleri listeler.
    path parametresi boşsa proje kök dizinini listeler.
    """
    _root = Path(__file__).parent
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
        ".toml", ".html", ".css", ".js", ".ts", ".sh", ".env", ".example",
        ".gitignore", ".dockerignore", ".sql", ".csv", ".xml",
    }
    _root = Path(__file__).parent
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

    _root = Path(__file__).parent
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
        # Dosyayı orijinal adıyla güvenli bir geçici klasöre kaydet
        temp_dir = Path(tempfile.mkdtemp())
        original_name = file.filename or "uploaded_file.txt"
        safe_filename = "".join(c for c in original_name if c.isalnum() or c in ".-_ ")
        if not safe_filename:
            safe_filename = "uploaded_file.txt"
        tmp_path = temp_dir / safe_filename

        with open(tmp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

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
    ok, result = await asyncio.to_thread(
        agent.docs.search, q.strip(), min(top_k, 10), mode, session_id
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
    agent.memory.clear()
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
async def set_level_endpoint(request: Request):
    """Güvenlik seviyesini çalışma zamanında değiştirir."""
    body = await request.json()
    new_level = body.get("level", "").strip()
    if not new_level:
        return JSONResponse({"success": False, "error": "Seviye belirtilmedi."}, status_code=400)

    agent = await get_agent()
    result_msg = await asyncio.to_thread(agent.set_access_level, new_level)
    return JSONResponse(
        {
            "success": True,
            "message": result_msg,
            "current_level": agent.security.level_name,
        }
    )


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
        await asyncio.to_thread(agent.memory.add, "user", msg)
        await asyncio.to_thread(
            agent.memory.add,
            "assistant",
            "GitHub bildirimini kayıtlarıma aldım. İstenirse 'github_commits' veya PR/Issue araçlarımla detayları inceleyebilirim.",
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
    # SidarAgent.__init__ senkrondur; asyncio.run() gerekmez.
    global _agent
    _agent = SidarAgent(cfg)

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