from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from types import SimpleNamespace

import pytest

if "httpx" not in sys.modules and importlib.util.find_spec("httpx") is None:
    fake_httpx = types.ModuleType("httpx")

    class Request:
        def __init__(self, method: str, url: str):
            self.method = method
            self.url = url

    class Response:
        def __init__(self, status_code: int, request: Request | None = None):
            self.status_code = status_code
            self.request = request

    class HTTPStatusError(Exception):
        def __init__(self, message: str, *, request: Request, response: Response):
            super().__init__(message)
            self.request = request
            self.response = response

    class TimeoutException(Exception):
        pass

    class RequestError(Exception):
        pass

    class Timeout:
        def __init__(self, *_args, **_kwargs):
            pass

    fake_httpx.Request = Request
    fake_httpx.Response = Response
    fake_httpx.HTTPStatusError = HTTPStatusError
    fake_httpx.TimeoutException = TimeoutException
    fake_httpx.RequestError = RequestError
    fake_httpx.Timeout = Timeout
    fake_httpx.AsyncClient = object
    sys.modules["httpx"] = fake_httpx

if "bs4" not in sys.modules and importlib.util.find_spec("bs4") is None:
    fake_bs4 = types.ModuleType("bs4")

    class _Tag:
        def __init__(self, name: str):
            self.name = name

        def decompose(self):
            return None

    class BeautifulSoup:
        def __init__(self, html: str, _parser: str):
            self._html = html

        def __call__(self, names):
            return [_Tag(name) for name in names]

        def get_text(self, separator: str = " ", strip: bool = True):
            text = self._html.replace("<script>", "").replace("</script>", "")
            text = text.replace("<html>", "").replace("</html>", "")
            text = text.replace("<body>", "").replace("</body>", "")
            text = text.replace("<h1>", "").replace("</h1>", "")
            return text.strip() if strip else text

    fake_bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = fake_bs4

import httpx

from managers.web_search import WebSearchManager


class _FakeResponse:
    def __init__(self, payload=None, status_code: int = 200, text: str = ""):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text
        self.encoding = None

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", "https://example.test")
            resp = httpx.Response(self.status_code, request=req)
            raise httpx.HTTPStatusError("http error", request=req, response=resp)

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, get_response=None, post_response=None, get_exc=None, post_exc=None, **_kwargs):
        self._get_response = get_response
        self._post_response = post_response
        self._get_exc = get_exc
        self._post_exc = post_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *_args, **_kwargs):
        if self._get_exc is not None:
            raise self._get_exc
        return self._get_response

    async def post(self, *_args, **_kwargs):
        if self._post_exc is not None:
            raise self._post_exc
        return self._post_response


def _manager(**cfg_overrides) -> WebSearchManager:
    cfg_data = dict(
        SEARCH_ENGINE="auto",
        TAVILY_API_KEY="",
        GOOGLE_SEARCH_API_KEY="",
        GOOGLE_SEARCH_CX="",
        WEB_SEARCH_MAX_RESULTS=5,
        WEB_FETCH_TIMEOUT=7,
        WEB_SCRAPE_MAX_CHARS=1200,
    )
    cfg_data.update(cfg_overrides)
    cfg = SimpleNamespace(**cfg_data)
    manager = WebSearchManager(cfg)
    return manager


def test_search_tavily_success_formats_results(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(TAVILY_API_KEY="tavily-key")
    payload = {"results": [{"title": "T1", "content": "Body", "url": "https://a"}]}

    monkeypatch.setattr(
        "managers.web_search.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(post_response=_FakeResponse(payload=payload), **kwargs),
    )

    ok, text = asyncio.run(manager._search_tavily("python", 3))

    assert ok is True
    assert "Web Arama (Tavily)" in text
    assert "https://a" in text


def test_search_tavily_rate_limit_or_auth_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(TAVILY_API_KEY="tavily-key")

    # 429 rate limit
    monkeypatch.setattr(
        "managers.web_search.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(post_response=_FakeResponse(status_code=429), **kwargs),
    )
    ok_429, text_429 = asyncio.run(manager._search_tavily("python", 2))
    assert ok_429 is False
    assert "[HATA] Tavily" in text_429
    assert manager.tavily_key == "tavily-key"

    # 401 auth error should disable tavily key
    monkeypatch.setattr(
        "managers.web_search.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(post_response=_FakeResponse(status_code=401), **kwargs),
    )
    ok_401, text_401 = asyncio.run(manager._search_tavily("python", 2))
    assert ok_401 is False
    assert "[HATA] Tavily" in text_401
    assert manager.tavily_key == ""


def test_search_google_success_and_empty_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(GOOGLE_SEARCH_API_KEY="g", GOOGLE_SEARCH_CX="cx")

    monkeypatch.setattr(
        "managers.web_search.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(
            get_response=_FakeResponse(payload={"items": [{"title": "G1", "snippet": "s", "link": "https://g"}]}),
            **kwargs,
        ),
    )
    ok, text = asyncio.run(manager._search_google("python", 4))
    assert ok is True
    assert "Web Arama (Google)" in text

    monkeypatch.setattr(
        "managers.web_search.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(get_response=_FakeResponse(payload={"items": []}), **kwargs),
    )
    ok_empty, text_empty = asyncio.run(manager._search_google("python", 4))
    assert ok_empty is True
    assert "sonuç bulunamadı" in text_empty


