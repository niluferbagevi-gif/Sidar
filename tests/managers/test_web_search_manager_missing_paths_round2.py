from __future__ import annotations

import asyncio
import builtins
import importlib.util
import sys
import types
from types import SimpleNamespace

import pytest


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

    class Request:
        def __init__(self, method: str, url: str) -> None:
            self.method = method
            self.url = url

    class Response:
        def __init__(self, status_code: int, request=None):
            self.status_code = status_code
            self.request = request

    class HTTPStatusError(Exception):
        def __init__(self, message: str, request=None, response=None) -> None:
            super().__init__(message)
            self.request = request
            self.response = response

    class AsyncClient:
        def __init__(self, *args, **kwargs):
            return None

    fake_httpx.Timeout = Timeout
    fake_httpx.Request = Request
    fake_httpx.Response = Response
    fake_httpx.HTTPStatusError = HTTPStatusError
    fake_httpx.TimeoutException = Exception
    fake_httpx.RequestError = Exception
    fake_httpx.AsyncClient = AsyncClient
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

import httpx
from managers.web_search import WebSearchManager


def test_check_ddg_import_error_path(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WebSearchManager(SimpleNamespace(SEARCH_ENGINE="auto"))

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "duckduckgo_search":
            raise ImportError("missing ddg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert manager._check_ddg() is False


def test_status_and_repr_with_all_engines() -> None:
    manager = WebSearchManager(
        SimpleNamespace(
            SEARCH_ENGINE="auto",
            TAVILY_API_KEY="tv",
            GOOGLE_SEARCH_API_KEY="gk",
            GOOGLE_SEARCH_CX="cx",
        )
    )
    manager._ddg_available = True

    status = manager.status()
    assert "Tavily" in status
    assert "Google" in status
    assert "DuckDuckGo" in status
    assert "AUTO" in status

    rep = repr(manager)
    assert "engine=auto" in rep
    assert "Tavily" in rep


def test_search_engine_specific_branches_and_fallbacks() -> None:
    manager = WebSearchManager(
        SimpleNamespace(
            SEARCH_ENGINE="tavily",
            TAVILY_API_KEY="tv",
            GOOGLE_SEARCH_API_KEY="gk",
            GOOGLE_SEARCH_CX="cx",
        )
    )
    manager._ddg_available = True

    async def _tavily(_q: str, _n: int):
        return False, "[HATA] Tavily: boom"

    async def _google(_q: str, _n: int):
        return True, "google ok"

    manager._search_tavily = _tavily
    manager._search_google = _google

    ok, text = asyncio.run(manager.search("sidar", max_results="abc"))
    assert ok is True
    assert text == "google ok"

    manager.engine = "google"
    ok2, text2 = asyncio.run(manager.search("sidar", max_results=4))
    assert ok2 is True
    assert text2 == "google ok"

    manager.engine = "duckduckgo"

    async def _ddg(_q: str, _n: int):
        return True, "ddg ok"

    manager._search_duckduckgo = _ddg
    ok3, text3 = asyncio.run(manager.search("sidar", max_results=3))
    assert ok3 is True
    assert text3 == "ddg ok"


def test_search_auto_falls_to_ddg_when_google_not_actionable() -> None:
    manager = WebSearchManager(
        SimpleNamespace(
            SEARCH_ENGINE="auto",
            TAVILY_API_KEY="",
            GOOGLE_SEARCH_API_KEY="gk",
            GOOGLE_SEARCH_CX="cx",
        )
    )
    manager._ddg_available = True

    async def _google(_q: str, _n: int):
        return True, manager._mark_no_results("nope")

    async def _ddg(_q: str, _n: int):
        return True, "[NO_RESULTS] cleaned"

    manager._search_google = _google
    manager._search_duckduckgo = _ddg

    ok, text = asyncio.run(manager.search("sidar", max_results=10))
    assert ok is True
    assert text == "cleaned"


def test_search_tavily_success_empty_http_error_and_generic_error(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WebSearchManager(SimpleNamespace(SEARCH_ENGINE="auto", TAVILY_API_KEY="tv"))

    class _RespOK:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {"title": "T1", "content": "Body", "url": "https://a"},
                    {"title": "T2", "content": "", "url": "https://b"},
                ]
            }

    class _ClientOK:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return _RespOK()

    monkeypatch.setattr("managers.web_search.httpx.AsyncClient", lambda *a, **k: _ClientOK())
    ok, text = asyncio.run(manager._search_tavily("q", 2))
    assert ok is True
    assert "[Web Arama (Tavily): q]" in text
    assert "1. **T1**" in text

    class _RespHTTP500:
        status_code = 500

        def raise_for_status(self):
            req = httpx.Request("POST", "https://api.tavily.com/search")
            resp = httpx.Response(500, request=req)
            raise httpx.HTTPStatusError("server", request=req, response=resp)

    class _ClientHTTP500(_ClientOK):
        async def post(self, *_args, **_kwargs):
            return _RespHTTP500()

    monkeypatch.setattr("managers.web_search.httpx.AsyncClient", lambda *a, **k: _ClientHTTP500())
    ok2, text2 = asyncio.run(manager._search_tavily("q", 2))
    assert ok2 is False
    assert "[HATA] Tavily" in text2

    class _ClientExplodes(_ClientOK):
        async def post(self, *_args, **_kwargs):
            raise RuntimeError("explode")

    monkeypatch.setattr("managers.web_search.httpx.AsyncClient", lambda *a, **k: _ClientExplodes())
    ok3, text3 = asyncio.run(manager._search_tavily("q", 2))
    assert ok3 is False
    assert "explode" in text3


def test_search_google_success_empty_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WebSearchManager(
        SimpleNamespace(SEARCH_ENGINE="google", GOOGLE_SEARCH_API_KEY="gk", GOOGLE_SEARCH_CX="cx")
    )

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, payload=None, err: Exception | None = None):
            self._payload = payload
            self._err = err

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            if self._err:
                raise self._err
            return _Resp(self._payload)

    monkeypatch.setattr(
        "managers.web_search.httpx.AsyncClient",
        lambda *a, **k: _Client(payload={"items": [{"title": "G", "snippet": "S", "link": "https://g"}]}),
    )
    ok, text = asyncio.run(manager._search_google("x", 2))
    assert ok is True
    assert "[Web Arama (Google): x]" in text

    monkeypatch.setattr("managers.web_search.httpx.AsyncClient", lambda *a, **k: _Client(payload={"items": []}))
    ok2, text2 = asyncio.run(manager._search_google("x", 2))
    assert ok2 is True
    assert "Google'da sonuç bulunamadı" in text2

    monkeypatch.setattr(
        "managers.web_search.httpx.AsyncClient", lambda *a, **k: _Client(err=RuntimeError("google boom"))
    )
    ok3, text3 = asyncio.run(manager._search_google("x", 2))
    assert ok3 is False
    assert "google boom" in text3


