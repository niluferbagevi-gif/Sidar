import asyncio
import builtins
import sys
import types
from types import SimpleNamespace

import httpx
import pytest

from managers.web_search import WebSearchManager


def run(coro):
    return asyncio.run(coro)


class DummyConfig:
    SEARCH_ENGINE = "Tavily"
    TAVILY_API_KEY = "tav-key"
    GOOGLE_SEARCH_API_KEY = "g-key"
    GOOGLE_SEARCH_CX = "g-cx"
    WEB_SEARCH_MAX_RESULTS = 7
    WEB_FETCH_TIMEOUT = 9
    WEB_SCRAPE_MAX_CHARS = 1500


class DummyResponse:
    def __init__(self, payload=None, text="", status_code=200):
        self._payload = payload or {}
        self.text = text
        self.status_code = status_code
        self.encoding = None
        self.response = self

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", "https://example.com")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError("boom", request=req, response=resp)


class DummyAsyncClient:
    def __init__(self, response=None, exc=None, **kwargs):
        self.response = response
        self.exc = exc
        self.kwargs = kwargs
        self.last_post = None
        self.last_get = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json):
        self.last_post = (url, json)
        if self.exc:
            raise self.exc
        return self.response

    async def get(self, url, params=None):
        self.last_get = (url, params)
        if self.exc:
            raise self.exc
        return self.response


def test_dummy_response_raise_for_status_and_fail_import_passthrough():
    ok_resp = DummyResponse(status_code=200)
    ok_resp.raise_for_status()

    bad_resp = DummyResponse(status_code=500)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        bad_resp.raise_for_status()
    assert exc_info.value.response.status_code == 500

    real_import = builtins.__import__

    def fail_import(name, *args, **kwargs):
        if name == "duckduckgo_search":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    assert fail_import("math").__name__ == "math"
    with pytest.raises(ImportError):
        fail_import("duckduckgo_search")


def test_init_with_config(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: True)
    m = WebSearchManager(DummyConfig())

    assert m.engine == "tavily"
    assert m.tavily_key == "tav-key"
    assert m.google_key == "g-key"
    assert m.google_cx == "g-cx"
    assert m.MAX_RESULTS == 7
    assert m.FETCH_TIMEOUT == 9
    assert m.FETCH_MAX_CHARS == 1500
    assert m._ddg_available is True


def test_check_ddg_true_and_false(monkeypatch):
    m = WebSearchManager.__new__(WebSearchManager)

    real_import = builtins.__import__

    def ok_import(name, *args, **kwargs):
        if name == "duckduckgo_search":
            return types.SimpleNamespace(DDGS=object)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", ok_import)
    assert m._check_ddg() is True

    def fail_import(name, *args, **kwargs):
        if name == "duckduckgo_search":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    assert fail_import("math").__name__ == "math"
    with pytest.raises(ImportError):
        fail_import("duckduckgo_search")

    monkeypatch.setattr(builtins, "__import__", fail_import)
    assert m._check_ddg() is False


