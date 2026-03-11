import asyncio
import builtins
import json
import sys
import types
from types import SimpleNamespace

from agent.core.contracts import DelegationRequest
from agent.roles.coder_agent import CoderAgent
from agent.roles.researcher_agent import ResearcherAgent
from agent.roles.reviewer_agent import ReviewerAgent
from tests.test_llm_client_runtime import _collect, _load_llm_client_module


def test_coder_agent_run_task_feedback_and_tool_validation():
    agent = CoderAgent()

    reject = asyncio.run(agent.run_task("qa_feedback|decision=reject;reason=x"))
    approve = asyncio.run(agent.run_task("qa_feedback|decision=approve;reason=y"))
    review_req = asyncio.run(agent.run_task("request_review|diff body"))

    bad_write = asyncio.run(agent.call_tool("write_file", "only-path"))
    bad_patch = asyncio.run(agent.call_tool("patch_file", "a|b"))

    assert reject.startswith("[CODER:REWORK_REQUIRED]")
    assert approve.startswith("[CODER:APPROVED]")
    assert isinstance(review_req, DelegationRequest)
    assert review_req.target_agent == "reviewer"
    assert "Kullanım" in bad_write
    assert "Kullanım" in bad_patch


def test_reviewer_and_researcher_route_edge_paths(monkeypatch):
    reviewer = ReviewerAgent()

    usage = asyncio.run(reviewer.call_tool("pr_diff", "x"))
    assert "Kullanım" in usage

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

    async def _fake_subprocess(*_args, **_kwargs):
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _fake_subprocess)
    test_out = asyncio.run(reviewer.call_tool("run_tests", "pytest -q tests/test_reviewer_agent.py"))
    assert "[TEST:OK]" in test_out

    researcher = ResearcherAgent()

    async def _fetch(arg: str):
        return f"fetch:{arg}"

    async def _search_docs(arg: str):
        return f"docs:{arg}"

    async def _docs_search(arg: str):
        return f"rag:{arg}"

    researcher.tools["fetch_url"] = _fetch
    researcher.tools["search_docs"] = _search_docs
    researcher.tools["docs_search"] = _docs_search

    assert asyncio.run(researcher.run_task("")) == "[UYARI] Boş araştırma görevi verildi."
    assert asyncio.run(researcher.run_task("fetch_url|https://example.com")) == "fetch:https://example.com"
    assert asyncio.run(researcher.run_task("search_docs|fastapi ws")) == "docs:fastapi ws"
    assert asyncio.run(researcher.run_task("docs_search|token limit")) == "rag:token limit"


def test_anthropic_import_error_and_stream_paths(monkeypatch):
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(ANTHROPIC_API_KEY="k", ANTHROPIC_TIMEOUT=30, ANTHROPIC_MODEL="claude")
    client = llm_mod.AnthropicClient(cfg)

    original_import = builtins.__import__

    def _boom_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "anthropic":
            raise RuntimeError("pkg missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _boom_import)
    nonstream = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True))
    stream_iter = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=True, json_mode=True))
    stream_out = asyncio.run(_collect(stream_iter))

    assert "anthropic paketi" in json.loads(nonstream)["argument"]
    assert len(stream_out) == 1 and "anthropic paketi" in json.loads(stream_out[0])["argument"]


def test_anthropic_success_and_stream_exception(monkeypatch):
    llm_mod = _load_llm_client_module()

    class _Usage:
        input_tokens = 3
        output_tokens = 5

    class _Block:
        def __init__(self, text):
            self.text = text

    class _Resp:
        usage = _Usage()
        content = [_Block('{"tool":"final_answer","argument":"ok","thought":"t"}')]

    class _MsgApi:
        async def create(self, **_kwargs):
            return _Resp()

        def stream(self, **_kwargs):
            class _Ctx:
                async def __aenter__(self_inner):
                    raise RuntimeError("stream down")

                async def __aexit__(self_inner, *_args):
                    return None

            return _Ctx()

    class _AsyncAnthropic:
        def __init__(self, **_kwargs):
            self.messages = _MsgApi()

    sys.modules["anthropic"] = types.SimpleNamespace(AsyncAnthropic=_AsyncAnthropic)
    monkeypatch.setattr(llm_mod, "_retry_with_backoff", lambda *_a, **_k: _a[1]())

    cfg = SimpleNamespace(ANTHROPIC_API_KEY="k", ANTHROPIC_TIMEOUT=30, ANTHROPIC_MODEL="claude")
    client = llm_mod.AnthropicClient(cfg)

    out = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=False, json_mode=True))
    streamed = asyncio.run(_collect(client._stream_anthropic(_AsyncAnthropic(), "claude", [], "", 0.2, True)))

    assert json.loads(out)["argument"] == "ok"
    err = json.loads(streamed[0])
    assert "Anthropic akış hatası" in err["argument"]
