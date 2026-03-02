"""
Sidar Project - Web Arayüzü Sunucusu
FastAPI + SSE (Server-Sent Events) ile asenkron (async) akış destekli chat arayüzü.

Başlatmak için:
    python web_server.py
    python web_server.py --host 0.0.0.0 --port 7860
"""

import argparse
import asyncio
import json
import logging
import re
import subprocess
import time
from collections import defaultdict
from pathlib import Path

try:
    import anyio
    _ANYIO_CLOSED = anyio.ClosedResourceError
except ImportError:  # anyio FastAPI/uvicorn bağımlılığıdır; normalde hep kurulu gelir
    _ANYIO_CLOSED = None

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse, Response

from config import Config
from agent.sidar_agent import SidarAgent

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  UYGULAMA BAŞLATMA
# ─────────────────────────────────────────────

cfg = Config()
_agent: SidarAgent | None = None
# Event loop başlamadan önce asyncio.Lock() oluşturmak Python <3.10'da
# DeprecationWarning üretir. Lazy başlatma ile bu risk tamamen ortadan kalkar.
_agent_lock: asyncio.Lock | None = None


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

app = FastAPI(title="Sidar Web UI", docs_url=None, redoc_url=None)

# CORS: Yalnızca localhost'tan gelen isteklere izin ver (port cfg.WEB_PORT'tan okunur)
_ALLOWED_ORIGINS = [
    f"http://localhost:{cfg.WEB_PORT}",
    f"http://127.0.0.1:{cfg.WEB_PORT}",
    f"http://0.0.0.0:{cfg.WEB_PORT}",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

# ─────────────────────────────────────────────
#  RATE LIMITING (basit in-memory)
# Kapsam:
#   /chat                                   → 20 istek/60 sn/IP  (LLM çağrısı, ağır)
#   POST + DELETE                           → 60 istek/60 sn/IP  (mutasyon endpoint'leri)
#   GET /git-info /git-branches             → 30 istek/60 sn/IP  (dosya sistemi / git I/O)
#       /files /file-content                →  (GET I/O kapsamında)
# ─────────────────────────────────────────────

_rate_data: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT           = 20   # /chat — LLM çağrısı başına limit
_RATE_LIMIT_MUTATIONS = 60   # Diğer POST/DELETE — mutasyon endpoint'leri
_RATE_LIMIT_GET_IO    = 30   # GET I/O endpoint'leri (git, dosya, vb.)
_RATE_WINDOW          = 60   # saniye cinsinden pencere (tüm limitler için)
_RATE_GET_IO_PATHS    = frozenset(["/git-info", "/git-branches", "/files", "/file-content"])
_rate_lock: asyncio.Lock | None = None  # _agent_lock ile tutarlı: lazy init

_start_time = time.monotonic()  # Sunucu başlangıç zamanı (/metrics için)
_LOCAL_PROJECTS_ROOT = Path.home()
_active_local_project: Path | None = None


async def _is_rate_limited(key: str, limit: int = _RATE_LIMIT) -> bool:
    """
    Atomik kontrol+yaz: asyncio.Lock ile TOCTOU yarış koşulunu önler.
    key: IP adresi veya 'IP:namespace' formatında bileşik anahtar
    limit: pencere boyunca izin verilen maksimum istek sayısı
    """
    global _rate_lock
    if _rate_lock is None:
        _rate_lock = asyncio.Lock()  # event loop başladıktan sonra oluştur
    async with _rate_lock:
        now = time.monotonic()
        window_start = now - _RATE_WINDOW
        # Pencere dışındakileri temizle
        _rate_data[key] = [t for t in _rate_data[key] if t > window_start]
        if len(_rate_data[key]) >= limit:
            return True
        _rate_data[key].append(now)
        return False


def _get_client_ip(request: Request) -> str:
    """
    İstemci IP adresini güvenle çeker.

    Proxy/reverse-proxy ortamlarında X-Forwarded-For ve X-Real-IP başlıklarına
    bakar; yoksa doğrudan bağlantı IP'sini kullanır.

    Güvenlik notu: X-Forwarded-For başlığındaki yalnızca ilk (en soldan) IP
    kullanılır — bu, istemcinin orijinal IP'sidir. Saldırganın başlığı
    manipüle etme riskine karşı proxy zincirinin yalnızca güvenilen ağdan
    geldiğinden emin olunmalıdır.
    """
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        # "client, proxy1, proxy2" formatından yalnızca client IP'sini al
        first_ip = xff.split(",")[0].strip()
        if first_ip:
            return first_ip
    xri = request.headers.get("X-Real-IP", "")
    if xri:
        return xri.strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """
    IP tabanlı rate limiting middleware.
    X-Forwarded-For / X-Real-IP başlıklarını proxy farkındalıklı okur.
    """
    client_ip = _get_client_ip(request)

    if request.url.path == "/chat":
        # /chat: LLM çağrısı — sıkı limit (20 req/60s)
        if await _is_rate_limited(client_ip, _RATE_LIMIT):
            return JSONResponse(
                {"error": "Çok fazla istek. Lütfen bir dakika bekleyin."},
                status_code=429,
            )
    elif request.method in ("POST", "DELETE"):
        # Mutasyon endpoint'leri (oturum oluştur/sil, repo değiştir vb.)
        # Gevşek limit (60 req/60s) — XSS/spam koruması
        if await _is_rate_limited(f"{client_ip}:mut", _RATE_LIMIT_MUTATIONS):
            return JSONResponse(
                {"error": "Çok fazla işlem isteği. Lütfen bir dakika bekleyin."},
                status_code=429,
            )
    elif request.method == "GET" and request.url.path in _RATE_GET_IO_PATHS:
        # Dosya sistemi / Git I/O endpoint'leri — orta limit (30 req/60s)
        if await _is_rate_limited(f"{client_ip}:get", _RATE_LIMIT_GET_IO):
            return JSONResponse(
                {"error": "Çok fazla sorgu isteği. Lütfen bir dakika bekleyin."},
                status_code=429,
            )

    return await call_next(request)

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


@app.post("/chat")
async def chat(request: Request):
    """
    Kullanıcı mesajını SSE akışı olarak işler.
    Agent artık asenkron (AsyncIterator) olduğu için doğrudan await edilebilir.
    (Eski Thread/Queue yapısı tamamen kaldırılmıştır).
    """
    body = await request.json()
    user_message = body.get("message", "").strip()

    if not user_message:
        return JSONResponse({"error": "Mesaj boş olamaz."}, status_code=400)

    async def sse_generator():
        """Asenkron SSE akışı: Ajan yanıtlarını dinler ve yayar."""
        try:
            agent = await get_agent()

            # Eğer aktif bir başlık yoksa ve bu ilk mesajsa, basit bir başlık üretelim
            if len(agent.memory) == 0:
                title = user_message[:30] + "..." if len(user_message) > 30 else user_message
                agent.memory.update_title(title)

            # Ajanın asenkron stream yanıtını bekle ve akıt
            _TOOL_SENTINEL = re.compile(r'^\x00TOOL:(.+)\x00$')
            async for chunk in agent.respond(user_message):
                try:
                    disconnected = await request.is_disconnected()
                except Exception:
                    disconnected = True  # Bağlantı durumu alınamazsa güvenli tarafta kal
                if disconnected:
                    logger.info("İstemci bağlantıyı kesti, stream durduruluyor.")
                    return
                m = _TOOL_SENTINEL.match(chunk)
                if m:
                    yield f"data: {json.dumps({'tool_call': m.group(1)})}\n\n"
                else:
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"

            # Akış başarıyla tamamlandı
            yield f"data: {json.dumps({'done': True})}\n\n"

        except asyncio.CancelledError:
            # İstemci bağlantıyı kesti (ESC / AbortController) — beklenen durum.
            logger.info("Stream iptal edildi (CancelledError): istemci bağlantıyı kesti.")
        except Exception as exc:
            # anyio.ClosedResourceError: kapalı sokete yazmaya çalışıldı — beklenen durum.
            if _ANYIO_CLOSED and isinstance(exc, _ANYIO_CLOSED):
                logger.info("Stream iptal edildi (ClosedResourceError): istemci bağlantıyı kesti.")
                return
            logger.exception("Agent respond hatası: %s", exc)
            try:
                err_chunk = json.dumps({"chunk": f"\n[Sistem Hatası] {exc}"})
                yield f"data: {err_chunk}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception:
                pass  # Hata yanıtı gönderilirken de bağlantı kopabilir

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # Nginx proxy'de buffering'i kapat
        },
    )


