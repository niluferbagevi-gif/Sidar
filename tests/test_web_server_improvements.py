import ast
from pathlib import Path


def _get_async_fn_src(module_path: str, fn_name: str) -> str:
    src = Path(module_path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == fn_name)
    return ast.get_source_segment(src, fn) or ""


def test_rag_search_uses_to_thread():
    fn_src = _get_async_fn_src("web_server.py", "rag_search")
    assert "await asyncio.to_thread(" in fn_src
    assert "agent.docs.search" in fn_src


def test_rate_limiter_uses_ttlcache_storage():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert "from cachetools import TTLCache" in src
    assert "_rate_data = TTLCache(maxsize=10000, ttl=cfg.RATE_LIMIT_WINDOW)" in src


def test_rate_limiter_uses_config_values():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert "_RATE_LIMIT           = cfg.RATE_LIMIT_CHAT" in src
    assert "_RATE_LIMIT_MUTATIONS = cfg.RATE_LIMIT_MUTATIONS" in src
    assert "_RATE_LIMIT_GET_IO    = cfg.RATE_LIMIT_GET_IO" in src
    assert "_RATE_WINDOW          = cfg.RATE_LIMIT_WINDOW" in src


def test_rate_limiter_get_io_uses_prefix_match_for_dynamic_routes():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert "is_io_route = any(request.url.path.startswith(p) for p in _RATE_GET_IO_PATHS)" in src
    assert '"/github-repos"' in src
    assert '"/sessions"' in src
    assert '"/rag/"' in src


def test_cors_allows_localhost_ports_via_regex():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert "allow_origin_regex=" in src
    assert "localhost|127\\.0\\.0\\.1|0\\.0\\.0\\.0" in src


def test_uvicorn_log_level_is_lowercased():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert "log_level=args.log.lower()" in src


def test_status_endpoint_includes_ollama_health_fields():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert "ollama_online = a.health.check_ollama()" in src
    assert "\"ollama_online\": ollama_online" in src
    assert "\"ollama_latency_ms\": ollama_latency_ms" in src

def test_web_server_has_basic_auth_middleware_backed_by_api_key():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert "import base64" in src
    assert "import secrets" in src
    assert "def basic_auth_middleware" in src
    assert "api_key = getattr(cfg, \"API_KEY\", \"\")" in src
    assert "secrets.compare_digest(password, api_key)" in src
    assert "WWW-Authenticate" in src
    assert 'Basic realm="Sidar Secure Web UI"' in src


def test_health_endpoint_uses_structured_summary_and_503_on_ollama_down():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert '@app.get("/health")' in src
    assert "health_data = agent.health.get_health_summary()" in src
    assert 'health_data["uptime_seconds"] = int(time.monotonic() - _start_time)' in src
    assert 'if agent.cfg.AI_PROVIDER == "ollama" and not health_data["ollama_online"]:' in src
    assert "return JSONResponse(health_data, status_code=503)" in src



def test_web_server_supports_rag_file_upload_endpoint():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert "import shutil" in src
    assert "import tempfile" in src
    assert "UploadFile, File" in src
    assert "@app.post(\"/api/rag/upload\")" in src
    assert "async def upload_rag_file(file: UploadFile = File(...))" in src
    assert "agent.docs.add_document_from_file" in src