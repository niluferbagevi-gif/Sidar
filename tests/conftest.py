import base64
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Çevrede bozuk native kütüphaneler varsa (cffi/cryptography/jwt) testlerin
# tamamen çökmemesi için stub'ları erken enjekte et.
# ──────────────────────────────────────────────────────────────────────────────
def _stub_broken_native_deps() -> None:
    """cffi/cryptography/jwt gibi binary uyumsuz paketleri stub ile değiştirir."""
    # _cffi_backend stub
    if "_cffi_backend" not in sys.modules:
        _cffi_backend = types.ModuleType("_cffi_backend")
        sys.modules["_cffi_backend"] = _cffi_backend

    # cffi stub
    if "cffi" not in sys.modules:
        _cffi = types.ModuleType("cffi")
        _cffi.FFI = type("FFI", (), {})
        sys.modules["cffi"] = _cffi

    # cryptography stub — sadece jwt'nin beklediği arayüz
    for mod_name in (
        "cryptography",
        "cryptography.hazmat",
        "cryptography.hazmat.primitives",
        "cryptography.hazmat.primitives.asymmetric",
        "cryptography.hazmat.primitives.asymmetric.ec",
        "cryptography.hazmat._oid",
        "cryptography.hazmat.bindings",
        "cryptography.hazmat.bindings._rust",
        "cryptography.exceptions",
        "cryptography.fernet",
    ):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)


_stub_broken_native_deps()

if "jwt" not in sys.modules:
    _jwt = types.ModuleType("jwt")

    class PyJWTError(Exception):
        pass

    def _b64encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def _b64decode(data: str) -> bytes:
        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode((data + padding).encode("ascii"))

    def encode(payload, secret, algorithm="HS256"):
        if algorithm != "HS256":
            raise PyJWTError("Unsupported algorithm")
        header = {"alg": algorithm, "typ": "JWT"}
        header_part = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_part = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        signature = hmac.new(str(secret).encode("utf-8"), signing_input, hashlib.sha256).digest()
        return f"{header_part}.{payload_part}.{_b64encode(signature)}"

    def decode(token, secret, algorithms):
        if "HS256" not in algorithms:
            raise PyJWTError("Unsupported algorithm")
        try:
            header_part, payload_part, sig_part = token.split(".", 2)
        except ValueError as exc:
            raise PyJWTError("Malformed token") from exc
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        expected = hmac.new(str(secret).encode("utf-8"), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64encode(expected), sig_part):
            raise PyJWTError("Signature verification failed")
        return json.loads(_b64decode(payload_part).decode("utf-8"))

    _jwt.PyJWTError = PyJWTError
    _jwt.encode = encode
    _jwt.decode = decode
    sys.modules["jwt"] = _jwt



if importlib.util.find_spec("httpx") is None:
    _httpx = types.ModuleType("httpx")

    class HTTPError(Exception):
        pass

    class RequestError(HTTPError):
        pass

    class TimeoutException(RequestError):
        pass

    class Response:
        def __init__(self, status_code=200, text="", json_data=None):
            self.status_code = status_code
            self.text = text
            self._json_data = json_data if json_data is not None else {}

        def json(self):
            return self._json_data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise HTTPError(self.text or f"HTTP {self.status_code}")

    class AsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *_args, **_kwargs):
            return Response()

        async def post(self, *_args, **_kwargs):
            return Response()

        async def put(self, *_args, **_kwargs):
            return Response()

        async def delete(self, *_args, **_kwargs):
            return Response()

    class ConnectError(RequestError):
        pass

    class Request:
        def __init__(self, method="GET", url=""):
            self.method = method
            self.url = url

    class HTTPStatusError(HTTPError):
        def __init__(self, message="", request=None, response=None):
            super().__init__(message)
            self.request = request
            self.response = response

    class Timeout:
        def __init__(self, timeout=None, connect=None, read=None, write=None, pool=None):
            self.timeout = timeout
            self.connect = connect

    _httpx.HTTPError = HTTPError
    _httpx.RequestError = RequestError
    _httpx.TimeoutException = TimeoutException
    _httpx.ConnectError = ConnectError
    _httpx.HTTPStatusError = HTTPStatusError
    _httpx.Request = Request
    _httpx.Response = Response
    _httpx.AsyncClient = AsyncClient
    _httpx.Timeout = Timeout
    sys.modules["httpx"] = _httpx


