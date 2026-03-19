import asyncio
import json
import sys
import types
from types import SimpleNamespace
from agent.roles.coder_agent import CoderAgent
from tests.test_llm_client_runtime import _collect, _load_llm_client_module
from tests.test_web_server_runtime import _FakeRequest, _load_web_server


def test_coder_agent_tool_wrappers_and_fallback_paths(monkeypatch):
    agent = CoderAgent()

    async def _fake_to_thread(fn, *args):
        return fn(*args)

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    agent.code.read_file = lambda arg: (True, f"read:{arg}")
    agent.code.write_file = lambda path, content: (True, f"write:{path}:{content}")
    agent.code.patch_file = lambda path, target, repl: (True, f"patch:{path}:{target}:{repl}")
    agent.code.execute_code = lambda arg: (True, f"exec:{arg}")
    agent.code.list_directory = lambda arg: (True, f"list:{arg}")
    agent.code.glob_search = lambda pattern, base: (True, f"glob:{pattern}:{base}")
    agent.code.grep_files = lambda p, path, fg, c: (True, f"grep:{p}:{path}:{fg}:{c}")
    agent.code.audit_project = lambda arg: f"audit:{arg}"
    agent.todo.scan_project_todos = lambda directory, _x: f"todo:{directory}"

    assert asyncio.run(agent._tool_read_file("a.py")) == "read:a.py"
    assert asyncio.run(agent._tool_write_file("a.py|x")) == "write:a.py:x"
    assert asyncio.run(agent._tool_patch_file("a.py|x|y")) == "patch:a.py:x:y"
    assert asyncio.run(agent._tool_execute_code("print(1)")) == "exec:print(1)"
    assert asyncio.run(agent._tool_list_directory("")) == "list:."
    assert asyncio.run(agent._tool_glob_search("*.py|||src")) == "glob:*.py:src"
    assert asyncio.run(agent._tool_grep_search("pat|||src|||*.py|||3")) == "grep:pat:src:*.py:3"
    assert asyncio.run(agent._tool_audit_project("")) == "audit:."
    assert asyncio.run(agent._tool_scan_project_todos("")) == f"todo:{agent.cfg.BASE_DIR}"
    assert asyncio.run(agent.run_task("unknown command")) == "[LEGACY_FALLBACK] coder_unhandled task=unknown command"


def test_llm_retry_helpers_and_factory_fallbacks():
    llm_mod = _load_llm_client_module()

    llm_mod.httpx.TimeoutException = TimeoutError
    llm_mod.httpx.ConnectError = ConnectionError
    retryable, status = llm_mod._is_retryable_exception(asyncio.TimeoutError("timeout"))
    assert retryable is True
    assert status is None

    wrapped = llm_mod._ensure_json_text("not-json", "ProviderX")
    payload = json.loads(wrapped)
    assert payload["tool"] == "final_answer"
    assert "JSON dışı" in payload["thought"]

    cfg = SimpleNamespace(
        OPENAI_API_KEY="k",
        OPENAI_MODEL="gpt",
        OPENAI_TIMEOUT=20,
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_TIMEOUT=20,
        GEMINI_API_KEY="",
    )
    factory = llm_mod.LLMClient("openai", cfg)
    assert asyncio.run(factory.list_ollama_models()) == []
    assert asyncio.run(factory.is_ollama_available()) is False



def test_ollama_stream_and_openai_error_branches(monkeypatch):
    llm_mod = _load_llm_client_module()

    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=10)
    ollama = llm_mod.OllamaClient(cfg)

    class _BrokenClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            raise RuntimeError("down")

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _BrokenClient)
    out = asyncio.run(_collect(ollama._stream_response("u", {}, timeout=llm_mod.httpx.Timeout(10))))
    assert "Akış kesildi" in json.loads(out[0])["argument"]

    openai_cfg = SimpleNamespace(OPENAI_API_KEY="k", OPENAI_MODEL="gpt-4o-mini", OPENAI_TIMEOUT=20)
    openai = llm_mod.OpenAIClient(openai_cfg)
    metrics = []

    async def _raise_api_error(*_args, **_kwargs):
        raise llm_mod.LLMAPIError("openai", "boom", status_code=503, retryable=True)

    monkeypatch.setattr(llm_mod, "_retry_with_backoff", _raise_api_error)
    monkeypatch.setattr(llm_mod, "_record_llm_metric", lambda **kwargs: metrics.append(kwargs))

    try:
        asyncio.run(openai.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True))
    except llm_mod.LLMAPIError:
        pass

    assert metrics and metrics[-1]["success"] is False



