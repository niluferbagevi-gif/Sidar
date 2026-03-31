"""
managers/web_search.py için ek testler — eksik satırları kapsar.
"""
from __future__ import annotations

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

class TestIsAvailable:
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

class TestStatus:
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

class TestSearch:
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

class TestSearchTavily:
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

            mock_resp = MagicMock(status_code=401)
            error = httpx.HTTPStatusError("401", response=mock_resp)

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

class TestSearchGoogle:
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

class TestSearchDuckDuckGo:
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

            async def _slow_search():
                import asyncio as _asyncio
                await _asyncio.sleep(10)

            async def _mock_text(*a, **kw):
                raise asyncio.TimeoutError()

            mock_ddgs = MagicMock()
            mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
            mock_ddgs.__exit__ = MagicMock(return_value=False)
            mock_ddgs.text = _mock_text
            ddg_mod.DDGS = MagicMock(return_value=mock_ddgs)

            with patch.dict(sys.modules, {"duckduckgo_search": ddg_mod}):
                with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
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

class TestScrapeUrl:
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
            mock_resp = MagicMock(status_code=404)
            error = httpx.HTTPStatusError("404", response=mock_resp)

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

class TestHelpers:
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

class TestFetchAndDocs:
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
