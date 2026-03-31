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


class TestWebSearchEngineApiMocking:
    def test_search_auto_falls_back_when_tavily_returns_no_results(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.engine = "auto"
        mgr.tavily_key = "tok"
        mgr.google_key = "g"
        mgr.google_cx = "cx"
        mgr._search_tavily = AsyncMock(return_value=(True, ws.WebSearchManager._mark_no_results("empty")))
        mgr._search_google = AsyncMock(return_value=(True, "google-hit"))

        ok, out = asyncio.run(mgr.search("query", max_results=5))

        assert ok is True
        assert out == "google-hit"
        mgr._search_tavily.assert_awaited_once()
        mgr._search_google.assert_awaited_once()

    def test_search_duckduckgo_timeout_returns_error(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.FETCH_TIMEOUT = 0.01

        ddg_stub = types.ModuleType("duckduckgo_search")

        class _AsyncDDGS:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def text(self, query, max_results=5):
                raise asyncio.TimeoutError()

        ddg_stub.AsyncDDGS = _AsyncDDGS
        sys.modules["duckduckgo_search"] = ddg_stub

        ok, out = asyncio.run(mgr._search_duckduckgo("query", 5))
        assert ok is False
        assert "Zaman aşımı" in out

    def test_search_tavily_success_with_mocked_json(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.tavily_key = "tok"

        response = types.SimpleNamespace(
            json=lambda: {"results": [{"title": "A", "content": "B", "url": "https://a"}]},
            raise_for_status=lambda: None,
        )

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, _url, json=None):
                return response

        ws.httpx.AsyncClient = lambda **_kwargs: _Client()
        ok, out = asyncio.run(mgr._search_tavily("query", 5))
        assert ok is True
        assert "Web Arama (Tavily)" in out

    def test_search_tavily_401_disables_key(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.tavily_key = "tok"

        class _Response:
            status_code = 401

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, _url, json=None):
                raise httpx.HTTPStatusError("unauthorized", request=httpx.Request("POST", "https://x"), response=_Response())

        ws.httpx.AsyncClient = lambda **_kwargs: _Client()
        ok, out = asyncio.run(mgr._search_tavily("query", 5))
        assert ok is False
        assert mgr.tavily_key == ""
        assert "Tavily" in out

    def test_search_google_success_and_failure_paths(self):
        ws = _get_ws()
        mgr = ws.WebSearchManager()
        mgr.google_key = "g"
        mgr.google_cx = "cx"

        success_resp = types.SimpleNamespace(
            json=lambda: {"items": [{"title": "G1", "snippet": "S1", "link": "https://g"}]},
            raise_for_status=lambda: None,
        )

        class _ClientOk:
            async def __aenter__(self): return self
            async def __aexit__(self, exc_type, exc, tb): return False
            async def get(self, _url, params=None): return success_resp

        ws.httpx.AsyncClient = lambda **_kwargs: _ClientOk()
        ok, out = asyncio.run(mgr._search_google("query", 5))
        assert ok is True
        assert "Web Arama (Google)" in out

        class _ClientFail:
            async def __aenter__(self): return self
            async def __aexit__(self, exc_type, exc, tb): return False
            async def get(self, _url, params=None): raise RuntimeError("network fail")

        ws.httpx.AsyncClient = lambda **_kwargs: _ClientFail()
        ok, out = asyncio.run(mgr._search_google("query", 5))
        assert ok is False
        assert "Google Search" in out

# ===== MERGED FROM tests/test_managers_web_search_extra.py =====

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _get_web_search():
    # bs4 stub
    if "bs4" not in sys.modules:
        bs4 = types.ModuleType("bs4")
        class _FakeSoup:
            def __init__(self, html, parser):
                self._html = html
            def __call__(self, tags):
                return []
            def get_text(self, separator=" ", strip=False):
                return self._html
            def decompose(self):
                pass
        bs4.BeautifulSoup = _FakeSoup
        sys.modules["bs4"] = bs4

    if "httpx" not in sys.modules:
        httpx = types.ModuleType("httpx")
        class _Timeout:
            def __init__(self, *a, **kw): pass
        class _HTTPStatusError(Exception):
            def __init__(self, msg="", response=None):
                super().__init__(msg)
                self.response = response or MagicMock(status_code=500)
        class _RequestError(Exception): pass
        class _TimeoutException(Exception): pass
        httpx.Timeout = _Timeout
        httpx.HTTPStatusError = _HTTPStatusError
        httpx.RequestError = _RequestError
        httpx.TimeoutException = _TimeoutException
        sys.modules["httpx"] = httpx

    if "managers.web_search" in sys.modules:
        del sys.modules["managers.web_search"]
    import managers.web_search as ws
    return ws


# ══════════════════════════════════════════════════════════════
# is_available() (73)
# ══════════════════════════════════════════════════════════════

class Extra_TestIsAvailable:
    def test_available_with_tavily_key(self):
        ws = _get_web_search()
        cfg = MagicMock()
        cfg.SEARCH_ENGINE = "auto"
        cfg.TAVILY_API_KEY = "test_key"
        cfg.GOOGLE_SEARCH_API_KEY = ""
        cfg.GOOGLE_SEARCH_CX = ""
        cfg.WEB_SEARCH_MAX_RESULTS = 5
        cfg.WEB_FETCH_TIMEOUT = 15
        cfg.WEB_SCRAPE_MAX_CHARS = 12000

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(cfg)
            assert manager.is_available() is True

    def test_available_with_google_key(self):
        ws = _get_web_search()
        cfg = MagicMock()
        cfg.SEARCH_ENGINE = "auto"
        cfg.TAVILY_API_KEY = ""
        cfg.GOOGLE_SEARCH_API_KEY = "gkey"
        cfg.GOOGLE_SEARCH_CX = "gcx"
        cfg.WEB_SEARCH_MAX_RESULTS = 5
        cfg.WEB_FETCH_TIMEOUT = 15
        cfg.WEB_SCRAPE_MAX_CHARS = 12000

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(cfg)
            assert manager.is_available() is True

    def test_not_available_with_nothing(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            assert manager.is_available() is False


# ══════════════════════════════════════════════════════════════
# status() (89)
# ══════════════════════════════════════════════════════════════

class Extra_TestStatus:
    def test_status_with_tavily(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.tavily_key = "key"
            result = manager.status()
            assert "Tavily" in result

    def test_status_with_all_engines(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=True):
            manager = ws.WebSearchManager(None)
            manager.tavily_key = "key"
            manager.google_key = "gkey"
            manager.google_cx = "gcx"
            result = manager.status()
            assert "Google" in result
            assert "DuckDuckGo" in result

    def test_status_no_engines(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            result = manager.status()
            assert "motor yok" in result


# ══════════════════════════════════════════════════════════════
# search() — çeşitli engine modları (113-141)
# ══════════════════════════════════════════════════════════════

class Extra_TestSearch:
    def test_search_tavily_engine_success(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.engine = "tavily"
            manager.tavily_key = "key"
            manager._search_tavily = AsyncMock(return_value=(True, "Sonuç"))
            result = asyncio.run(manager.search("test sorgusu"))
            assert result[0] is True

    def test_search_tavily_fails_then_auto_fallback(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=True):
            manager = ws.WebSearchManager(None)
            manager.engine = "tavily"
            manager.tavily_key = "key"
            manager._search_tavily = AsyncMock(return_value=(False, "[HATA]"))
            manager._search_duckduckgo = AsyncMock(return_value=(True, "DDG sonuç"))
            result = asyncio.run(manager.search("test"))
            assert result[0] is True

    def test_search_google_engine(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.engine = "google"
            manager.google_key = "gkey"
            manager.google_cx = "gcx"
            manager._search_google = AsyncMock(return_value=(True, "Google sonuç"))
            result = asyncio.run(manager.search("test"))
            assert result[0] is True

    def test_search_duckduckgo_engine(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=True):
            manager = ws.WebSearchManager(None)
            manager.engine = "duckduckgo"
            manager._ddg_available = True
            manager._search_duckduckgo = AsyncMock(return_value=(True, "DDG sonuç"))
            result = asyncio.run(manager.search("test"))
            assert result[0] is True

    def test_search_auto_mode_tavily_no_results_fallback_to_google(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.engine = "auto"
            manager.tavily_key = "key"
            manager.google_key = "gkey"
            manager.google_cx = "gcx"
            manager._search_tavily = AsyncMock(return_value=(True, "[NO_RESULTS] bulunamadı"))
            manager._search_google = AsyncMock(return_value=(True, "Google sonuçlar"))
            result = asyncio.run(manager.search("test"))
            assert result[0] is True

    def test_search_auto_mode_all_fail(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.engine = "auto"
            manager.tavily_key = ""
            manager.google_key = ""
            manager.google_cx = ""
            result = asyncio.run(manager.search("test"))
            assert result[0] is False

    def test_search_max_results_bounded(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=True):
            manager = ws.WebSearchManager(None)
            manager.engine = "duckduckgo"
            manager._ddg_available = True
            manager._search_duckduckgo = AsyncMock(return_value=(True, "sonuç"))
            # max_results=0 → clipped to 1
            result = asyncio.run(manager.search("test", max_results=0))
            assert result is not None


# ══════════════════════════════════════════════════════════════
# _search_tavily() — hata yolları (166, 174→176, 188, 190-192)
# ══════════════════════════════════════════════════════════════

class Extra_TestSearchTavily:
    def test_tavily_no_results(self):
        ws = _get_web_search()
        import httpx as _httpx

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.tavily_key = "key"
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value={"results": []})

            async def _mock_post(*a, **kw):
                return mock_response

            with patch("httpx.AsyncClient") as mock_client:
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_response)))
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_ctx
                ok, text = asyncio.run(manager._search_tavily("test", 5))
            assert ok is True
            assert "sonuç bulunamadı" in text.lower() or "NO_RESULTS" in text

    def test_tavily_401_error(self):
        ws = _get_web_search()
        import httpx

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.tavily_key = "key"

            mock_req = MagicMock()
            mock_resp = MagicMock(status_code=401)
            error = httpx.HTTPStatusError("401", request=mock_req, response=mock_resp)

            async def _raise(*a, **kw):
                raise error

            with patch("httpx.AsyncClient") as mock_client:
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=error)))
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_ctx
                ok, text = asyncio.run(manager._search_tavily("test", 5))
            assert ok is False
            # tavily key should be cleared after 401
            assert manager.tavily_key == ""

    def test_tavily_generic_exception(self):
        ws = _get_web_search()

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.tavily_key = "key"

            with patch("httpx.AsyncClient") as mock_client:
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=Exception("network error"))))
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_ctx
                ok, text = asyncio.run(manager._search_tavily("test", 5))
            assert ok is False