def test_web_server_auth_and_main_arg_overrides(monkeypatch):
    patched_modules = [
        "fastapi",
        "fastapi.middleware.cors",
        "fastapi.responses",
        "fastapi.staticfiles",
        "redis.asyncio",
        "uvicorn",
        "config",
        "agent",
        "agent.core",
        "core",
        "core.llm_client",
        "core.llm_metrics",
        "agent.sidar_agent",
        "agent.core.event_stream",
    ]
    previous = {name: sys.modules.get(name) for name in patched_modules}
    try:
        mod = _load_web_server()

        no_auth = _FakeRequest(path="/sessions", headers={})
        no_auth_resp = asyncio.run(mod.basic_auth_middleware(no_auth, lambda req: req))
        assert no_auth_resp.status_code == 401

        empty_bearer = _FakeRequest(path="/sessions", headers={"Authorization": "Bearer   "})
        empty_bearer_resp = asyncio.run(mod.basic_auth_middleware(empty_bearer, lambda req: req))
        assert empty_bearer_resp.status_code == 401

        started = {}

        class _FakeAgent:
            VERSION = "1.2.3"

            def __init__(self, cfg):
                started["level"] = cfg.ACCESS_LEVEL
                started["provider"] = cfg.AI_PROVIDER

        monkeypatch.setattr(mod, "SidarAgent", _FakeAgent)
        monkeypatch.setattr(mod.uvicorn, "run", lambda _app, host, port, log_level: started.update({"host": host, "port": port, "log": log_level}))
        monkeypatch.setattr(sys, "argv", ["web_server.py", "--level", "full", "--provider", "openai", "--host", "0.0.0.0", "--port", "9999"])

        mod.main()

        assert started["level"] == "full"
        assert started["provider"] == "openai"
        assert started["host"] == "0.0.0.0"
        assert started["port"] == 9999
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value

from agent.core.contracts import DelegationRequest, is_delegation_request, TaskResult
from agent.core.supervisor import SupervisorAgent
from agent.roles.researcher_agent import ResearcherAgent
from agent.roles.reviewer_agent import ReviewerAgent


def test_reviewer_and_researcher_wrappers_and_routing(monkeypatch):
    reviewer = ReviewerAgent()

    async def _fake_to_thread(fn, *args):
        return fn(*args)

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    reviewer.github.get_repo_info = lambda: (True, "repo")
    reviewer.github.list_pull_requests = lambda state, lim: (True, f"prs:{state}:{lim}")
    reviewer.github.get_pull_request_diff = lambda number: (True, f"diff:{number}")
    reviewer.github.list_issues = lambda state, lim: (False, f"issues:{state}:{lim}")

    assert asyncio.run(reviewer._tool_repo_info("")) == "repo"
    assert asyncio.run(reviewer._tool_list_prs("")) == "prs:open:20"
    assert asyncio.run(reviewer._tool_pr_diff("7")) == "diff:7"
    assert asyncio.run(reviewer._tool_list_issues("closed")) == "[HATA] issues:closed:20"

    reviewer.tools["repo_info"] = lambda _arg: asyncio.sleep(0, result="rinfo")
    reviewer.tools["list_prs"] = lambda arg: asyncio.sleep(0, result=f"lprs:{arg}")
    reviewer.tools["pr_diff"] = lambda arg: asyncio.sleep(0, result=f"pdiff:{arg}")
    reviewer.tools["list_issues"] = lambda arg: asyncio.sleep(0, result=f"lissues:{arg}")

    assert asyncio.run(reviewer.run_task("repo_info")) == "rinfo"
    assert asyncio.run(reviewer.run_task("list_prs|closed")) == "lprs:closed"
    assert asyncio.run(reviewer.run_task("pr_diff|3")) == "pdiff:3"
    assert asyncio.run(reviewer.run_task("list_issues")) == "lissues:open"

    researcher = ResearcherAgent()

    async def _ok(tag, val):
        return True, f"{tag}:{val}"

    researcher.web.search = lambda arg: _ok("web", arg)
    researcher.web.fetch_url = lambda arg: _ok("fetch", arg)
    researcher.web.search_docs = lambda lib, topic: _ok("docs", f"{lib}/{topic}")
    researcher.docs.search = lambda query, *_args: (True, f"rag:{query}")

    assert asyncio.run(researcher._tool_web_search("python")) == "web:python"
    assert asyncio.run(researcher._tool_fetch_url("https://example.com")) == "fetch:https://example.com"
    assert asyncio.run(researcher._tool_search_docs("fastapi websockets")) == "docs:fastapi/websockets"
    assert asyncio.run(researcher._tool_docs_search("limits")) == "rag:limits"



