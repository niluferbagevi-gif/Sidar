"""Pytest için minimal ve yeniden kullanılabilir çekirdek fixture seti."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import sqlite3
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


if importlib.util.find_spec("jwt") is None:
    jwt_stub = types.ModuleType("jwt")

    class PyJWTError(Exception):
        """PyJWT uyumlu temel hata tipi."""

    def _b64encode(data: bytes) -> str:
        import base64

        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def _b64decode(data: str) -> bytes:
        import base64

        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode((data + padding).encode("ascii"))

    def encode(payload: dict[str, Any], secret: str, algorithm: str = "HS256") -> str:
        if algorithm != "HS256":
            raise PyJWTError("Unsupported algorithm")
        header = {"alg": algorithm, "typ": "JWT"}
        header_part = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_part = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        signature = hmac.new(str(secret).encode("utf-8"), signing_input, hashlib.sha256).digest()
        return f"{header_part}.{payload_part}.{_b64encode(signature)}"

    def decode(token: str, secret: str, algorithms: list[str]) -> dict[str, Any]:
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

    jwt_stub.PyJWTError = PyJWTError
    jwt_stub.encode = encode
    jwt_stub.decode = decode
    sys.modules["jwt"] = jwt_stub


def pytest_addoption(parser: pytest.Parser) -> None:
    """pytest-asyncio yoksa bile proje ini seçeneğini tanımlar."""
    parser.addini("asyncio_default_fixture_loop_scope", "pytest-asyncio compatibility shim", default="function")
    parser.addini("asyncio_mode", "pytest-asyncio compatibility shim", default="auto")

@dataclass
class MockLLMClient:
    """Deterministic davranan basit LLM istemcisi mock'u."""

    default_response: str = "mock-response"
    queued_responses: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        if self.queued_responses:
            return self.queued_responses.pop(0)
        return self.default_response

    def queue(self, *responses: str) -> None:
        self.queued_responses.extend(responses)


@pytest.fixture
def db_session() -> sqlite3.Connection:
    """İzole in-memory SQLite bağlantısı sağlar."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def llm_mock_client() -> MockLLMClient:
    """Testlerde ortak kullanılacak LLM mock istemcisi."""
    return MockLLMClient()


@pytest.fixture
def test_config(tmp_path: Path) -> dict[str, Any]:
    """Sık kullanılan test konfigürasyon değerleri."""
    return {
        "environment": "test",
        "workspace_dir": str(tmp_path),
        "debug": False,
        "llm_timeout_seconds": 10,
    }