def test_search_routing_fallback_from_tavily_to_google(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(SEARCH_ENGINE="tavily", TAVILY_API_KEY="t", GOOGLE_SEARCH_API_KEY="g", GOOGLE_SEARCH_CX="cx")
    manager._ddg_available = False

    async def _tavily_fail(_query, _n):
        return False, "boom"

    async def _google_ok(_query, _n):
        return True, "google-result"

    manager._search_tavily = _tavily_fail
    manager._search_google = _google_ok

    ok, text = asyncio.run(manager.search("fallback", max_results="bad-int"))

    assert ok is True
    assert text == "google-result"


def test_search_returns_global_error_when_no_engine_available() -> None:
    manager = _manager()
    manager.tavily_key = ""
    manager.google_key = ""
    manager.google_cx = ""
    manager._ddg_available = False

    ok, text = asyncio.run(manager.search("anything", max_results=99))

    assert ok is False
    assert "Web arama yapılamadı" in text


def test_scrape_url_success_timeout_and_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager()

    html_resp = _FakeResponse(text="<html><body><script>x</script><h1>Başlık</h1></body></html>")
    monkeypatch.setattr(
        "managers.web_search.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(get_response=html_resp, **kwargs),
    )
    text_ok = asyncio.run(manager.scrape_url("https://site"))
    assert "Başlık" in text_ok
    assert "script" not in text_ok.lower()

    monkeypatch.setattr(
        "managers.web_search.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(get_exc=httpx.TimeoutException("timeout"), **kwargs),
    )
    text_timeout = asyncio.run(manager.scrape_url("https://site"))
    assert "zaman aşımı" in text_timeout

    req = httpx.Request("GET", "https://site")
    rate_resp = httpx.Response(429, request=req)
    rate_exc = httpx.HTTPStatusError("rate limit", request=req, response=rate_resp)
    monkeypatch.setattr(
        "managers.web_search.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(get_exc=rate_exc, **kwargs),
    )
    text_429 = asyncio.run(manager.scrape_url("https://site"))
    assert "HTTP 429" in text_429


def test_fetch_url_and_helper_methods() -> None:
    manager = _manager()

    async def _scrape_ok(_url):
        return "clean text"

    async def _scrape_err(_url):
        return "Hata: Sayfa içeriği çekilemedi - test"

    manager.scrape_url = _scrape_ok
    ok, text = asyncio.run(manager.fetch_url("https://x"))
    assert ok is True
    assert "[URL: https://x]" in text

    manager.scrape_url = _scrape_err
    ok_err, text_err = asyncio.run(manager.fetch_url("https://x"))
    assert ok_err is False
    assert "Hata:" in text_err

    assert manager._truncate_content("a" * 1500).endswith("[İçerik çok uzun olduğu için kesildi]")
    manager.FETCH_MAX_CHARS = "bad"
    assert manager._truncate_content("abc") == "abc"

    normalized = manager._normalize_result_text(manager._mark_no_results("none"))
    assert normalized == "none"
    assert manager._is_actionable_result(True, "plain") is True
    assert manager._is_actionable_result(True, manager._mark_no_results("none")) is False


def test_search_docs_stackoverflow_status_repr_and_check_ddg(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(TAVILY_API_KEY="t", SEARCH_ENGINE="auto")

    called = {}

    async def _fake_search(query, max_results=None):
        called["query"] = query
        called["max_results"] = max_results
        return True, "ok"

    manager.search = _fake_search
    asyncio.run(manager.search_docs("fastapi", "routing"))
    assert "site:docs.python.org" in called["query"]

    manager.tavily_key = ""
    manager.google_key = ""
    manager.google_cx = ""
    asyncio.run(manager.search_stackoverflow("httpx timeout"))
    assert called["query"].startswith("stackoverflow ")

    manager._ddg_available = True
    assert manager.is_available() is True
    assert "DuckDuckGo" in manager.status()
    assert "engine=auto" in repr(manager)

    monkeypatch.setattr("builtins.__import__", lambda *args, **kwargs: (_ for _ in ()).throw(ImportError("no ddg")))
    assert WebSearchManager._check_ddg(manager) is False