if importlib.util.find_spec("bs4") is None:
    _bs4 = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, markup="", parser=None):
            self.markup = markup
            self.parser = parser

        def get_text(self, *args, **kwargs):
            return str(self.markup)

        def find_all(self, *args, **kwargs):
            return []

        def __call__(self, *args, **kwargs):
            return []

        def decompose(self):
            pass

    _bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = _bs4

# managers paketini erken yükle; conftest save/restore döngüsünde kaybolmasını önle.
try:
    import managers as _managers_pkg  # noqa: F401
except Exception:
    pass

# pytest-asyncio >= 0.21+ ile session kapsamlı event loop pytest.ini üzerinden
# `asyncio_default_fixture_loop_scope = session` ayarıyla sağlanır.
# Özel event_loop fixture override'ı artık gerekli değildir ve deprecated'dır.

@pytest.fixture(autouse=True)
def _restore_critical_modules_between_tests():
    """Bazı testlerin sys.modules üzerinde bıraktığı stub modülleri test sonunda geri al."""
    module_names = (
        "config",
        "managers",
        "managers.browser_manager",
        "managers.system_health",
        "managers.code_manager",
        "managers.github_manager",
        "managers.jira_manager",
        "managers.security",
        "managers.slack_manager",
        "managers.social_media_manager",
        "managers.teams_manager",
        "managers.todo_manager",
        "managers.web_search",
        "managers.package_info",
        "managers.youtube_manager",
        "core",
        "core.llm_metrics",
        "core.llm_client",
        "core.memory",
        "core.rag",
        "core.entity_memory",
        "core.ci_remediation",
        "core.db",
        "httpx",
        "fastapi",
        "starlette",
        "agent",
        "agent.core",
        "agent.core.contracts",
        "agent.core.memory_hub",
        "agent.core.registry",
        "agent.core.event_stream",
        "agent.core.supervisor",
        "agent.registry",
        "agent.definitions",
        "agent.swarm",
        "agent.base_agent",
        "agent.roles",
        "agent.roles.coder_agent",
        "agent.roles.researcher_agent",
        "agent.roles.reviewer_agent",
        "agent.roles.poyraz_agent",
        "agent.roles.qa_agent",
        "agent.roles.coverage_agent",
        "redis",
        "redis.asyncio",
        "redis.exceptions",
        "core.agent_metrics",
        "pydantic",
    )
    saved = {name: sys.modules.get(name) for name in module_names}
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


@pytest.fixture(autouse=True)
def _cleanup_logging_handlers():
    """Teste sonra logging handler'larını kapat (ResourceWarning önlemek için)."""
    yield
    import logging
    import gc
    # Tüm handler'ları kapat
    for handler in logging.root.handlers[:]:
        try:
            handler.close()
            logging.root.removeHandler(handler)
        except Exception:
            pass
    # Tüm logger'ları temizle
    for logger_name in list(logging.Logger.manager.loggerDict):
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers[:]:
            try:
                handler.close()
                logger.removeHandler(handler)
            except Exception:
                pass
    # Garbage collection'ı force et
    gc.collect()


@pytest.fixture
def sqlite_test_db_url(tmp_path) -> str:
    """core.db testleri için geçici SQLite veritabanı URL'i."""
    db_file = Path(tmp_path) / "sidar_test.db"
    return f"sqlite+aiosqlite:///{db_file}"
