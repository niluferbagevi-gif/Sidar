"""
Sidar Test Suite — Ortak Fixture ve Stub Tanımları
===================================================
Bu dosya tüm test modülleri tarafından otomatik olarak yüklenir.
Görevleri:
  • Opsiyonel / ağır bağımlılıklar (jwt, httpx, bs4) için hafif stub'lar sağlar.
  • Her test sonrası sys.modules ve logging durumunu temizler.
  • Session kapsamlı asyncio event loop'unu pyproject.toml üzerinden yönetir
    (asyncio_default_fixture_loop_scope = "session" — özel fixture gerekmez).
"""

from __future__ import annotations

import base64
import gc
import hashlib
import hmac
import importlib.util
import json
import logging
import sys
import types

import pytest


# ────────────────────────────────────────────────────────────────────────────
# OPSIYONEL BAĞIMLILIK STUB'LARI
# Gerçek paket kuruluysa stub enjekte edilmez; kurulu değilse minimal bir
# sahte modül sys.modules içine yerleştirilir — böylece import hataları
# test süitini çökertemez.
# ────────────────────────────────────────────────────────────────────────────


def _inject_jwt_stub() -> None:
    """PyJWT kurulu değilse HS256 desteğiyle minimal stub ekle."""
    if importlib.util.find_spec("jwt") is not None:
        return

    mod = types.ModuleType("jwt")

    class PyJWTError(Exception):
        pass

    def _b64enc(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def _b64dec(data: str) -> bytes:
        pad = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode((data + pad).encode("ascii"))

    def encode(payload: dict, secret: str, algorithm: str = "HS256") -> str:
        if algorithm != "HS256":
            raise PyJWTError("Unsupported algorithm")
        header = _b64enc(json.dumps({"alg": algorithm, "typ": "JWT"}, separators=(",", ":")).encode())
        body = _b64enc(json.dumps(payload, separators=(",", ":")).encode())
        sig_input = f"{header}.{body}".encode("ascii")
        sig = hmac.new(str(secret).encode(), sig_input, hashlib.sha256).digest()
        return f"{header}.{body}.{_b64enc(sig)}"

    def decode(token: str, secret: str, algorithms: list[str]) -> dict:
        if "HS256" not in algorithms:
            raise PyJWTError("Unsupported algorithm")
        try:
            header, body, sig = token.split(".", 2)
        except ValueError as exc:
            raise PyJWTError("Malformed token") from exc
        sig_input = f"{header}.{body}".encode("ascii")
        expected = hmac.new(str(secret).encode(), sig_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64enc(expected), sig):
            raise PyJWTError("Signature verification failed")
        return json.loads(_b64dec(body).decode())

    mod.PyJWTError = PyJWTError  # type: ignore[attr-defined]
    mod.encode = encode           # type: ignore[attr-defined]
    mod.decode = decode           # type: ignore[attr-defined]
    sys.modules["jwt"] = mod


def _inject_httpx_stub() -> None:
    """httpx kurulu değilse minimal async-uyumlu stub ekle."""
    if importlib.util.find_spec("httpx") is not None:
        return

    mod = types.ModuleType("httpx")

    class HTTPError(Exception):
        pass

    class RequestError(HTTPError):
        pass

    class TimeoutException(RequestError):
        pass

    class Response:
        def __init__(self, status_code: int = 200, text: str = "", json_data: dict | None = None):
            self.status_code = status_code
            self.text = text
            self._json = json_data or {}

        def json(self) -> dict:
            return self._json

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise HTTPError(self.text or f"HTTP {self.status_code}")

    class AsyncClient:
        async def __aenter__(self) -> "AsyncClient":
            return self

        async def __aexit__(self, *_: object) -> bool:
            return False

        async def get(self, *_: object, **__: object) -> Response:
            return Response()

        async def post(self, *_: object, **__: object) -> Response:
            return Response()

        async def put(self, *_: object, **__: object) -> Response:
            return Response()

        async def delete(self, *_: object, **__: object) -> Response:
            return Response()

    mod.HTTPError = HTTPError             # type: ignore[attr-defined]
    mod.RequestError = RequestError       # type: ignore[attr-defined]
    mod.TimeoutException = TimeoutException  # type: ignore[attr-defined]
    mod.Response = Response               # type: ignore[attr-defined]
    mod.AsyncClient = AsyncClient         # type: ignore[attr-defined]
    sys.modules["httpx"] = mod


def _inject_bs4_stub() -> None:
    """BeautifulSoup4 kurulu değilse metin döndüren minimal stub ekle."""
    if importlib.util.find_spec("bs4") is not None:
        return

    mod = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, markup: str = "", parser: str | None = None):
            self.markup = markup

        def get_text(self, *_: object, **__: object) -> str:
            return str(self.markup)

        def find_all(self, *_: object, **__: object) -> list:
            return []

    mod.BeautifulSoup = BeautifulSoup  # type: ignore[attr-defined]
    sys.modules["bs4"] = mod


# Stub'ları uygula (modül yüklendiği anda, import sırasına göre)
_inject_jwt_stub()
_inject_httpx_stub()
_inject_bs4_stub()


# ────────────────────────────────────────────────────────────────────────────
# ORTAK FIXTURE'LAR
# ────────────────────────────────────────────────────────────────────────────

# sys.modules içinde izlenecek kritik modüller; her test sonrası orijinal
# hâline döndürülür — testlerin birbirini kirletmesini önler.
_TRACKED_MODULES = (
    "config",
    "managers",
    "managers.system_health",
    "managers.security",
    "core",
    "core.llm_client",
    "core.llm_metrics",
    "core.memory",
    "core.rag",
    "httpx",
    "fastapi",
    "starlette",
)


@pytest.fixture(autouse=True)
def _restore_modules():
    """Her test öncesi modül anlık görüntüsünü al; sonrasında geri yükle."""
    snapshot = {name: sys.modules.get(name) for name in _TRACKED_MODULES}
    try:
        yield
    finally:
        for name, module in snapshot.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


@pytest.fixture(autouse=True)
def _cleanup_logging():
    """Her test sonrası logging handler'larını kapat → ResourceWarning önle."""
    yield
    for handler in logging.root.handlers[:]:
        with suppress_exception():
            handler.close()
            logging.root.removeHandler(handler)
    for name in list(logging.Logger.manager.loggerDict):
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            with suppress_exception():
                handler.close()
                logger.removeHandler(handler)
    gc.collect()


# ────────────────────────────────────────────────────────────────────────────
# YARDIMCI
# ────────────────────────────────────────────────────────────────────────────

from contextlib import contextmanager  # noqa: E402


@contextmanager
def suppress_exception():
    """Sessizce tüm exception'ları yut (cleanup bloklarında kullanım için)."""
    try:
        yield
    except Exception:
        pass