def test_search_duckduckgo_async_and_sync_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WebSearchManager(SimpleNamespace(SEARCH_ENGINE="duckduckgo"))

    fake_mod = types.ModuleType("duckduckgo_search")

    class _AsyncDDGS:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def text(self, *_args, **_kwargs):
            async def _agen():
                yield {"title": "A", "body": "B", "href": "https://d"}

            return _agen()

    fake_mod.AsyncDDGS = _AsyncDDGS
    monkeypatch.setitem(sys.modules, "duckduckgo_search", fake_mod)

    ok, text = asyncio.run(manager._search_duckduckgo("q", 1))
    assert ok is True
    assert "DuckDuckGo" in text

    class _DDGS:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def text(self, *_args, **_kwargs):
            return [{"title": "S", "body": "Body", "href": "https://s"}]

    delattr(fake_mod, "AsyncDDGS")
    fake_mod.DDGS = _DDGS
    ok2, text2 = asyncio.run(manager._search_duckduckgo("q", 1))
    assert ok2 is True
    assert "1. **S**" in text2


def test_search_duckduckgo_timeout_and_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WebSearchManager(SimpleNamespace(SEARCH_ENGINE="duckduckgo"))

    fake_mod = types.ModuleType("duckduckgo_search")

    class _AsyncDDGS:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def text(self, *_args, **_kwargs):
            return []

    fake_mod.AsyncDDGS = _AsyncDDGS
    monkeypatch.setitem(sys.modules, "duckduckgo_search", fake_mod)

    async def _raise_timeout(*_args, **_kwargs):
        raise asyncio.TimeoutError

    monkeypatch.setattr("managers.web_search.asyncio.wait_for", _raise_timeout)
    ok, text = asyncio.run(manager._search_duckduckgo("q", 1))
    assert ok is False
    assert "Zaman aşımı" in text

    monkeypatch.setitem(sys.modules, "duckduckgo_search", None)
    ok2, text2 = asyncio.run(manager._search_duckduckgo("q", 1))
    assert ok2 is False
    assert "[HATA] DuckDuckGo" in text2


