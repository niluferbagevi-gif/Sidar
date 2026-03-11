import asyncio
from types import SimpleNamespace

import pytest

from tests.test_web_server_runtime import _FakeRequest, _load_web_server


def _restore_real_core_package():
    import sys

    core_mod = sys.modules.get("core")
    if core_mod is not None and getattr(core_mod, "__path__", None) == []:
        sys.modules.pop("core", None)
    sys.modules.pop("core.llm_client", None)
    sys.modules.pop("core.llm_metrics", None)



def test_web_server_bind_usage_sink_handles_runtimeerror_and_db_exception(monkeypatch):
    mod = _load_web_server()

    class _Collector:
        def __init__(self):
            self.sink = None

        def set_usage_sink(self, sink):
            self.sink = sink

    collector = _Collector()
    monkeypatch.setattr(mod, "get_llm_metrics_collector", lambda: collector)

    class _DB:
        async def record_provider_usage_daily(self, **_kwargs):
            raise RuntimeError("db down")

    agent = SimpleNamespace(memory=SimpleNamespace(db=_DB()))

    # İlk bind
    mod._bind_llm_usage_sink(agent)
    assert callable(collector.sink)

    # running loop yok path'i
    monkeypatch.setattr(mod.asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
    collector.sink(SimpleNamespace(user_id="u1", provider="openai", total_tokens=12))

    # already-bound early return path
    mod._bind_llm_usage_sink(agent)


def test_web_server_auth_error_paths_raise_http_exceptions(monkeypatch):
    mod = _load_web_server()

    class _DB:
        async def register_user(self, **_kwargs):
            raise RuntimeError("duplicate")

        async def create_auth_token(self, _uid):
            return SimpleNamespace(token="t")

        async def authenticate_user(self, **_kwargs):
            return None

    fake_agent = SimpleNamespace(memory=SimpleNamespace(db=_DB()))

    async def _fake_get_agent():
        return fake_agent

    monkeypatch.setattr(mod, "get_agent", _fake_get_agent)

    with pytest.raises(Exception) as reg_exc:
        asyncio.run(mod.register_user({"username": "alice", "password": "123456"}))
    assert getattr(reg_exc.value, "status_code", None) == 409

    with pytest.raises(Exception) as login_exc:
        asyncio.run(mod.login_user({"username": "alice", "password": "bad"}))
    assert getattr(login_exc.value, "status_code", None) == 401


def test_web_server_metrics_paths_with_async_sessions(monkeypatch):
    mod = _load_web_server()

    class _Memory:
        def __len__(self):
            return 3

        async def aget_all_sessions(self):
            return [1, 2]

    fake_agent = SimpleNamespace(
        VERSION="x",
        cfg=SimpleNamespace(AI_PROVIDER="ollama", USE_GPU=False),
        docs=SimpleNamespace(doc_count=7),
        memory=_Memory(),
    )

    async def _fake_get_agent():
        return fake_agent

    monkeypatch.setattr(mod, "get_agent", _fake_get_agent)

    resp = asyncio.run(mod.metrics(_FakeRequest(headers={})))
    assert getattr(resp, "status_code", 200) == 200

    llm_resp = asyncio.run(mod.llm_prometheus_metrics())
    assert "text/plain" in (getattr(llm_resp, "media_type", "") or "")


def test_llm_client_retry_non_retryable_wraps_exception():
    _restore_real_core_package()
    import importlib
    import core.llm_client as llm_mod

    llm_mod = importlib.reload(llm_mod)

    async def _op():
        raise ValueError("boom")

    cfg = SimpleNamespace(LLM_MAX_RETRIES=1, LLM_RETRY_BASE_DELAY=0.01, LLM_RETRY_MAX_DELAY=0.02)
    with pytest.raises(llm_mod.LLMAPIError) as exc:
        asyncio.run(
            llm_mod._retry_with_backoff(
                "openai",
                _op,
                config=cfg,
                retry_hint="request failed",
            )
        )
    assert "request failed" in str(exc.value)
    assert exc.value.retryable is False


def test_anthropic_chat_system_only_defaults_to_user_message(monkeypatch):
    _restore_real_core_package()
    import importlib
    import core.llm_client as llm_mod

    llm_mod = importlib.reload(llm_mod)

    class _Response:
        usage = SimpleNamespace(input_tokens=1, output_tokens=2)
        content = [SimpleNamespace(text="ok")]

    class _Messages:
        async def create(self, **_kwargs):
            return _Response()

    class _AsyncAnthropic:
        def __init__(self, **_kwargs):
            self.messages = _Messages()

    import types
    import sys

    anth_mod = types.ModuleType("anthropic")
    anth_mod.AsyncAnthropic = _AsyncAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", anth_mod)

    cfg = SimpleNamespace(ANTHROPIC_API_KEY="k", ANTHROPIC_TIMEOUT=30, ANTHROPIC_MODEL="m", ENABLE_TRACING=False)
    client = llm_mod.AnthropicClient(cfg)
    out = asyncio.run(client.chat([{"role": "system", "content": ""}], stream=False, json_mode=False))
    assert out == "ok"
