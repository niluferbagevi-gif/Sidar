import asyncio
import json
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest
import core.llm_client as llm_real

from agent.core.contracts import DelegationRequest
from agent.roles.coder_agent import CoderAgent
from core.llm_client import AnthropicClient, LLMClient, _ensure_json_text
from core.llm_metrics import LLMMetricsCollector
from tests.test_web_server_runtime import _FakeRequest, _FakeUploadFile, _load_web_server, _make_agent


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


def test_web_server_git_run_failure_and_auth_success_paths(monkeypatch):
    mod = _load_web_server()

    def _check_output(cmd, cwd=None, stderr=None):
        if cmd[:3] == ["git", "remote", "get-url"]:
            return b""
        if cmd[:2] == ["git", "symbolic-ref"]:
            raise subprocess.CalledProcessError(1, cmd, output=b"fatal")
        if cmd[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return b"feat/x"
        raise subprocess.CalledProcessError(1, cmd, output=b"err")

    monkeypatch.setattr(mod.subprocess, "check_output", _check_output)
    gi = asyncio.run(mod.git_info())
    assert gi.content["repo"] == "sidar_project"
    assert gi.content["default_branch"] == "main"

    # _git_run except Exception yolu
    monkeypatch.setattr(mod.subprocess, "check_output", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert mod._git_run(["git", "status"], cwd=".") == ""

    # auth/login success yolu: create_auth_token döndürüp response üretir
    agent, _ = _make_agent()

    async def _auth_user(**_kwargs):
        return SimpleNamespace(id="u9", username="bob", role="user")

    async def _mk_token(_uid):
        return SimpleNamespace(token="tok-9")

    agent.memory.db.authenticate_user = _auth_user
    agent.memory.db.create_auth_token = _mk_token
    mod.get_agent = lambda: asyncio.sleep(0, result=agent)

    login = asyncio.run(mod.login_user({"username": "bob", "password": "secret"}))
    assert login.content["access_token"] == "tok-9"

    me = asyncio.run(mod.auth_me(_FakeRequest(), user=SimpleNamespace(id="u9", username="bob", role="user")))
    assert me.content["id"] == "u9"


def test_llm_client_stream_and_error_branches(monkeypatch):
    llm_mod = llm_real
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=10, USE_GPU=False)
    ollama = LLMClient("ollama", cfg)._client

    # OllamaClient.chat içindeki `except LLMAPIError: raise` satırı
    async def _raise_api_error(*_args, **_kwargs):
        raise llm_mod.LLMAPIError("ollama", "boom", retryable=False)

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _raise_api_error)
    with pytest.raises(llm_mod.LLMAPIError):
        asyncio.run(ollama.chat([{"role": "user", "content": "x"}], stream=False, json_mode=False))

    # _stream_response içinde boş satır/bozuk JSON paketlerini atlayıp geçerli chunk üretir
    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b"\n"
            yield b"not-json\n"
            yield b'{"message": {"content": "ok"}}\n'

    class _StreamCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *_args):
            return None

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return _StreamCtx()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    out = asyncio.run(_collect(ollama._stream_response("http://x", {"stream": True}, timeout=llm_mod.httpx.Timeout(10))))
    assert out == ["ok"]

    # Anthropic stream except Exception dalı


def test_llm_client_factory_openai_gemini_and_wrapper_stream(monkeypatch):
    llm_mod = llm_real

    class _FakeGemini:
        def __init__(self, _cfg):
            self.called = False

        async def _stream_gemini_generator(self, _response_stream):
            self.called = True
            yield "g-1"
            yield "g-2"

    class _FakeOpenAI:
        def __init__(self, _cfg):
            self.created = True

    monkeypatch.setattr(llm_mod, "GeminiClient", _FakeGemini)
    monkeypatch.setattr(llm_mod, "OpenAIClient", _FakeOpenAI)

    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=10)
    gemini_fac = llm_mod.LLMClient("gemini", cfg)
    openai_fac = llm_mod.LLMClient("openai", cfg)

    assert isinstance(gemini_fac._client, _FakeGemini)
    assert isinstance(openai_fac._client, _FakeOpenAI)
    assert asyncio.run(gemini_fac.is_ollama_available()) is False

    chunks = asyncio.run(_collect(gemini_fac._stream_gemini_generator(object())))
    assert chunks == ["g-1", "g-2"]