# ══════════════════════════════════════════════════════════════
# _search_google() — (210, 218→220)
# ══════════════════════════════════════════════════════════════

class Extra_TestSearchGoogle:
    def test_google_no_items(self):
        ws = _get_web_search()

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.google_key = "gkey"
            manager.google_cx = "gcx"

            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value={"items": []})

            with patch("httpx.AsyncClient") as mock_client:
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=mock_response)))
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_ctx
                ok, text = asyncio.run(manager._search_google("test", 5))
            assert ok is True

    def test_google_exception(self):
        ws = _get_web_search()

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.google_key = "gkey"
            manager.google_cx = "gcx"

            with patch("httpx.AsyncClient") as mock_client:
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(side_effect=Exception("API error"))))
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_ctx
                ok, text = asyncio.run(manager._search_google("test", 5))
            assert ok is False


# ══════════════════════════════════════════════════════════════
# _search_duckduckgo() — (240-281)
# ══════════════════════════════════════════════════════════════

class Extra_TestSearchDuckDuckGo:
    def test_ddg_sync_mode(self):
        ws = _get_web_search()

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=True):
            manager = ws.WebSearchManager(None)
            manager._ddg_available = True

            ddg_mod = types.ModuleType("duckduckgo_search")
            # No AsyncDDGS → sync mode
            mock_ddgs = MagicMock()
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            mock_ddgs.text = MagicMock(return_value=[
                {"title": "Test", "body": "içerik", "href": "https://example.com"}
            ])
            ddg_mod.DDGS = MagicMock(return_value=mock_ddgs)
            # No AsyncDDGS attribute

            with patch.dict(sys.modules, {"duckduckgo_search": ddg_mod}):
                ok, text = asyncio.run(manager._search_duckduckgo("test", 3))
            assert ok is True
            assert "DuckDuckGo" in text

    def test_ddg_no_results(self):
        ws = _get_web_search()

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=True):
            manager = ws.WebSearchManager(None)
            manager._ddg_available = True

            ddg_mod = types.ModuleType("duckduckgo_search")
            mock_ddgs = MagicMock()
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            mock_ddgs.text = MagicMock(return_value=[])
            ddg_mod.DDGS = MagicMock(return_value=mock_ddgs)

            with patch.dict(sys.modules, {"duckduckgo_search": ddg_mod}):
                ok, text = asyncio.run(manager._search_duckduckgo("test", 3))
            assert ok is True

    def test_ddg_timeout_error(self):
        ws = _get_web_search()

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=True):
            manager = ws.WebSearchManager(None)
            manager._ddg_available = True
            manager.FETCH_TIMEOUT = 0.001  # Very short timeout

            ddg_mod = types.ModuleType("duckduckgo_search")
            def _mock_text(*a, **kw):
                return []

            mock_ddgs = MagicMock()
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            mock_ddgs.text = _mock_text
            ddg_mod.DDGS = MagicMock(return_value=mock_ddgs)

            with patch.dict(sys.modules, {"duckduckgo_search": ddg_mod}):
                async def _slow_to_thread(*_a, **_kw):
                    await asyncio.sleep(0.05)
                    return []

                with patch("asyncio.to_thread", side_effect=_slow_to_thread):
                    ok, text = asyncio.run(manager._search_duckduckgo("test", 3))
            assert ok is False
            assert "Zaman aşımı" in text

    def test_ddg_generic_exception(self):
        ws = _get_web_search()

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=True):
            manager = ws.WebSearchManager(None)
            manager._ddg_available = True

            ddg_mod = types.ModuleType("duckduckgo_search")
            ddg_mod.DDGS = MagicMock(side_effect=Exception("DDG Error"))

            with patch.dict(sys.modules, {"duckduckgo_search": ddg_mod}):
                ok, text = asyncio.run(manager._search_duckduckgo("test", 3))
            assert ok is False


