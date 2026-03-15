import asyncio
import sys
from types import SimpleNamespace

from tests.test_web_search_runtime import _load_web_search_module


def test_search_tavily_mode_success_normalizes_result(monkeypatch):
    mod = _load_web_search_module(monkeypatch)
    monkeypatch.setattr(mod.WebSearchManager, "_check_ddg", lambda self: False)
    cfg = SimpleNamespace(
        SEARCH_ENGINE="tavily",
        TAVILY_API_KEY="t",
        GOOGLE_SEARCH_API_KEY="",
        GOOGLE_SEARCH_CX="",
        WEB_SEARCH_MAX_RESULTS=5,
        WEB_FETCH_TIMEOUT=15,
        WEB_SCRAPE_MAX_CHARS=12000,
    )
    manager = mod.WebSearchManager(cfg)

    async def _tavily(*_):
        return True, manager._mark_no_results("tavily-no-results")

    monkeypatch.setattr(manager, "_search_tavily", _tavily)
    ok, text = asyncio.run(manager.search("q"))
    assert ok is True
    assert text == "tavily-no-results"


def test_search_auto_returns_tavily_when_actionable(monkeypatch):
    mod = _load_web_search_module(monkeypatch)
    monkeypatch.setattr(mod.WebSearchManager, "_check_ddg", lambda self: False)
    cfg = SimpleNamespace(
        SEARCH_ENGINE="auto",
        TAVILY_API_KEY="t",
        GOOGLE_SEARCH_API_KEY="g",
        GOOGLE_SEARCH_CX="cx",
        WEB_SEARCH_MAX_RESULTS=5,
        WEB_FETCH_TIMEOUT=15,
        WEB_SCRAPE_MAX_CHARS=12000,
    )
    manager = mod.WebSearchManager(cfg)

    async def _tavily(*_):
        return True, "tavily-actionable"

    async def _google(*_):
        raise AssertionError("google should not be called when tavily is actionable")

    monkeypatch.setattr(manager, "_search_tavily", _tavily)
    monkeypatch.setattr(manager, "_search_google", _google)

    ok, text = asyncio.run(manager.search("q"))
    assert ok is True
    assert text == "tavily-actionable"


def test_duckduckgo_asyncddgs_list_and_no_results_paths(monkeypatch):
    mod = _load_web_search_module(monkeypatch)
    monkeypatch.setattr(mod.WebSearchManager, "_check_ddg", lambda self: True)
    cfg = SimpleNamespace(
        SEARCH_ENGINE="duckduckgo",
        TAVILY_API_KEY="",
        GOOGLE_SEARCH_API_KEY="",
        GOOGLE_SEARCH_CX="",
        WEB_SEARCH_MAX_RESULTS=5,
        WEB_FETCH_TIMEOUT=15,
        WEB_SCRAPE_MAX_CHARS=12000,
    )
    manager = mod.WebSearchManager(cfg)

    class _AsyncDDGSList:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self, query, max_results):
            return [{"title": "T", "body": "B", "href": "H"}]

    monkeypatch.setitem(sys.modules, "duckduckgo_search", SimpleNamespace(AsyncDDGS=_AsyncDDGSList))
    ok, text = asyncio.run(manager._search_duckduckgo("q", 2))
    assert ok is True
    assert "DuckDuckGo" in text and "→ H" in text

    class _AsyncDDGSEmpty(_AsyncDDGSList):
        async def text(self, query, max_results):
            return []

    monkeypatch.setitem(sys.modules, "duckduckgo_search", SimpleNamespace(AsyncDDGS=_AsyncDDGSEmpty))
    ok2, text2 = asyncio.run(manager._search_duckduckgo("q", 2))
    assert ok2 is True
    assert "sonuç bulunamadı" in text2


def test_scrape_url_success_path_sets_encoding_and_cleans(monkeypatch):
    mod = _load_web_search_module(monkeypatch)
    monkeypatch.setattr(mod.WebSearchManager, "_check_ddg", lambda self: False)
    cfg = SimpleNamespace(
        SEARCH_ENGINE="auto",
        TAVILY_API_KEY="",
        GOOGLE_SEARCH_API_KEY="",
        GOOGLE_SEARCH_CX="",
        WEB_SEARCH_MAX_RESULTS=5,
        WEB_FETCH_TIMEOUT=15,
        WEB_SCRAPE_MAX_CHARS=12000,
    )
    manager = mod.WebSearchManager(cfg)

    class _Resp:
        def __init__(self):
            self.encoding = None
            self.text = "<html><body><script>x</script><p>ok</p></body></html>"

        def raise_for_status(self):
            return None

    resp = _Resp()

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return resp

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)

    out = asyncio.run(manager.scrape_url("https://example.com"))
    assert out == "ok"
    assert resp.encoding == "utf-8"