def test_web_server_admin_file_git_and_repo_branches(monkeypatch, tmp_path):
    mod = _load_web_server()
    agent, _ = _make_agent()

    async def _admin_stats():
        return {"total_users": 5}

    agent.memory.db.get_admin_stats = _admin_stats
    agent.github.repo_name = "owner-x/repo-y"
    agent.github.list_repos = lambda owner, limit=200: (True, [{"full_name": f"{owner}/repo-y"}])
    mod.get_agent = lambda: asyncio.sleep(0, result=agent)

    admin_ok = asyncio.run(mod.admin_stats(_user=SimpleNamespace(role="admin", username="root")))
    assert admin_ok.status_code == 200
    assert admin_ok.content["total_users"] == 5

    with pytest.raises(mod.HTTPException) as exc:
        mod._require_admin_user(SimpleNamespace(role="user", username="alice"))
    assert exc.value.status_code == 403

    root = tmp_path / "project"
    root.mkdir()
    (root / ".hidden").write_text("x", encoding="utf-8")
    (root / "visible.txt").write_text("ok", encoding="utf-8")
    (root / "archive.zip").write_bytes(b"PK")
    (root / "subdir").mkdir()
    monkeypatch.setattr(mod, "__file__", str(root / "web_server.py"))

    listed = asyncio.run(mod.list_project_files(""))
    names = [item["name"] for item in listed.content["items"]]
    assert "visible.txt" in names
    assert ".hidden" not in names

    dir_err = asyncio.run(mod.file_content("subdir"))
    assert dir_err.status_code == 400
    bad_ext = asyncio.run(mod.file_content("archive.zip"))
    assert bad_ext.status_code == 415

    monkeypatch.setattr(mod.subprocess, "check_output", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert mod._git_run(["git", "status"], cwd=".") == ""

    def _git_run(cmd, _cwd, stderr=None):
        if "branch --format" in " ".join(cmd):
            return "\nmain\n feature/x \n"
        if "rev-parse --abbrev-ref HEAD" in " ".join(cmd):
            return "feature/x"
        return ""

    monkeypatch.setattr(mod, "_git_run", _git_run)
    branches = asyncio.run(mod.git_branches())
    assert branches.content["branches"] == ["main", "feature/x"]
    assert branches.content["current"] == "feature/x"

    repos = asyncio.run(mod.github_repos(owner="", q=""))
    assert repos.status_code == 200
    assert repos.content["owner"] == "owner-x"
    class _MsgAPI:
        def stream(self, **_kwargs):
            class _Ctx:
                async def __aenter__(self):
                    raise RuntimeError("net down")

                async def __aexit__(self, *_args):
                    return None

            return _Ctx()

    class _AsyncAnthropic:
        def __init__(self, **_kwargs):
            self.messages = _MsgAPI()

    sys.modules["anthropic"] = types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic)
    anth_cfg = SimpleNamespace(ANTHROPIC_API_KEY="k", ANTHROPIC_TIMEOUT=15, ANTHROPIC_MODEL="claude", OLLAMA_URL="http://x/api", OLLAMA_TIMEOUT=10)
    client = AnthropicClient(anth_cfg)
    chunks = asyncio.run(_collect(client._stream_anthropic(_AsyncAnthropic(), "claude", [{"role": "user", "content": "hi"}], "", 0.2, True)))
    payload = json.loads(chunks[0])
    assert "Anthropic akış hatası" in payload["argument"]


def test_llmclient_factory_fallbacks_and_stream_bridge(monkeypatch):
    cfg = SimpleNamespace(
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_TIMEOUT=33,
        GEMINI_API_KEY="key",
        GEMINI_MODEL="gemini-2.0-flash",
    )

    ollama_factory = LLMClient("ollama", cfg)
    assert ollama_factory._ollama_base_url == "http://localhost:11434"
    assert ollama_factory._build_ollama_timeout().connect == 10.0

    non_ollama = LLMClient("gemini", cfg)
    assert asyncio.run(non_ollama.list_ollama_models()) == []
    assert asyncio.run(non_ollama.is_ollama_available()) is False

    seen = {"created": 0}

    def _fake_init(self, config):
        seen["created"] += 1
        self.config = config

    async def _fake_stream(self, _response_stream):
        yield "chunk"

    monkeypatch.setattr(llm_real.GeminiClient, "__init__", _fake_init)
    monkeypatch.setattr(llm_real.GeminiClient, "_stream_gemini_generator", _fake_stream)

    openai_factory = LLMClient("openai", cfg)
    assert asyncio.run(_collect(openai_factory._stream_gemini_generator(object()))) == ["chunk"]
    assert seen["created"] == 1


def test_web_server_security_and_error_guard_paths(monkeypatch):
    mod = _load_web_server()
    agent, _ = _make_agent()
    mod.get_agent = lambda: asyncio.sleep(0, result=agent)

    with pytest.raises(mod.HTTPException) as exc:
        mod._get_request_user(_FakeRequest(path="/secure"))
    assert exc.value.status_code == 401

    async def _rate_limited(*_args, **_kwargs):
        return True

    monkeypatch.setattr(mod, "_redis_is_rate_limited", _rate_limited)

    async def _next(_request):
        return mod.JSONResponse({"ok": True}, status_code=200)

    post_resp = asyncio.run(mod.rate_limit_middleware(_FakeRequest(method="POST", path="/set-level"), _next))
    get_resp = asyncio.run(mod.rate_limit_middleware(_FakeRequest(method="GET", path="/git-info"), _next))
    assert post_resp.status_code == 429
    assert get_resp.status_code == 429

    assert asyncio.run(mod.serve_vendor("../escape.js")).status_code == 403
    assert asyncio.run(mod.serve_vendor("missing.js")).status_code == 404

    def _checkout_error(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "git checkout", output=b"checkout failed")

    monkeypatch.setattr(mod.subprocess, "check_output", _checkout_error)
    set_branch_resp = asyncio.run(mod.set_branch(_FakeRequest(method="POST", path="/set-branch", json_body={"branch": "feature/x"})))
    assert set_branch_resp.status_code == 400

    agent.github.list_repos = lambda **_kwargs: (False, "Hata")
    assert asyncio.run(mod.github_repos()).status_code == 400

    agent.github.is_available = lambda: False
    assert asyncio.run(mod.github_prs()).status_code == 503
    assert asyncio.run(mod.github_pr_detail(1)).status_code == 503

    rag_add_resp = asyncio.run(mod.rag_add_file(_FakeRequest(method="POST", path="/rag/add-file", json_body={"path": "../../../etc/passwd"})))
    assert rag_add_resp.status_code == 403

    up = _FakeUploadFile("doc.txt", b"hello")
    monkeypatch.setattr(mod.shutil, "rmtree", lambda _p: (_ for _ in ()).throw(RuntimeError("rm failed")))
    upload_resp = asyncio.run(mod.upload_rag_file(up))
    assert upload_resp.status_code == 200
