import asyncio
import json
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest

from agent.core.contracts import DelegationRequest
from agent.roles.coder_agent import CoderAgent
from core.llm_client import AnthropicClient, LLMClient, _ensure_json_text
from core.llm_metrics import LLMMetricsCollector
from tests.test_web_server_runtime import _FakeRequest, _load_web_server, _make_agent


async def _collect(aiter):
    out = []
    async for item in aiter:
        out.append(item)
    return out


def test_web_server_targeted_error_and_filter_branches(monkeypatch):
    mod = _load_web_server()
    agent, _ = _make_agent()

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    # redis: count==1 -> expire çağrısı
    calls = {"expire": 0, "fallback": 0}

    class _RedisOk:
        async def incr(self, _key):
            return 1

        async def expire(self, _key, _ttl):
            calls["expire"] += 1

    mod._get_redis = lambda: asyncio.sleep(0, result=_RedisOk())
    assert asyncio.run(mod._redis_is_rate_limited("ns", "k", 3, 60)) is False
    assert calls["expire"] == 1

    # redis error -> local fallback
    class _RedisFail:
        async def incr(self, _key):
            raise RuntimeError("redis down")

    async def _fallback(*_args, **_kwargs):
        calls["fallback"] += 1
        return True

    mod._get_redis = lambda: asyncio.sleep(0, result=_RedisFail())
    monkeypatch.setattr(mod, "_local_is_rate_limited", _fallback)
    assert asyncio.run(mod._redis_is_rate_limited("ns", "k", 3, 60)) is True
    assert calls["fallback"] == 1

    # git-info: remote boş
    def _git_run(cmd, _cwd, stderr=None):
        if "remote" in cmd:
            return ""
        if "symbolic-ref" in cmd:
            return "origin/main"
        return "feature/test"

    monkeypatch.setattr(mod, "_git_run", _git_run)
    git_info = asyncio.run(mod.git_info())
    assert git_info.content["repo"] == "sidar_project"

    # set-branch: checkout fail -> 400
    def _raise_checkout(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "git checkout", output=b"bad branch")

    monkeypatch.setattr(mod.subprocess, "check_output", _raise_checkout)
    bad_req = _FakeRequest(method="POST", path="/set-branch", json_body={"branch": "missing-branch"})
    set_branch = asyncio.run(mod.set_branch(bad_req))
    assert set_branch.status_code == 400

    # github-repos: q filtresi
    agent.github.repo_name = "owner/main-repo"
    agent.github.list_repos = lambda owner, limit=200: (
        True,
        [{"full_name": "owner/test-one"}, {"full_name": "owner/other"}],
    )
    filtered = asyncio.run(mod.github_repos(q="test"))
    assert filtered.content["repos"] == [{"full_name": "owner/test-one"}]

    # github-pr detail: bulunamadı
    agent.github.is_available = lambda: True
    agent.github.get_pull_request = lambda number: (False, f"PR {number} yok")
    pr_resp = asyncio.run(mod.github_pr_detail(9999))
    assert pr_resp.status_code == 404

    # rag add-file: path traversal
    traversal_req = _FakeRequest(method="POST", path="/rag/add-file", json_body={"path": "../../../etc/passwd"})
    rag_resp = asyncio.run(mod.rag_add_file(traversal_req))
    assert rag_resp.status_code == 403