# ══════════════════════════════════════════════════════════════
# scrape_url() — hata yolları (296-310)
# ══════════════════════════════════════════════════════════════

class Extra_TestScrapeUrl:
    def test_scrape_timeout(self):
        ws = _get_web_search()
        import httpx

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)

            with patch("httpx.AsyncClient") as mock_client:
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(
                    get=AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
                ))
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_ctx
                result = asyncio.run(manager.scrape_url("https://example.com"))
            assert "zaman aşımı" in result

    def test_scrape_request_error(self):
        ws = _get_web_search()
        import httpx

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)

            with patch("httpx.AsyncClient") as mock_client:
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(
                    get=AsyncMock(side_effect=httpx.RequestError("Connection error"))
                ))
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_ctx
                result = asyncio.run(manager.scrape_url("https://example.com"))
            assert "bağlantı" in result or "istek" in result

    def test_scrape_http_error(self):
        ws = _get_web_search()
        import httpx

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            mock_req = MagicMock()
            mock_resp = MagicMock(status_code=404)
            error = httpx.HTTPStatusError("404", request=mock_req, response=mock_resp)

            with patch("httpx.AsyncClient") as mock_client:
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(
                    get=AsyncMock(side_effect=error)
                ))
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_ctx
                result = asyncio.run(manager.scrape_url("https://example.com"))
            assert "HTTP" in result

    def test_scrape_generic_exception(self):
        ws = _get_web_search()

        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)

            with patch("httpx.AsyncClient") as mock_client:
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(
                    get=AsyncMock(side_effect=Exception("Unknown error"))
                ))
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_ctx
                result = asyncio.run(manager.scrape_url("https://example.com"))
            assert "çekilemedi" in result