def test_supervisor_delegate_routes_and_retry_cap(monkeypatch):
    sup = object.__new__(SupervisorAgent)
    sup.MAX_QA_RETRIES = 1
    sup.events = SimpleNamespace(publish=lambda *_a, **_k: asyncio.sleep(0))
    sup.memory_hub = SimpleNamespace(add_global=lambda *_a, **_k: None, add_role_note=lambda *_a, **_k: None)

    route_calls = []

    async def _route(req, **_kwargs):
        route_calls.append(req)
        return TaskResult(task_id="r", status="done", summary="p2p-ok")

    async def _delegate(receiver, goal, intent, parent_task_id=None, sender="supervisor"):
        if receiver in ("researcher", "reviewer") and parent_task_id is None and sender == "supervisor":
            req = DelegationRequest(task_id="p2p", reply_to=receiver, target_agent="coder", payload="fix")
            return TaskResult(task_id=f"t-{receiver}", status="done", summary=req)
        if receiver == "coder":
            return TaskResult(task_id="c1", status="done", summary="kod özeti")
        # review after code should force retry stop
        return TaskResult(task_id="rv", status="done", summary="[TEST:FAIL] regresyon")

    sup._delegate = _delegate
    sup._route_p2p = _route

    assert asyncio.run(sup.run_task("web araştır")) == "p2p-ok"
    assert asyncio.run(sup.run_task("pull request incele")) == "p2p-ok"

    out = asyncio.run(sup.run_task("kodu güncelle"))
    assert "Maksimum QA retry limiti aşıldı" in out
    assert route_calls



