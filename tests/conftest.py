import base64
import hashlib
import hmac
import importlib.util
import json
import sys
import types

import pytest


if importlib.util.find_spec("jwt") is None:
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

    _httpx.HTTPError = HTTPError
    _httpx.RequestError = RequestError
    _httpx.TimeoutException = TimeoutException
    _httpx.Response = Response
    _httpx.AsyncClient = AsyncClient
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

    _bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = _bs4

# pytest-asyncio >= 0.21+ ile session kapsamlı event loop pytest.ini üzerinden
# `asyncio_default_fixture_loop_scope = session` ayarıyla sağlanır.
# Özel event_loop fixture override'ı artık gerekli değildir ve deprecated'dır.

@pytest.fixture(autouse=True)
def _restore_critical_modules_between_tests():
    """Bazı testlerin sys.modules üzerinde bıraktığı stub modülleri test sonunda geri al."""
    module_names = (
        "config",
        "managers",
        "managers.system_health",
        "core",
        "core.llm_metrics",
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
