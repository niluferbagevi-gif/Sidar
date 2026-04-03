from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from types import SimpleNamespace


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


if not _has_module("httpx"):
    fake_httpx = types.ModuleType("httpx")

    class Timeout:
        def __init__(self, *args, **kwargs):
            return None

    fake_httpx.Timeout = Timeout
    fake_httpx.TimeoutException = Exception
    fake_httpx.RequestError = Exception
    fake_httpx.HTTPStatusError = Exception
    fake_httpx.AsyncClient = object
    sys.modules["httpx"] = fake_httpx

if not _has_module("bs4"):
    fake_bs4 = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, html, _parser):
            self._html = html

        def __call__(self, *_args, **_kwargs):
            return []

        def get_text(self, **_kwargs):
            return self._html

    fake_bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = fake_bs4

from managers.web_search import WebSearchManager


def test_web_search_helpers_and_status_text() -> None:
    manager = WebSearchManager(SimpleNamespace(SEARCH_ENGINE="auto", TAVILY_API_KEY="", GOOGLE_SEARCH_API_KEY="", GOOGLE_SEARCH_CX=""))
    manager._ddg_available = False

    assert manager.is_available() is False
    assert "motor yok" in manager.status()

    no_result = manager._mark_no_results("empty")
    assert manager._is_actionable_result(True, no_result) is False
    assert manager._normalize_result_text(no_result) == "empty"


def test_web_search_docs_query_and_fallback_error(monkeypatch) -> None:
    manager = WebSearchManager(SimpleNamespace(SEARCH_ENGINE="auto", TAVILY_API_KEY="tv", GOOGLE_SEARCH_API_KEY="", GOOGLE_SEARCH_CX=""))

    captured = {}

    async def _fake_search(query: str, max_results=None):
        captured["query"] = query
        captured["max_results"] = max_results
        return True, "ok"

    monkeypatch.setattr(manager, "search", _fake_search)
    ok, _ = asyncio.run(manager.search_docs("fastapi", "auth"))
    assert ok is True
    assert "site:docs.python.org" in captured["query"]
    assert captured["max_results"] == 5

    manager2 = WebSearchManager(SimpleNamespace(SEARCH_ENGINE="duckduckgo", TAVILY_API_KEY="", GOOGLE_SEARCH_API_KEY="", GOOGLE_SEARCH_CX=""))
    manager2._ddg_available = False
    ok2, msg2 = asyncio.run(manager2.search("sidar"))
    assert ok2 is False
    assert "Web arama yapılamadı" in msg2


def test_web_search_stackoverflow_query_without_keys(monkeypatch) -> None:
    manager = WebSearchManager(SimpleNamespace(SEARCH_ENGINE="auto", TAVILY_API_KEY="", GOOGLE_SEARCH_API_KEY="", GOOGLE_SEARCH_CX=""))
    manager._ddg_available = True

    async def _fake_search(query: str, max_results=None):
        return True, f"Q={query} N={max_results}"

    monkeypatch.setattr(manager, "search", _fake_search)

    ok, text = asyncio.run(manager.search_stackoverflow("python timeout"))
    assert ok is True
    assert "stackoverflow python timeout" in text
    assert "N=5" in text