def test_web_server_sink_and_prewarm_negative_paths(monkeypatch):
    patched_modules = [
        "fastapi",
        "fastapi.middleware.cors",
        "fastapi.responses",
        "fastapi.staticfiles",
        "redis.asyncio",
        "uvicorn",
        "config",
        "agent",
        "agent.core",
        "core",
        "core.llm_client",
        "core.llm_metrics",
        "agent.sidar_agent",
        "agent.core.event_stream",
    ]
    previous = {name: sys.modules.get(name) for name in patched_modules}
    try:
        mod = _load_web_server()

        class _Collector:
            def __init__(self):
                self._sidar_usage_sink_bound = False
                self.sink = None

            def set_usage_sink(self, sink):
                self.sink = sink

        collector = _Collector()
        monkeypatch.setattr(mod, "get_llm_metrics_collector", lambda: collector)

        class _DB:
            async def record_provider_usage_daily(self, **_kwargs):
                raise RuntimeError("db down")

        agent = SimpleNamespace(memory=SimpleNamespace(db=_DB()))
        mod._bind_llm_usage_sink(agent)
        assert collector.sink is not None

        monkeypatch.setattr(asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
        collector.sink(SimpleNamespace(user_id="u1", provider="p", total_tokens=3))

        async def _agent_no_rag():
            return SimpleNamespace(rag=None)

        monkeypatch.setattr(mod, "get_agent", _agent_no_rag)
        asyncio.run(mod._prewarm_rag_embeddings())

        async def _agent_no_chroma():
            return SimpleNamespace(rag=SimpleNamespace(_chroma_available=False))

        monkeypatch.setattr(mod, "get_agent", _agent_no_chroma)
        asyncio.run(mod._prewarm_rag_embeddings())

        class _Rag:
            _chroma_available = True

            def _init_chroma(self):
                raise RuntimeError("boom")

        async def _agent_broken():
            return SimpleNamespace(rag=_Rag())

        monkeypatch.setattr(mod, "get_agent", _agent_broken)
        asyncio.run(mod._prewarm_rag_embeddings())
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value

import builtins

from agent.core.event_stream import AgentEventBus
from core.llm_metrics import LLMMetricsCollector


def test_coder_and_reviewer_run_task_routing_paths(monkeypatch):
    coder = CoderAgent()
    coder.tools["write_file"] = lambda arg: asyncio.sleep(0, result=f"wf:{arg}")
    assert asyncio.run(coder.run_task("write_file|a.py|print(1)")) == "wf:a.py|print(1)"
    assert "REWORK_REQUIRED" in asyncio.run(coder.run_task("qa_feedback|decision=reject"))

    reviewer_req = asyncio.run(coder.run_task("request_review|diff body"))
    assert is_delegation_request(reviewer_req)
    assert reviewer_req.target_agent == "reviewer"

    reviewer = ReviewerAgent()
    result = asyncio.run(reviewer._build_dynamic_test_content("please add_two helper"))
    assert "def test_add_two" in result
    assert reviewer._extract_changed_paths("./a.py ./a.py ../x.py /abs/y.py docs/readme.md") == ["a.py", "x.py", "abs/y.py", "docs/readme.md"]
    cmds = reviewer._build_regression_commands("tests/test_a.py tests/test_a.py")
    assert any(c.startswith("pytest -q tests/test_a.py") for c in cmds)

    monkeypatch.setattr(reviewer, "_run_dynamic_tests", lambda _ctx: asyncio.sleep(0, result="[TEST:OK] dyn"))
    monkeypatch.setattr(reviewer, "_build_regression_commands", lambda _ctx: ["pytest -q"])
    reviewer.tools["run_tests"] = lambda _arg: asyncio.sleep(0, result="[TEST:FAIL] regression")
    monkeypatch.setattr(reviewer, "delegate_to", lambda *_a, **_k: "delegated")
    assert asyncio.run(reviewer.run_task("review this now")) == "delegated"



def test_anthropic_paths_and_retryable_readtimeout(monkeypatch):
    llm_mod = _load_llm_client_module()
    llm_mod.httpx.TimeoutException = TimeoutError
    llm_mod.httpx.ConnectError = ConnectionError
    llm_mod.httpx.ReadTimeout = TimeoutError
    ok, _ = llm_mod._is_retryable_exception(llm_mod.httpx.ReadTimeout("t"))
    assert ok is True

    cfg = SimpleNamespace(ANTHROPIC_API_KEY="", ANTHROPIC_MODEL="claude", ANTHROPIC_TIMEOUT=20)
    fac = llm_mod.LLMClient("anthropic", cfg)
    no_key = asyncio.run(fac.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True))
    assert "ANTHROPIC_API_KEY" in no_key

    original_import = builtins.__import__

    def _blocked(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "anthropic":
            raise ImportError("missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    cfg2 = SimpleNamespace(ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="claude", ANTHROPIC_TIMEOUT=20)
    out = asyncio.run(llm_mod.LLMClient("anthropic", cfg2).chat([{"role": "user", "content": "x"}], stream=False, json_mode=True))
    assert "anthropic paketi" in out

    monkeypatch.setattr(builtins, "__import__", original_import)

    class _Event:
        def __init__(self, kind, text=""):
            self.type = "content_block_delta"
            self.delta = SimpleNamespace(type=kind, text=text)

    class _Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def __aiter__(self):
            async def _gen():
                yield _Event("meta", "")
                yield _Event("text_delta", "parca")
            return _gen()

    class _Messages:
        def stream(self, **_kwargs):
            return _Stream()

    client = SimpleNamespace(messages=_Messages())
    anthropic_client = llm_mod.AnthropicClient(cfg2)
    chunks = asyncio.run(_collect(anthropic_client._stream_anthropic(client, "claude", [{"role": "user", "content": "h"}], "", 0.2, True)))
    assert chunks == ["parca"]



def test_llm_metrics_sink_and_event_bus_queuefull_cleanup():
    m = LLMMetricsCollector(max_events=5)

    def _sink(_evt):
        return None

    m.set_usage_sink(_sink)
    m.record(provider="openai", model="gpt-4o", latency_ms=10, prompt_tokens=10, completion_tokens=5)
    snap = m.snapshot()
    assert snap["totals"]["calls"] == 1
    assert snap["totals"]["cost_usd"] >= 0.0

    bus = AgentEventBus()
    sid, _q = bus.subscribe(maxsize=1)
    asyncio.run(bus.publish("t", "m1"))
    asyncio.run(bus.publish("t", "m2"))
    assert sid in bus._subscribers



def test_db_postgres_pool_error_and_main_preflight_warnings(monkeypatch):
    import importlib

    sys.modules.setdefault("dotenv", SimpleNamespace(load_dotenv=lambda *_a, **_k: None))
    from core.db import Database

    import config as config_mod
    config_mod = importlib.reload(config_mod)
    import main as launcher_main
    launcher_main = importlib.reload(launcher_main)

    class _AsyncPG:
        @staticmethod
        async def create_pool(**_kwargs):
            raise TimeoutError("db timeout")

    sys.modules["asyncpg"] = _AsyncPG
    db = Database(SimpleNamespace(DATABASE_URL="postgresql://user:pass@localhost/db", DB_POOL_SIZE=1, DB_SCHEMA_VERSION_TABLE="schema_versions", DB_SCHEMA_TARGET_VERSION=1))
    try:
        asyncio.run(db.connect())
        assert False, "expected timeout"
    except TimeoutError:
        pass
    finally:
        sys.modules.pop("asyncpg", None)

    if not hasattr(launcher_main.cfg, "OPENAI_API_KEY"):
        launcher_main.cfg.OPENAI_API_KEY = ""
    if not hasattr(launcher_main.cfg, "ANTHROPIC_API_KEY"):
        launcher_main.cfg.ANTHROPIC_API_KEY = ""
    monkeypatch.setattr(launcher_main.cfg, "OPENAI_API_KEY", "")
    monkeypatch.setattr(launcher_main.cfg, "ANTHROPIC_API_KEY", "")
    launcher_main.preflight("openai")
    launcher_main.preflight("anthropic")



def test_web_server_rate_limit_fallback_and_invalid_webhook_signature(monkeypatch):
    patched_modules = [
        "fastapi",
        "fastapi.middleware.cors",
        "fastapi.responses",
        "fastapi.staticfiles",
        "redis.asyncio",
        "uvicorn",
        "config",
        "agent",
        "agent.core",
        "core",
        "core.llm_client",
        "core.llm_metrics",
        "agent.sidar_agent",
        "agent.core.event_stream",
    ]
    previous = {name: sys.modules.get(name) for name in patched_modules}
    try:
        mod = _load_web_server()
        monkeypatch.setattr(mod, "_get_redis", lambda: asyncio.sleep(0, result=None))
        monkeypatch.setattr(mod, "_local_is_rate_limited", lambda *_a, **_k: asyncio.sleep(0, result=True))
        assert asyncio.run(mod._redis_is_rate_limited("x", "k", 1, 60)) is True

        mod.cfg.GITHUB_WEBHOOK_SECRET = "sekret"
        req = _FakeRequest(body_bytes=b'{"x":1}')
        try:
            asyncio.run(mod.github_webhook(req, x_github_event="push", x_hub_signature_256="sha256=bad"))
            assert False, "expected auth exception"
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 401
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value

def test_researcher_docs_search_awaitable_result_path(monkeypatch):
    researcher = ResearcherAgent()

    async def _result():
        return True, "rag-await:limits"

    researcher.docs.search = lambda query, *_args: _result()

    async def _to_thread_passthrough(func, *args):
        return func(*args)

    monkeypatch.setattr(asyncio, "to_thread", _to_thread_passthrough)

    out = asyncio.run(researcher._tool_docs_search("limits"))
    assert out == "rag-await:limits"
