import asyncio
import importlib.util
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


class _FakeHTTPStatusError(Exception):
    def __init__(self, message, request=None, response=None):
        super().__init__(message)
        self.request = request
        self.response = response


class _FakeRequestError(Exception):
    pass


class _FakeTimeoutException(Exception):
    pass


class _FakeTimeout:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _FakeRequest:
    def __init__(self, method, url):
        self.method = method
        self.url = url


class _FakeResponse:
    def __init__(self, *, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.encoding = None

    def raise_for_status(self):
        if self.status_code >= 400:
            req = _FakeRequest("GET", "http://example.com")
            raise _FakeHTTPStatusError("http error", request=req, response=self)

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return _FakeResponse()

    async def get(self, *args, **kwargs):
        return _FakeResponse(text="<html><body>ok</body></html>")


class _FakeSoupTag:
    def __init__(self, soup, name):
        self._soup = soup
        self._name = name

    def decompose(self):
        self._soup.html = re.sub(
            rf"<{self._name}[^>]*>.*?</{self._name}>",
            " ",
            self._soup.html,
            flags=re.IGNORECASE | re.DOTALL,
        )


class _FakeSoup:
    def __init__(self, html, parser):
        self.html = html

    def __call__(self, names):
        found = []
        for name in names:
            if re.search(rf"<{name}[^>]*>", self.html, flags=re.IGNORECASE):
                found.append(_FakeSoupTag(self, name))
        return found

    def get_text(self, separator=" ", strip=True):
        text = re.sub(r"<[^>]+>", " ", self.html)
        text = text.replace("\n", " ")
        if strip:
            text = text.strip()
        return text


def _load_web_search_module(monkeypatch):
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Timeout = _FakeTimeout
    fake_httpx.TimeoutException = _FakeTimeoutException
    fake_httpx.RequestError = _FakeRequestError
    fake_httpx.HTTPStatusError = _FakeHTTPStatusError
    fake_httpx.Request = _FakeRequest
    fake_httpx.Response = _FakeResponse
    fake_httpx.AsyncClient = _FakeAsyncClient

    fake_bs4 = types.ModuleType("bs4")
    fake_bs4.BeautifulSoup = _FakeSoup

    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    monkeypatch.setitem(sys.modules, "bs4", fake_bs4)

    spec = importlib.util.spec_from_file_location("web_search_under_test", Path("managers/web_search.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def web_search_mod(monkeypatch):
    return _load_web_search_module(monkeypatch)


@pytest.fixture
def base_cfg():
    return SimpleNamespace(
        SEARCH_ENGINE="auto",
        TAVILY_API_KEY="",
        GOOGLE_SEARCH_API_KEY="",
        GOOGLE_SEARCH_CX="",
        WEB_SEARCH_MAX_RESULTS=5,
        WEB_FETCH_TIMEOUT=15,
        WEB_SCRAPE_MAX_CHARS=12000,
    )


def test_search_auto_fallback_from_tavily_no_results_to_google(monkeypatch, web_search_mod, base_cfg):
    base_cfg.TAVILY_API_KEY = "t-key"
    base_cfg.GOOGLE_SEARCH_API_KEY = "g-key"
    base_cfg.GOOGLE_SEARCH_CX = "g-cx"
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: False)
    manager = web_search_mod.WebSearchManager(base_cfg)

    calls = []

    async def fake_tavily(query, n):
        calls.append(("tavily", query, n))
        return True, manager._mark_no_results("boş")

    async def fake_google(query, n):
        calls.append(("google", query, n))
        return True, "google-result"

    monkeypatch.setattr(manager, "_search_tavily", fake_tavily)
    monkeypatch.setattr(manager, "_search_google", fake_google)

    ok, result = asyncio.run(manager.search("q", max_results="99"))

    assert ok is True
    assert result == "google-result"
    assert calls == [("tavily", "q", 10), ("google", "q", 10)]


def test_search_tavily_mode_falls_back_after_error(monkeypatch, web_search_mod, base_cfg):
    base_cfg.SEARCH_ENGINE = "tavily"
    base_cfg.TAVILY_API_KEY = "t-key"
    base_cfg.GOOGLE_SEARCH_API_KEY = "g-key"
    base_cfg.GOOGLE_SEARCH_CX = "g-cx"
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: False)
    manager = web_search_mod.WebSearchManager(base_cfg)

    async def fake_tavily(*_):
        return False, "[HATA] tavily"

    async def fake_google(*_):
        return True, "google-result"

    monkeypatch.setattr(manager, "_search_tavily", fake_tavily)
    monkeypatch.setattr(manager, "_search_google", fake_google)

    ok, result = asyncio.run(manager.search("q"))
    assert ok is True
    assert result == "google-result"


def test_search_returns_error_when_no_engines_available(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: False)
    manager = web_search_mod.WebSearchManager(base_cfg)

    ok, result = asyncio.run(manager.search("q"))

    assert ok is False
    assert "arama yapılamadı" in result.lower()


def test_search_docs_and_stackoverflow_query_building(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: False)
    manager = web_search_mod.WebSearchManager(base_cfg)

    captured = {}

    async def fake_search(query, max_results=None):
        captured["query"] = query
        captured["max_results"] = max_results
        return True, "ok"

    monkeypatch.setattr(manager, "search", fake_search)

    asyncio.run(manager.search_docs("fastapi", "routing"))
    assert captured["query"] == "fastapi routing official docs reference"
    assert captured["max_results"] == 5

    asyncio.run(manager.search_stackoverflow("asyncio timeout"))
    assert captured["query"] == "stackoverflow asyncio timeout"

    base_cfg.TAVILY_API_KEY = "key"
    manager2 = web_search_mod.WebSearchManager(base_cfg)
    monkeypatch.setattr(manager2, "search", fake_search)

    asyncio.run(manager2.search_docs("httpx", "stream"))
    assert "site:docs.python.org" in captured["query"]

    asyncio.run(manager2.search_stackoverflow("pytest"))
    assert captured["query"] == "site:stackoverflow.com pytest"


def test_fetch_url_success_and_error_mapping(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: False)
    manager = web_search_mod.WebSearchManager(base_cfg)

    async def ok_scrape(_):
        return "metin"

    monkeypatch.setattr(manager, "scrape_url", ok_scrape)
    ok, result = asyncio.run(manager.fetch_url("https://example.com"))
    assert ok is True
    assert "[URL: https://example.com]" in result

    async def err_scrape(_):
        return "Hata: Sayfa içeriği çekilemedi - zaman aşımı"

    monkeypatch.setattr(manager, "scrape_url", err_scrape)
    ok, result = asyncio.run(manager.fetch_url("https://example.com"))
    assert ok is False
    assert result.startswith("Hata: Sayfa içeriği çekilemedi")


def test_clean_html_and_truncate_logic(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: False)
    manager = web_search_mod.WebSearchManager(base_cfg)

    html = "<header>h</header><body><script>x</script><nav>n</nav><h1>Başlık</h1><p>İçerik</p></body>"
    cleaned = manager._clean_html(html)
    assert "Başlık" in cleaned
    assert "İçerik" in cleaned
    assert "h" not in cleaned
    assert "x" not in cleaned

    manager.FETCH_MAX_CHARS = 20
    text = "x" * 1500
    truncated = manager._truncate_content(text)
    assert truncated.endswith("... [İçerik çok uzun olduğu için kesildi]")
    assert len(truncated) > 1000


def test_search_tavily_disables_api_key_on_401(monkeypatch, web_search_mod, base_cfg):
    base_cfg.TAVILY_API_KEY = "t-key"
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: False)
    manager = web_search_mod.WebSearchManager(base_cfg)

    class _Resp:
        def raise_for_status(self):
            req = web_search_mod.httpx.Request("POST", "https://api.tavily.com/search")
            resp = web_search_mod.httpx.Response(status_code=401)
            raise web_search_mod.httpx.HTTPStatusError("auth", request=req, response=resp)

        def json(self):
            return {}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _Client)

    ok, result = asyncio.run(manager._search_tavily("q", 3))

    assert ok is False
    assert "[HATA] Tavily" in result
    assert manager.tavily_key == ""


def test_search_duckduckgo_timeout_path(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: True)
    manager = web_search_mod.WebSearchManager(base_cfg)

    class DummyAsyncDDGS:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self, query, max_results):
            return []

    monkeypatch.setitem(sys.modules, "duckduckgo_search", SimpleNamespace(AsyncDDGS=DummyAsyncDDGS))

    async def fake_wait_for(awaitable, *args, **kwargs):
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(web_search_mod.asyncio, "wait_for", fake_wait_for)

    ok, result = asyncio.run(manager._search_duckduckgo("q", 5))

    assert ok is False
    assert "Zaman aşımı" in result
