"""
managers/web_search.py için birim testleri.
WebSearchManager: constructor, availability/status, search routing,
content helpers, scrape/fetch wrappers ve docs query helper akışları.
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock

import httpx


def _stub_deps():
    """Stub bs4 and duckduckgo_search so import doesn't fail without them."""
    if "bs4" not in sys.modules:
        bs4_stub = types.ModuleType("bs4")

        class _FakeSoup:
            def __init__(self, html, parser):
                self._text = html

            def __call__(self, tags):
                return []

            def get_text(self, separator=" ", strip=True):
                return self._text

            def decompose(self):
                pass

        bs4_stub.BeautifulSoup = _FakeSoup
        sys.modules["bs4"] = bs4_stub

    if "duckduckgo_search" not in sys.modules:
        ddg_stub = types.ModuleType("duckduckgo_search")
        sys.modules["duckduckgo_search"] = ddg_stub


def _get_ws():
    _stub_deps()
    if "managers.web_search" in sys.modules:
        del sys.modules["managers.web_search"]
    import managers.web_search as ws

    return ws


class TestWebSearchManagerInit:
    def test_no_config_defaults(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        assert mgr.engine == "auto"
        assert mgr.tavily_key == ""
        assert mgr.google_key == ""
        assert mgr.google_cx == ""

    def test_config_sets_engine(self):
        ws = _get_ws()

        class _Cfg:
            SEARCH_ENGINE = "tavily"
            TAVILY_API_KEY = "secret"
            GOOGLE_SEARCH_API_KEY = ""
            GOOGLE_SEARCH_CX = ""
            WEB_SEARCH_MAX_RESULTS = 5
            WEB_FETCH_TIMEOUT = 15
            WEB_SCRAPE_MAX_CHARS = 12000

        mgr = ws.WebSearchManager(config=_Cfg())
        assert mgr.engine == "tavily"
        assert mgr.tavily_key == "secret"

    def test_config_sets_max_results(self):
        ws = _get_ws()

        class _Cfg:
            SEARCH_ENGINE = "auto"
            TAVILY_API_KEY = ""
            GOOGLE_SEARCH_API_KEY = ""
            GOOGLE_SEARCH_CX = ""
            WEB_SEARCH_MAX_RESULTS = 8
            WEB_FETCH_TIMEOUT = 15
            WEB_SCRAPE_MAX_CHARS = 12000

        mgr = ws.WebSearchManager(config=_Cfg())
        assert mgr.MAX_RESULTS == 8


class TestIsAvailable:
    def test_false_without_any_engine(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr._ddg_available = False
        assert mgr.is_available() is False

    def test_true_with_tavily_key(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.tavily_key = "tok"
        assert mgr.is_available() is True

    def test_true_with_google_key_and_cx(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.google_key = "gkey"
        mgr.google_cx = "cx123"
        assert mgr.is_available() is True

    def test_false_with_google_key_but_no_cx(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.google_key = "gkey"
        mgr.google_cx = ""
        mgr._ddg_available = False
        assert mgr.is_available() is False


class TestStatus:
    def test_no_engine_message(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr._ddg_available = False
        result = mgr.status()
        assert "motor" in result.lower() or "kurulu" in result.lower()

    def test_tavily_listed(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.tavily_key = "tok"
        result = mgr.status()
        assert "Tavily" in result

    def test_google_listed(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.google_key = "gkey"
        mgr.google_cx = "cx"
        result = mgr.status()
        assert "Google" in result

    def test_mode_shown(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.tavily_key = "tok"
        result = mgr.status()
        assert "AUTO" in result or "Mod" in result


class TestSearchRouting:
    def test_search_direct_google_mode(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.engine = "google"
        mgr.google_key = "k"
        mgr.google_cx = "cx"
        mgr._search_google = AsyncMock(return_value=(True, "[g]"))

        ok, txt = asyncio.run(mgr.search("query", max_results=50))

        assert ok is True
        assert txt == "[g]"
        mgr._search_google.assert_awaited_once_with("query", 10)

    def test_search_fallback_after_tavily_failure(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.engine = "tavily"
        mgr.tavily_key = "t"
        mgr.google_key = "g"
        mgr.google_cx = "cx"
        mgr._search_tavily = AsyncMock(return_value=(False, "[HATA] Tavily: 401"))
        mgr._search_google = AsyncMock(return_value=(True, "google-ok"))

        ok, txt = asyncio.run(mgr.search("query"))

        assert ok is True
        assert txt == "google-ok"
        mgr._search_tavily.assert_awaited_once()
        mgr._search_google.assert_awaited_once()

    def test_search_returns_no_engine_error_when_all_missing(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr._ddg_available = False
        mgr.tavily_key = ""
        mgr.google_key = ""
        mgr.google_cx = ""

        ok, txt = asyncio.run(mgr.search("query", max_results="bad"))

        assert ok is False
        assert "API anahtarları" in txt


class TestScrapeAndFetch:
    def test_fetch_url_wraps_success_content(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.scrape_url = AsyncMock(return_value="clean content")

        ok, txt = asyncio.run(mgr.fetch_url("https://example.com"))

        assert ok is True
        assert "[URL: https://example.com]" in txt
        assert "clean content" in txt

    def test_fetch_url_passes_error_text(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.scrape_url = AsyncMock(return_value="Hata: Sayfa içeriği çekilemedi - HTTP 500")

        ok, txt = asyncio.run(mgr.fetch_url("https://example.com"))

        assert ok is False
        assert "HTTP 500" in txt

    def test_scrape_url_timeout_error_message(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url):
                raise httpx.TimeoutException("boom")

        ws.httpx.AsyncClient = lambda **kwargs: _Client()

        txt = asyncio.run(mgr.scrape_url("https://timeout.local"))
        assert "zaman aşımı" in txt


class TestTruncateContent:
    def _mgr(self):
        ws = _get_ws()
        return ws.WebSearchManager()

    def test_short_content_unchanged(self):
        mgr = self._mgr()
        text = "hello world"
        assert mgr._truncate_content(text) == text

    def test_long_content_truncated(self):
        mgr = self._mgr()
        mgr.FETCH_MAX_CHARS = 1200
        text = "x" * 2000
        result = mgr._truncate_content(text)
        assert len(result) < 2000
        assert "kesildi" in result

    def test_minimum_clamp_at_1000(self):
        mgr = self._mgr()
        mgr.FETCH_MAX_CHARS = 50
        text = "a" * 1500
        result = mgr._truncate_content(text)
        assert "kesildi" in result


class TestDocsAndHelpers:
    def test_search_docs_uses_site_filters_with_tavily(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.tavily_key = "tok"
        mgr.search = AsyncMock(return_value=(True, "ok"))

        asyncio.run(mgr.search_docs("fastapi", "middleware"))

        called_q = mgr.search.await_args.args[0]
        assert "site:docs.python.org" in called_q

    def test_search_docs_uses_ddg_friendly_query_without_api_keys(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.tavily_key = ""
        mgr.google_key = ""
        mgr.google_cx = ""
        mgr.search = AsyncMock(return_value=(True, "ok"))

        asyncio.run(mgr.search_docs("pytest", "fixtures"))

        called_q = mgr.search.await_args.args[0]
        assert "official docs reference" in called_q

    def test_search_stackoverflow_query_variants(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.search = AsyncMock(return_value=(True, "ok"))

        mgr.tavily_key = "k"
        asyncio.run(mgr.search_stackoverflow("asyncio timeout"))
        with_site = mgr.search.await_args.args[0]

        mgr.tavily_key = ""
        mgr.google_key = ""
        mgr.google_cx = ""
        asyncio.run(mgr.search_stackoverflow("asyncio timeout"))
        without_site = mgr.search.await_args.args[0]

        assert with_site.startswith("site:stackoverflow.com")
        assert without_site.startswith("stackoverflow")

    def test_mark_no_results_adds_prefix(self):
        ws = _get_ws()
        result = ws.WebSearchManager._mark_no_results("nothing found")
        assert result.startswith(ws.WebSearchManager._NO_RESULTS_PREFIX)

    def test_is_actionable_true_normal_result(self):
        ws = _get_ws()
        assert ws.WebSearchManager._is_actionable_result(True, "Some search results") is True

    def test_is_actionable_false_if_no_results(self):
        ws = _get_ws()
        no_res = ws.WebSearchManager._mark_no_results("empty")
        assert ws.WebSearchManager._is_actionable_result(True, no_res) is False

    def test_is_actionable_false_if_not_ok(self):
        ws = _get_ws()
        assert ws.WebSearchManager._is_actionable_result(False, "error text") is False

    def test_normalize_strips_prefix(self):
        ws = _get_ws()
        marked = ws.WebSearchManager._mark_no_results("nothing")
        normalized = ws.WebSearchManager._normalize_result_text(marked)
        assert not normalized.startswith(ws.WebSearchManager._NO_RESULTS_PREFIX)
        assert "nothing" in normalized

    def test_normalize_normal_text_unchanged(self):
        ws = _get_ws()
        text = "normal result"
        assert ws.WebSearchManager._normalize_result_text(text) == text

    def test_repr_lists_available_engines(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.tavily_key = "t"
        mgr.google_key = "g"
        mgr.google_cx = "cx"
        mgr._ddg_available = True

        text = repr(mgr)
        assert "Tavily" in text
        assert "Google" in text
        assert "DuckDuckGo" in text