def test_is_available_status_and_repr(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    m = WebSearchManager()

    assert m.is_available() is False
    assert "motor yok" in m.status()

    m.tavily_key = "x"
    m.google_key = "g"
    m.google_cx = "cx"
    m._ddg_available = True

    assert m.is_available() is True
    assert "Tavily" in m.status()
    assert "Google" in m.status()
    assert "DuckDuckGo" in m.status()
    assert "engine=auto" in repr(m)


def test_search_engine_specific_and_limits(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    m = WebSearchManager(DummyConfig())

    called = {}

    async def fake_tavily(query, n):
        called["n"] = n
        return True, m._mark_no_results("none")

    monkeypatch.setattr(m, "_search_tavily", fake_tavily)
    ok, res = run(m.search("q", max_results="99"))

    assert ok is True
    assert res == "none"
    assert called["n"] == 10


def test_search_tavily_selected_actionable_and_bad_max_results(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    m = WebSearchManager(DummyConfig())
    m.engine = "tavily"

    called = {}

    async def tavily_actionable(query, n):
        called["n"] = n
        return True, "tavily-ok"

    monkeypatch.setattr(m, "_search_tavily", tavily_actionable)
    ok, res = run(m.search("q", max_results={"bad": "type"}))
    assert (ok, res) == (True, "tavily-ok")
    assert called["n"] == m.MAX_RESULTS


def test_search_tavily_fail_fallback_google(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    m = WebSearchManager(DummyConfig())

    async def bad_tavily(query, n):
        return False, "[HATA]"

    async def good_google(query, n):
        return True, "google-ok"

    monkeypatch.setattr(m, "_search_tavily", bad_tavily)
    monkeypatch.setattr(m, "_search_google", good_google)

    ok, res = run(m.search("q"))
    assert (ok, res) == (True, "google-ok")


def test_search_auto_returns_tavily_actionable(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    m = WebSearchManager(DummyConfig())
    m.engine = "auto"

    async def tavily_ok(query, n):
        return True, "tavily-from-auto"

    async def google_should_not_run(query, n):
        raise AssertionError("google fallback should not run when tavily is actionable")

    monkeypatch.setattr(m, "_search_tavily", tavily_ok)
    monkeypatch.setattr(m, "_search_google", google_should_not_run)
    assert run(m.search("q")) == (True, "tavily-from-auto")


def test_search_google_and_duckduckgo_direct(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: True)

    m_google = WebSearchManager(DummyConfig())
    m_google.engine = "google"

    async def google(query, n):
        return True, "g"

    monkeypatch.setattr(m_google, "_search_google", google)
    assert run(m_google.search("q")) == (True, "g")

    m_ddg = WebSearchManager()
    m_ddg.engine = "duckduckgo"

    async def ddg(query, n):
        return True, m_ddg._mark_no_results("ddg-none")

    monkeypatch.setattr(m_ddg, "_search_duckduckgo", ddg)
    assert run(m_ddg.search("q")) == (True, "ddg-none")


def test_search_auto_no_actionable_then_ddg_and_no_engine(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: True)
    m = WebSearchManager(DummyConfig())
    m.engine = "auto"

    async def no_tavily(query, n):
        return True, m._mark_no_results("tn")

    async def no_google(query, n):
        return True, m._mark_no_results("gn")

    async def ddg(query, n):
        return True, "ddg-final"

    monkeypatch.setattr(m, "_search_tavily", no_tavily)
    monkeypatch.setattr(m, "_search_google", no_google)
    monkeypatch.setattr(m, "_search_duckduckgo", ddg)
    assert run(m.search("q")) == (True, "ddg-final")

    m2 = WebSearchManager()
    m2._ddg_available = False
    assert run(m2.search("q"))[0] is False


def test_search_tavily_success_no_results_and_errors(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    m = WebSearchManager(DummyConfig())

    client = DummyAsyncClient(
        response=DummyResponse(payload={"results": [{"title": "t", "content": "c", "url": "u"}]})
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    ok, res = run(m._search_tavily("python", 3))
    assert ok is True
    assert "Web Arama (Tavily)" in res
    assert "**t**" in res
    assert "   c" in res

    client_no_content = DummyAsyncClient(
        response=DummyResponse(payload={"results": [{"title": "t2", "content": "", "url": "u2"}]})
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_no_content)
    ok, res = run(m._search_tavily("python", 3))
    assert ok is True
    assert "**t2**" in res
    assert "   → u2" in res
    assert "   \n" not in res

    client_empty = DummyAsyncClient(response=DummyResponse(payload={"results": []}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_empty)
    ok, res = run(m._search_tavily("python", 3))
    assert ok is True
    assert res.startswith(m._NO_RESULTS_PREFIX)

    req = httpx.Request("POST", "https://api.tavily.com/search")
    resp = httpx.Response(401, request=req)
    err401 = httpx.HTTPStatusError("unauth", request=req, response=resp)
    client_401 = DummyAsyncClient(exc=err401)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_401)
    ok, res = run(m._search_tavily("python", 3))
    assert ok is False
    assert "[HATA] Tavily" in res
    assert m.tavily_key == ""

    client_exc = DummyAsyncClient(exc=RuntimeError("boom"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_exc)
    ok, _ = run(m._search_tavily("python", 3))
    assert ok is False

    req_500 = httpx.Request("POST", "https://api.tavily.com/search")
    resp_500 = httpx.Response(500, request=req_500)
    err500 = httpx.HTTPStatusError("http", request=req_500, response=resp_500)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: DummyAsyncClient(exc=err500))
    m.tavily_key = "still-set"
    ok, res = run(m._search_tavily("python", 3))
    assert ok is False
    assert "[HATA] Tavily" in res
    assert m.tavily_key == "still-set"


def test_search_google_success_no_items_and_error(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    m = WebSearchManager(DummyConfig())

    client = DummyAsyncClient(
        response=DummyResponse(payload={"items": [{"title": "t", "snippet": "s", "link": "l"}]})
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    ok, res = run(m._search_google("python", 3))
    assert ok is True
    assert "Web Arama (Google)" in res

    client2 = DummyAsyncClient(response=DummyResponse(payload={"items": []}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client2)
    ok, res = run(m._search_google("python", 3))
    assert ok is True
    assert res.startswith(m._NO_RESULTS_PREFIX)

    client3 = DummyAsyncClient(exc=RuntimeError("x"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client3)
    ok, res = run(m._search_google("python", 3))
    assert ok is False
    assert "Google Search" in res

    client4 = DummyAsyncClient(
        response=DummyResponse(payload={"items": [{"title": "t", "snippet": "", "link": "l"}]})
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client4)
    ok, res = run(m._search_google("python", 3))
    assert ok is True
    assert "   → l" in res


def test_search_duckduckgo_asyncddgs_list(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: True)
    m = WebSearchManager()

    class FakeAsyncDDGS:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self, query, max_results):
            return [{"title": "t", "body": "b", "href": "h"}]

    mod = types.SimpleNamespace(AsyncDDGS=FakeAsyncDDGS)
    monkeypatch.setitem(sys.modules, "duckduckgo_search", mod)

    ok, res = run(m._search_duckduckgo("python", 2))
    assert ok is True
    assert "DuckDuckGo" in res


def test_search_duckduckgo_asyncddgs_async_generator(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: True)
    m = WebSearchManager()

    async def agen():
        yield {"title": "t2", "body": "b2", "href": "h2"}

    class FakeAsyncDDGS:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self, query, max_results):
            return agen()

    mod = types.SimpleNamespace(AsyncDDGS=FakeAsyncDDGS)
    monkeypatch.setitem(sys.modules, "duckduckgo_search", mod)

    ok, res = run(m._search_duckduckgo("python", 2))
    assert ok is True
    assert "t2" in res


def test_search_duckduckgo_ddgs_fallback_no_results_timeout_and_error(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: True)
    m = WebSearchManager()

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def text(self, query, max_results):
            return []

    mod = types.SimpleNamespace(DDGS=FakeDDGS)
    monkeypatch.setitem(sys.modules, "duckduckgo_search", mod)

    ok, res = run(m._search_duckduckgo("python", 2))
    assert ok is True
    assert res.startswith(m._NO_RESULTS_PREFIX)

    async def timeout_wait_for(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", timeout_wait_for)
    ok, res = run(m._search_duckduckgo("python", 2))
    assert ok is False
    assert "Zaman aşımı" in res

    monkeypatch.setattr(
        asyncio, "wait_for", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    )
    ok, res = run(m._search_duckduckgo("python", 2))
    assert ok is False
    assert "DuckDuckGo" in res


def test_search_duckduckgo_no_body_line(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: True)
    m = WebSearchManager()

    class FakeAsyncDDGS:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self, query, max_results):
            return [{"title": "t", "body": "", "href": "h"}]

    monkeypatch.setitem(
        sys.modules, "duckduckgo_search", types.SimpleNamespace(AsyncDDGS=FakeAsyncDDGS)
    )
    ok, res = run(m._search_duckduckgo("python", 2))
    assert ok is True
    assert "   → h" in res
    assert "\n   \n" not in res


def test_scrape_url_fetch_url_and_truncate(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    m = WebSearchManager()

    client = DummyAsyncClient(
        response=DummyResponse(text="<html><body><h1>A</h1><script>x</script> B</body></html>")
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    text = run(m.scrape_url("https://example.com"))
    assert text == "A B"

    req = httpx.Request("GET", "https://x")
    timeout_exc = httpx.TimeoutException("t", request=req)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: DummyAsyncClient(exc=timeout_exc))
    assert "zaman aşımı" in run(m.scrape_url("https://x"))

    req_err = httpx.RequestError("r", request=req)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: DummyAsyncClient(exc=req_err))
    assert "bağlantı/istek" in run(m.scrape_url("https://x"))

    status_err = httpx.HTTPStatusError("h", request=req, response=httpx.Response(500, request=req))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: DummyAsyncClient(exc=status_err))
    assert "HTTP 500" in run(m.scrape_url("https://x"))

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: DummyAsyncClient(exc=RuntimeError("e"))
    )
    assert "çekilemedi" in run(m.scrape_url("https://x"))

    monkeypatch.setattr(m, "scrape_url", lambda url: asyncio.sleep(0, result="ok"))
    assert run(m.fetch_url("https://ok")) == (True, "[URL: https://ok]\n\nok")

    monkeypatch.setattr(
        m, "scrape_url", lambda url: asyncio.sleep(0, result="Hata: Sayfa içeriği çekilemedi - x")
    )
    assert run(m.fetch_url("https://bad"))[0] is False

    m.FETCH_MAX_CHARS = "bad"
    truncated = m._truncate_content("x" * 13000)
    assert truncated.endswith("kesildi]")
    assert m._truncate_content("short") == "short"


def test_clean_html_docs_stackoverflow_and_helpers(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    m = WebSearchManager()

    cleaned = m._clean_html(
        "<html><header>x</header><body>a &amp; b <style>c</style></body></html>"
    )
    assert cleaned == "a & b"

    calls = {}

    async def fake_search(query, max_results=None):
        calls["query"] = query
        calls["max_results"] = max_results
        return True, "ok"

    monkeypatch.setattr(m, "search", fake_search)

    run(m.search_docs("python", "asyncio"))
    assert "site:docs.python.org" not in calls["query"]
    assert calls["max_results"] == 5

    m.tavily_key = "x"
    run(m.search_docs("python", "asyncio"))
    assert "site:docs.python.org" in calls["query"]

    m.tavily_key = ""
    m.google_key = ""
    m.google_cx = ""
    run(m.search_stackoverflow("list comprehension"))
    assert calls["query"].startswith("stackoverflow")

    m.google_key = "g"
    m.google_cx = "cx"
    run(m.search_stackoverflow("list comprehension"))
    assert calls["query"].startswith("site:stackoverflow.com")

    marked = m._mark_no_results("n")
    assert m._is_actionable_result(True, "ok") is True
    assert m._is_actionable_result(True, marked) is False
    assert m._normalize_result_text(marked) == "n"
    assert m._normalize_result_text("plain") == "plain"


def test_web_search_manager_isolated(monkeypatch):
    monkeypatch.setattr(WebSearchManager, "_check_ddg", lambda self: False)
    web = WebSearchManager(
        SimpleNamespace(
            SEARCH_ENGINE="tavily",
            TAVILY_API_KEY="test-key",
            GOOGLE_SEARCH_API_KEY="",
            GOOGLE_SEARCH_CX="",
            WEB_SEARCH_MAX_RESULTS=5,
            WEB_FETCH_TIMEOUT=5,
            WEB_SCRAPE_MAX_CHARS=1000,
        )
    )

    async def _fake_tavily(_query, _n):
        return True, "web-ok"

    web._search_tavily = _fake_tavily
    ok, text = run(web.search("sidar"))
    assert ok is True and text == "web-ok"