def test_scrape_url_success_and_more_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WebSearchManager(SimpleNamespace(SEARCH_ENGINE="auto"))
    class _TimeoutExc(Exception):
        pass
    class _ReqExc(Exception):
        pass
    monkeypatch.setattr("managers.web_search.httpx.TimeoutException", _TimeoutExc)
    monkeypatch.setattr("managers.web_search.httpx.RequestError", _ReqExc)

    class _Resp:
        text = "<html><body><h1>Başlık</h1></body></html>"

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return _Resp()

    monkeypatch.setattr("managers.web_search.httpx.AsyncClient", lambda *a, **k: _Client())
    text = asyncio.run(manager.scrape_url("https://example.com"))
    assert "Başlık" in text

    class _HTTP500Client(_Client):
        async def get(self, *_args, **_kwargs):
            req = httpx.Request("GET", "https://example.com")
            resp = httpx.Response(500, request=req)
            raise httpx.HTTPStatusError("boom", request=req, response=resp)

    monkeypatch.setattr("managers.web_search.httpx.AsyncClient", lambda *a, **k: _HTTP500Client())
    err = asyncio.run(manager.scrape_url("https://example.com"))
    assert "HTTP 500" in err

    class _GenericClient(_Client):
        async def get(self, *_args, **_kwargs):
            raise RuntimeError("unknown")

    monkeypatch.setattr("managers.web_search.httpx.AsyncClient", lambda *a, **k: _GenericClient())
    err2 = asyncio.run(manager.scrape_url("https://example.com"))
    assert "unknown" in err2

    async def _ok_scrape(_url: str) -> str:
        return "içerik"

    manager.scrape_url = _ok_scrape
    ok, payload = asyncio.run(manager.fetch_url("https://example.com"))
    assert ok is True
    assert payload.startswith("[URL: https://example.com]")


def test_truncate_and_query_helpers_more_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WebSearchManager(SimpleNamespace(SEARCH_ENGINE="auto", TAVILY_API_KEY="", GOOGLE_SEARCH_API_KEY="", GOOGLE_SEARCH_CX=""))

    manager.FETCH_MAX_CHARS = "bad"
    out = manager._truncate_content("kısa")
    assert out == "kısa"

    captured = {}

    async def _fake_search(query: str, max_results: int | None = None):
        captured["q"] = query
        captured["n"] = max_results
        return True, "ok"

    monkeypatch.setattr(manager, "search", _fake_search)
    asyncio.run(manager.search_docs("fastapi", ""))
    assert "official docs reference" in captured["q"]

    manager.tavily_key = "tv"
    asyncio.run(manager.search_stackoverflow("pytest mock"))
    assert captured["q"].startswith("site:stackoverflow.com")
    assert captured["n"] == 5
