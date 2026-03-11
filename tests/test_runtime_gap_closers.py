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
