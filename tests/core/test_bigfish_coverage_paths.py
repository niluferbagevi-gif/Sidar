from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("jwt") is None:
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.encode = lambda payload, *_args, **_kwargs: f"token:{payload.get('sub', '')}"
    fake_jwt.decode = lambda *_args, **_kwargs: {"sub": "stub", "username": "stub"}
    sys.modules["jwt"] = fake_jwt

if importlib.util.find_spec("httpx") is None:
    fake_httpx = types.ModuleType("httpx")

    class Request:
        def __init__(self, method: str, url: str) -> None:
            self.method = method
            self.url = url

    class Response:
        def __init__(self, status_code: int, request=None) -> None:
            self.status_code = status_code
            self.request = request

    class HTTPStatusError(Exception):
        def __init__(self, message: str, request=None, response=None) -> None:
            super().__init__(message)
            self.request = request
            self.response = response

    class TimeoutException(Exception):
        pass

    class ConnectError(Exception):
        pass

    fake_httpx.Request = Request
    fake_httpx.Response = Response
    fake_httpx.HTTPStatusError = HTTPStatusError
    fake_httpx.TimeoutException = TimeoutException
    fake_httpx.ConnectError = ConnectError
    sys.modules["httpx"] = fake_httpx

from core.db import Database
import core.llm_client as llm_client
from core.rag import DocumentStore, embed_texts_for_semantic_cache


def test_retry_with_backoff_wraps_429_as_retryable_api_error() -> None:
    cfg = SimpleNamespace(LLM_MAX_RETRIES=0, LLM_RETRY_BASE_DELAY=0.01, LLM_RETRY_MAX_DELAY=0.05)

    async def _rate_limited():
        req = llm_client.httpx.Request("GET", "https://example.com")
        resp = llm_client.httpx.Response(429, request=req)
        raise llm_client.httpx.HTTPStatusError("rate limited", request=req, response=resp)

    with pytest.raises(llm_client.LLMAPIError) as err:
        asyncio.run(llm_client._retry_with_backoff("openai", _rate_limited, config=cfg, retry_hint="chat"))

    assert err.value.status_code == 429
    assert err.value.retryable is True


def test_embed_texts_for_semantic_cache_returns_empty_when_encoder_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenSentenceTransformer:
        def __init__(self, _model_name: str) -> None:
            raise RuntimeError("model init failed")

    fake_sentence_transformers = types.ModuleType("sentence_transformers")
    fake_sentence_transformers.SentenceTransformer = _BrokenSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_sentence_transformers)

    vectors = embed_texts_for_semantic_cache(["coverage"], cfg=SimpleNamespace(PGVECTOR_EMBEDDING_MODEL="test-model"))
    assert vectors == []


def test_validate_url_safe_blocks_private_ip_and_accepts_public_host() -> None:
    with pytest.raises(ValueError):
        DocumentStore._validate_url_safe("http://127.0.0.1/private")

    DocumentStore._validate_url_safe("https://example.com/docs")


def test_replace_session_messages_filters_empty_content_and_defaults_role(tmp_path) -> None:
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'coverage.db'}",
        BASE_DIR=tmp_path,
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        JWT_SECRET_KEY="secret",
        JWT_ALGORITHM="HS256",
    )

    async def _scenario() -> tuple[int, list]:
        db = Database(cfg)
        await db.connect()
        await db.init_schema()

        user = await db.ensure_user("coverage-user")
        session = await db.create_session(user.id, "coverage oturumu")

        replaced = await db.replace_session_messages(
            session.id,
            [
                {"role": "", "content": "ilk içerik"},
                {"role": "user", "content": "   "},
                {"role": "user", "content": "ikinci içerik"},
            ],
        )
        messages = await db.get_session_messages(session.id)
        await db.close()
        return replaced, messages

    replaced, messages = asyncio.run(_scenario())

    assert replaced == 2
    assert [m.role for m in messages] == ["assistant", "user"]
    assert [m.content for m in messages] == ["ilk içerik", "ikinci içerik"]
