from __future__ import annotations

import asyncio
import importlib.util
import sys
from types import SimpleNamespace
import types

import pytest

if importlib.util.find_spec("httpx") is None:
    fake_httpx = types.ModuleType("httpx")

    class _TimeoutException(Exception):
        pass

    class _ConnectError(Exception):
        pass

    class _ReadTimeout(_TimeoutException):
        pass

    class _HTTPStatusError(Exception):
        def __init__(self, message: str, request=None, response=None) -> None:
            super().__init__(message)
            self.request = request
            self.response = response

    class _Timeout:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

    class _AsyncClient:
        pass

    fake_httpx.TimeoutException = _TimeoutException
    fake_httpx.ConnectError = _ConnectError
    fake_httpx.ReadTimeout = _ReadTimeout
    fake_httpx.HTTPStatusError = _HTTPStatusError
    fake_httpx.Timeout = _Timeout
    fake_httpx.AsyncClient = _AsyncClient
    sys.modules["httpx"] = fake_httpx

if importlib.util.find_spec("pydantic") is None:
    fake_pydantic = types.ModuleType("pydantic")
    fake_pydantic.BaseModel = object
    fake_pydantic.Field = lambda *a, **k: None
    fake_pydantic.ValidationError = Exception
    sys.modules["pydantic"] = fake_pydantic

for _mod_name, _class_name in [
    ("managers.web_search", "WebSearchManager"),
    ("managers.package_info", "PackageInfoManager"),
    ("core.rag", "DocumentStore"),
    ("core.memory", "ConversationMemory"),
]:
    _mod = types.ModuleType(_mod_name)
    _mod.__dict__[_class_name] = type(_class_name, (), {})
    sys.modules.setdefault(_mod_name, _mod)

from agent.auto_handle import AutoHandle
from agent import sidar_agent
from core import llm_client


class _CodeManager:
    def __init__(self):
        self.security = SimpleNamespace(status_report=lambda: "secure")

    def read_file(self, _path):
        return True, "print('ok')"

    def validate_python_syntax(self, _content):
        return True, "python valid"

    def validate_json(self, _content):
        return True, "json valid"


class _GitHubManager:
    def is_available(self):
        return True

    def list_pull_requests(self, state: str, limit: int):
        return True, f"{state}:{limit}"

    def get_pull_request(self, number: int):
        return True, f"pr:{number}"

    def get_pr_files(self, number: int):
        return True, f"files:{number}"


class _WebManager:
    async def search(self, query: str):
        return True, f"search:{query}"

    async def fetch_url(self, url: str):
        return True, f"url:{url}"

    async def search_docs(self, lib: str, topic: str):
        return True, f"docs:{lib}:{topic}"

    async def search_stackoverflow(self, query: str):
        return True, f"so:{query}"


class _PackageManager:
    async def pypi_compare(self, package: str, version: str):
        return True, f"pypi-compare:{package}:{version}"

    async def pypi_info(self, package: str):
        return True, f"pypi:{package}"

    async def npm_info(self, package: str):
        return True, f"npm:{package}"

    async def github_releases(self, repo: str):
        return True, f"gh:{repo}"


class _DocsStore:
    def __init__(self):
        self.collection = None

    def search(self, query: str, _filters, mode: str):
        return True, f"{mode}:{query}"

    def list_documents(self):
        return "listed"

    async def add_document_from_url(self, url: str, title: str = ""):
        return True, f"added:{url}:{title}"


def _build_handler() -> AutoHandle:
    return AutoHandle(
        code=_CodeManager(),
        health=SimpleNamespace(full_report=lambda: "ok", optimize_gpu_memory=lambda: "gpu-ok"),
        github=_GitHubManager(),
        memory=SimpleNamespace(get_last_file=lambda: None, clear=lambda: None),
        web=_WebManager(),
        pkg=_PackageManager(),
        docs=_DocsStore(),
        cfg=SimpleNamespace(AUTO_HANDLE_TIMEOUT=1),
    )