def test_llm_client_missing_branches(monkeypatch):
    wrapped = _ensure_json_text("Bozuk JSON { ", "Anthropic")
    payload = json.loads(wrapped)
    assert payload["tool"] == "final_answer"

    class _Event:
        def __init__(self, type_, delta=None):
            self.type = type_
            self.delta = delta

    class _Delta:
        def __init__(self, type_, text=""):
            self.type = type_
            self.text = text

    class _Stream:
        def __aiter__(self):
            self._i = 0
            return self

        async def __anext__(self):
            self._i += 1
            if self._i == 1:
                return _Event("message_start")
            if self._i == 2:
                return _Event("content_block_delta", _Delta("text_delta", "parca-1"))
            raise StopAsyncIteration

    class _MsgAPI:
        async def create(self, **_kwargs):
            return None

        def stream(self, **_kwargs):
            class _Ctx:
                async def __aenter__(self_inner):
                    return _Stream()

                async def __aexit__(self_inner, *_args):
                    return None

            return _Ctx()

    class _AsyncAnthropic:
        def __init__(self, **_kwargs):
            self.messages = _MsgAPI()

    sys.modules["anthropic"] = types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic)
    cfg = SimpleNamespace(ANTHROPIC_API_KEY="k", ANTHROPIC_TIMEOUT=15, ANTHROPIC_MODEL="claude", OLLAMA_URL="http://x/api", OLLAMA_TIMEOUT=10)
    client = AnthropicClient(cfg)
    streamed = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=True, json_mode=False))
    assert asyncio.run(_collect(streamed)) == ["parca-1"]

    # provider ollama/gemini değilken uyumluluk fallback'leri
    fac = LLMClient("anthropic", cfg)
    assert asyncio.run(fac.list_ollama_models()) == []
    assert asyncio.run(fac.is_ollama_available()) is False

    class _EmptyStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    assert asyncio.run(_collect(fac._stream_gemini_generator(_EmptyStream()))) == []


def test_coder_agent_split_shortcuts_requested_literals():
    agent = CoderAgent()
    approved = asyncio.run(agent.run_task("qa_feedback|decision=approve"))
    review = asyncio.run(agent.run_task("request_review|kodu incele"))
    assert approved.startswith("[CODER:APPROVED]")
    assert isinstance(review, DelegationRequest)


def test_llm_metrics_record_ignores_runtime_error_when_no_running_loop(monkeypatch):
    collector = LLMMetricsCollector(max_events=8)

    class _AwaitableNoop:
        def __await__(self):
            if False:
                yield None
            return None

    collector.set_usage_sink(lambda _event: _AwaitableNoop())
    monkeypatch.setattr("core.llm_metrics.asyncio.get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))

    collector.record(provider="openai", model="gpt-4o-mini", latency_ms=5, prompt_tokens=1, completion_tokens=1)
    assert collector.snapshot()["totals"]["calls"] == 1


def test_web_server_lifespan_cancel_and_auth_paths(monkeypatch):
    mod = _load_web_server()

    # _app_lifespan finally içindeki CancelledError dalı
    class _FakeTask:
        def __init__(self):
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

        def __await__(self):
            raise asyncio.CancelledError
            yield  # pragma: no cover

    fake_task = _FakeTask()
    def _fake_create_task(coro):
        coro.close()
        return fake_task

    monkeypatch.setattr(mod.asyncio, "create_task", _fake_create_task)
    monkeypatch.setattr(mod, "_close_redis_client", lambda: asyncio.sleep(0))

    async def _drive_lifespan():
        async with mod._app_lifespan(mod.app):
            return None

    asyncio.run(_drive_lifespan())
    assert fake_task.cancelled is True

    # basic_auth_middleware: token doğrulanınca request.state.user set edilir
    agent, _ = _make_agent()

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent
    req = _FakeRequest(method="GET", path="/secure", headers={"Authorization": "Bearer token-1"})

    async def _next(request):
        return mod.JSONResponse({"ok": True, "uid": request.state.user.id}, status_code=200)

    resp = asyncio.run(mod.basic_auth_middleware(req, _next))
    assert resp.status_code == 200
    assert resp.content["uid"] == "u1"

    # register_user: geçersiz payload 400
    with pytest.raises(mod.HTTPException) as exc:
        asyncio.run(mod.register_user({"username": "ab", "password": "123"}))
    assert exc.value.status_code == 400

    # _require_admin_user: admin olmayan için 403
    with pytest.raises(mod.HTTPException) as exc2:
        mod._require_admin_user(SimpleNamespace(role="user", username="alice"))
    assert exc2.value.status_code == 403


def test_web_server_prewarm_exception_logged(monkeypatch):
    mod = _load_web_server()

    async def _get_agent():
        def _boom():
            raise RuntimeError("init chroma failed")

        return SimpleNamespace(rag=SimpleNamespace(_chroma_available=True, _init_chroma=_boom))

    seen = {"warn": 0}
    mod.get_agent = _get_agent
    monkeypatch.setattr(mod.logger, "warning", lambda *a, **k: seen.__setitem__("warn", seen["warn"] + 1))

    asyncio.run(mod._prewarm_rag_embeddings())
    assert seen["warn"] == 1
