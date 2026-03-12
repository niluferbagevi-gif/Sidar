import asyncio
import io
import subprocess
import types
from unittest.mock import AsyncMock

import core.llm_client as llm
from tests.test_web_server_runtime import _FakeRequest, _FakeUploadFile, _load_web_server


class _Cfg:
    OLLAMA_URL = "http://localhost:11434/api"
    OLLAMA_TIMEOUT = 120


async def _collect(async_iterable):
    out = []
    async for item in async_iterable:
        out.append(item)
    return out


def test_llmclient_non_ollama_fallback_helpers(monkeypatch):
    client = llm.LLMClient("openai", _Cfg())

    assert client._ollama_base_url == "http://localhost:11434"
    assert asyncio.run(client.list_ollama_models()) == []
    assert asyncio.run(client.is_ollama_available()) is False

    async def _fake_stream(self, _response_stream):
        yield "fallback-chunk"

    monkeypatch.setattr(llm.GeminiClient, "_stream_gemini_generator", _fake_stream)
    assert asyncio.run(_collect(client._stream_gemini_generator(object()))) == ["fallback-chunk"]


def test_web_server_missing_error_and_guard_paths(monkeypatch):
    mod = _load_web_server()

    # _bind_llm_usage_sink: DB write exception should be swallowed
    collector = types.SimpleNamespace(_sidar_usage_sink_bound=False)

    def _set_usage_sink(sink):
        collector.sink = sink

    collector.set_usage_sink = _set_usage_sink
    monkeypatch.setattr(mod, "get_llm_metrics_collector", lambda: collector)

    agent_for_sink = types.SimpleNamespace(
        memory=types.SimpleNamespace(
            db=types.SimpleNamespace(
                record_provider_usage_daily=AsyncMock(side_effect=Exception("DB Error"))
            )
        )
    )
    mod._bind_llm_usage_sink(agent_for_sink)

    async def _trigger_sink():
        collector.sink(types.SimpleNamespace(user_id="u-1", provider="openai", total_tokens=7))
        await asyncio.sleep(0)

    asyncio.run(_trigger_sink())

    # _setup_tracing: enabled but dependency missing -> warning path
    mod.cfg.ENABLE_TRACING = True
    mod.OTLPSpanExporter = None
    mod._setup_tracing()

    # Shared fake agent for endpoints
    db = types.SimpleNamespace(
        register_user=AsyncMock(side_effect=Exception("duplicate")),
    )
    github = types.SimpleNamespace(
        is_available=lambda: False,
        get_pull_requests_detailed=lambda **_kwargs: (False, [], "API Error"),
        repo_name="owner/repo",
        set_repo=lambda repo: (True, f"repo={repo}"),
    )
    docs = types.SimpleNamespace(add_document_from_url=AsyncMock(return_value=(True, "ok")), add_document_from_file=lambda *a, **k: (True, "ok"))
    memory = types.SimpleNamespace(active_session_id="sess-1", db=db)
    fake_agent = types.SimpleNamespace(memory=memory, github=github, docs=docs)

    async def _get_agent():
        return fake_agent

    monkeypatch.setattr(mod, "get_agent", _get_agent)

    # /auth/register exception -> 409
    try:
        asyncio.run(mod.register_user({"username": "alice", "password": "123456"}))
        raise AssertionError("expected HTTPException")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409

    # /set-branch invalid regex -> 400
    bad_name = asyncio.run(mod.set_branch(_FakeRequest(method="POST", path="/set-branch", json_body={"branch": "dal adı!"})))
    assert bad_name.status_code == 400

    # /set-branch checkout failure -> 400
    async def _to_thread_fail(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(mod.asyncio, "to_thread", _to_thread_fail)

    def _raise_checkout(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["git", "checkout"], output=b"not found")

    monkeypatch.setattr(mod.subprocess, "check_output", _raise_checkout)
    checkout_fail = asyncio.run(mod.set_branch(_FakeRequest(method="POST", path="/set-branch", json_body={"branch": "missing-branch"})))
    assert checkout_fail.status_code == 400

    # /github-prs token missing -> 503
    gh_unavailable = asyncio.run(mod.github_prs())
    assert gh_unavailable.status_code == 503

    # /github-prs provider failure -> 500
    github.is_available = lambda: True
    gh_error = asyncio.run(mod.github_prs())
    assert gh_error.status_code == 500

    # /set-repo empty repo -> 400
    set_repo_empty = asyncio.run(mod.set_repo(_FakeRequest(method="POST", path="/set-repo", json_body={"repo": ""})))
    assert set_repo_empty.status_code == 400

    # /rag/add-url empty url -> 400
    add_url_empty = asyncio.run(mod.rag_add_url(_FakeRequest(method="POST", path="/rag/add-url", json_body={"url": "   "})))
    assert add_url_empty.status_code == 400

    # /api/rag/upload safe filename fallback -> uploaded_file.txt
    captured = {}

    def _add_document_from_file(path, *_args):
        captured["path"] = path
        return True, "ok"

    fake_agent.docs.add_document_from_file = _add_document_from_file
    up = _FakeUploadFile("&&&***", b"hello")
    uploaded = asyncio.run(mod.upload_rag_file(up))
    assert uploaded.status_code == 200
    assert captured["path"].endswith("uploaded_file.txt")