@app.get("/status")
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
    })

@app.get("/metrics")
async def metrics(request: Request):
    """
    Temel operasyonel metrikler.
    - Varsayılan: JSON formatı (her istemci için çalışır).
    - 'Accept: text/plain' başlığı + prometheus_client kurulu ise Prometheus formatı döner.
    """
    agent = await get_agent()
    uptime_s  = int(time.monotonic() - _start_time)
    rag_docs  = len(agent.docs._index)
    sessions  = agent.memory.get_all_sessions()
    rl_total  = sum(len(v) for v in _rate_data.values())

    payload = {
        "version":                       agent.VERSION,
        "uptime_seconds":                uptime_s,
        "sessions_total":                len(sessions),
        "active_session_turns":          len(agent.memory),
        "rag_documents":                 rag_docs,
        "rate_limit_buckets":            len(_rate_data),
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

@app.get("/sessions")
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


def _default_local_projects_root() -> Path:
    """Yerel proje kök klasörünü döndürür (varsayılan: /home/niluf, yoksa home)."""
    preferred = Path("/home/niluf")
    return preferred if preferred.exists() and preferred.is_dir() else _LOCAL_PROJECTS_ROOT


def _safe_project_path(raw_path: str, root: Path) -> Path:
    """İstemciden gelen yolu kök altında güvenli bir dizine çözümler."""
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (root / candidate)
    resolved = candidate.resolve()
    resolved.relative_to(root.resolve())
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError("Geçersiz proje yolu")
    return resolved


@app.get("/local-projects")
async def local_projects():
    """Yerel proje klasörlerini listeler."""
    root = _default_local_projects_root().resolve()
    if not root.exists() or not root.is_dir():
        return JSONResponse({"success": False, "error": f"Kök klasör bulunamadı: {root}", "projects": []}, status_code=404)

    projects = []
    for item in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_dir() or item.name.startswith('.'):
            continue
        has_git = (item / ".git").exists()
        projects.append({
            "name": item.name,
            "path": str(item),
            "is_git": has_git,
        })

    active = str(_active_local_project) if _active_local_project else ""
    return JSONResponse({
        "success": True,
        "root": str(root),
        "active_project": active,
        "projects": projects,
    })


@app.post("/set-local-project")
async def set_local_project(request: Request):
    """Aktif yerel proje klasörünü değiştirir."""
    global _active_local_project

    body = await request.json()
    project_path = body.get("path", "").strip()
    if not project_path:
        return JSONResponse({"success": False, "error": "Proje yolu boş."}, status_code=400)

    root = _default_local_projects_root().resolve()
    try:
        resolved = _safe_project_path(project_path, root)
    except Exception:
        return JSONResponse({"success": False, "error": "Geçersiz proje yolu."}, status_code=400)

    _active_local_project = resolved
    return JSONResponse({"success": True, "path": str(resolved), "name": resolved.name})

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

    # GitHub URL'sini "owner/repo" biçimine çevir
    repo = ""
    if remote:
        # https://github.com/owner/repo.git  →  owner/repo
        # git@github.com:owner/repo.git      →  owner/repo
        repo = remote.removesuffix(".git")
        repo = repo.split("github.com/")[-1].split("github.com:")[-1]

    return JSONResponse({"branch": branch, "repo": repo or "sidar_project"})


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


@app.post("/clear")
async def clear():
    """Aktif konuşma belleğini temizle."""
    agent = await get_agent()
    agent.memory.clear()
    return JSONResponse({"result": True})


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
        "--provider", choices=["ollama", "gemini"],
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
    print(f"\n  ╔══════════════════════════════════════╗")
    print(f"  ║  SİDAR Web Arayüzü — v{_agent.VERSION}          ║")
    print(f"  ║  http://{display_host}:{args.port:<27}║")
    print(f"  ╚══════════════════════════════════════╝\n")

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log,
    )


if __name__ == "__main__":
    main() 