def test_auto_handle_web_package_and_docs_paths() -> None:
    h = _build_handler()
    assert asyncio.run(h._try_web_search("internette ara python", "internette ara python")) == (True, "search:python")
    assert asyncio.run(h._try_fetch_url("url getir", "url getir https://example.com")) == (True, "url:https://example.com")
    assert asyncio.run(h._try_search_docs("docs ara fastapi routing", "docs ara fastapi routing")) == (True, "docs:fastapi:routing")
    assert asyncio.run(h._try_search_stackoverflow("stackoverflow: pytest async", "stackoverflow: pytest async")) == (True, "so:pytest async")
    assert asyncio.run(h._try_pypi("pypi httpx 0.27.0", "pypi httpx 0.27.0")) == (True, "pypi-compare:httpx:0.27.0")
    assert asyncio.run(h._try_npm("npm react", "npm react")) == (True, "npm:react")
    assert asyncio.run(h._try_gh_releases("github releases psf/requests", "github releases psf/requests")) == (
        True,
        "gh:psf/requests",
    )
    assert asyncio.run(h._try_docs_search("depoda ara mode:vector rag", "depoda ara mode:vector rag")) == (True, "vector:rag")
    assert asyncio.run(h._try_docs_add("belge ekle", 'belge ekle https://example.com "doküman"')) == (
        True,
        "added:https://example.com:doküman",
    )


def test_auto_handle_github_and_docs_listing_paths() -> None:
    h = _build_handler()
    assert h._try_github_list_prs("kapalı pr listele 5 pr", "kapalı pr listele 5 pr") == (True, "closed:5")
    assert asyncio.run(h._try_github_get_pr("pr #42 dosya", "pr #42 dosya")) == (True, "files:42")
    assert asyncio.run(h._try_github_get_pr("pull request 7", "pull request 7")) == (True, "pr:7")
    assert h._try_docs_list("belge deposu listele", "belge deposu listele") == (True, "listed")


def test_openai_chat_wraps_non_retryable_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(
        OPENAI_API_KEY="key",
        OPENAI_MODEL="gpt-test",
        OPENAI_TIMEOUT=10,
        ENABLE_TRACING=False,
        LLM_MAX_RETRIES=0,
    )
    client = llm_client.OpenAIClient(cfg)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    class _FakeHttpxClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        post = _boom

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda *a, **k: _FakeHttpxClient())
    with pytest.raises(llm_client.LLMAPIError) as exc:
        asyncio.run(client.chat(messages=[{"role": "user", "content": "selam"}], json_mode=False))

    assert exc.value.provider == "openai"
    assert exc.value.retryable is False


def test_gemini_and_anthropic_missing_keys_return_error_payload() -> None:
    gemini_cfg = SimpleNamespace(GEMINI_API_KEY="", GEMINI_MODEL="gemini-test", ENABLE_TRACING=False)
    anthropic_cfg = SimpleNamespace(ANTHROPIC_API_KEY="", ANTHROPIC_MODEL="claude-test", ENABLE_TRACING=False)

    gemini_text = asyncio.run(llm_client.GeminiClient(gemini_cfg).chat(
        messages=[{"role": "user", "content": "hi"}], stream=False
    ))
    anthropic_text = asyncio.run(llm_client.AnthropicClient(anthropic_cfg).chat(
        messages=[{"role": "user", "content": "hi"}], stream=False
    ))

    assert ("GEMINI_API_KEY" in str(gemini_text)) or ("google-generativeai" in str(gemini_text))
    assert "ANTHROPIC_API_KEY" in str(anthropic_text)


def test_anthropic_split_system_and_message_order() -> None:
    system, convo = llm_client.AnthropicClient._split_system_and_messages(
        [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
    )
    assert system == "rules"
    assert convo == [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]


def test_sidar_agent_activity_and_archive_context_paths() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent._autonomy_history = [
        {"trigger_id": "1", "status": "success", "source": "ci"},
        {"trigger_id": "2", "status": "failed", "source": "scheduler"},
    ]
    summary = agent.get_autonomy_activity(limit=2)
    assert summary["counts_by_status"] == {"success": 1, "failed": 1}
    assert summary["latest_trigger_id"] == "2"

    class _Collection:
        def query(self, **_kwargs):
            return {
                "documents": [["uzun metin " * 40]],
                "metadatas": [[{"source": "memory_archive", "title": "Arşiv"}]],
                "distances": [[0.1]],
            }

    agent.docs = SimpleNamespace(collection=_Collection())
    context = agent._get_memory_archive_context_sync(
        user_input="geçmişi getir",
        top_k=1,
        min_score=0.5,
        max_chars=600,
    )
    assert "[Geçmiş Sohbet Arşivinden İlgili Notlar]" in context


def test_sidar_agent_try_multi_agent_fallback_for_invalid_output(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace()

    async def _invalid_run_task(_goal: str):
        return 123

    agent._supervisor = SimpleNamespace(run_task=_invalid_run_task)

    result = asyncio.run(agent._try_multi_agent("görev"))
    assert result == "⚠ Supervisor geçerli bir çıktı üretemedi."