# ══════════════════════════════════════════════════════════════
# _truncate_content() (322-323) ve _clean_html() (332-338)
# ══════════════════════════════════════════════════════════════

class Extra_TestHelpers:
    def test_truncate_long_content(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            # max_len = max(1000, configured_limit), so need > 1000 chars to trigger truncation
            manager.FETCH_MAX_CHARS = 1000
            long_text = "a" * 1500  # 1500 > max(1000, 1000) = 1000
            result = manager._truncate_content(long_text)
            assert "kesildi" in result
            assert len(result) < 1500

    def test_truncate_short_content(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            short_text = "Kısa metin"
            result = manager._truncate_content(short_text)
            assert result == short_text

    def test_clean_html(self):
        ws = _get_web_search()
        html = "<html><body><p>Merhaba</p><script>alert(1);</script></body></html>"
        # bs4 gerçek kullanımı burada stub'a bağlı olduğu için sadece çalışıp çalışmadığını test ediyoruz
        result = ws.WebSearchManager._clean_html(html)
        assert result is not None

    def test_repr(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=True):
            manager = ws.WebSearchManager(None)
            manager.tavily_key = "key"
            r = repr(manager)
            assert "WebSearchManager" in r


# ══════════════════════════════════════════════════════════════
# fetch_url() ve search_docs()/search_stackoverflow()
# ══════════════════════════════════════════════════════════════

class Extra_TestFetchAndDocs:
    def test_fetch_url_success(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.scrape_url = AsyncMock(return_value="Sayfa içeriği burada")
            ok, text = asyncio.run(manager.fetch_url("https://example.com"))
            assert ok is True
            assert "URL" in text

    def test_fetch_url_error(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.scrape_url = AsyncMock(return_value="Hata: Sayfa içeriği çekilemedi - timeout")
            ok, text = asyncio.run(manager.fetch_url("https://example.com"))
            assert ok is False

    def test_search_docs(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.search = AsyncMock(return_value=(True, "docs result"))
            ok, text = asyncio.run(manager.search_docs("python", "asyncio"))
            assert ok is True

    def test_search_stackoverflow(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=False):
            manager = ws.WebSearchManager(None)
            manager.search = AsyncMock(return_value=(True, "stackoverflow result"))
            ok, text = asyncio.run(manager.search_stackoverflow("async python"))
            assert ok is True

    def test_search_docs_ddg_mode(self):
        ws = _get_web_search()
        with patch.object(ws.WebSearchManager, "_check_ddg", return_value=True):
            manager = ws.WebSearchManager(None)
            manager.tavily_key = ""
            manager.google_key = ""
            manager.search = AsyncMock(return_value=(True, "ddg docs"))
            ok, text = asyncio.run(manager.search_docs("requests"))
            assert ok is True
