from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from types import MethodType, SimpleNamespace

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


def test_search_auto_fallbacks_from_tavily_no_results_to_google() -> None:
    cfg = SimpleNamespace(SEARCH_ENGINE="auto", TAVILY_API_KEY="tv", GOOGLE_SEARCH_API_KEY="gk", GOOGLE_SEARCH_CX="cx")
    manager = WebSearchManager(cfg)
    manager._ddg_available = False

    async def _tavily(_query: str, _n: int):
        return True, manager._mark_no_results("empty")

    async def _google(_query: str, _n: int):
        return True, "google result"

    manager._search_tavily = MethodType(lambda _self, q, n: _tavily(q, n), manager)
    manager._search_google = MethodType(lambda _self, q, n: _google(q, n), manager)

    ok, text = asyncio.run(manager.search("sidar"))
    assert ok is True
    assert text == "google result"


def test_search_tavily_disables_key_on_403(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = WebSearchManager(SimpleNamespace(SEARCH_ENGINE="tavily", TAVILY_API_KEY="secret"))

    class _Resp:
        status_code = 403

        def raise_for_status(self):
            req = httpx.Request("POST", "https://api.tavily.com/search")
            resp = httpx.Response(403, request=req)
            raise httpx.HTTPStatusError("forbidden", request=req, response=resp)

        def json(self):
            return {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return _Resp()

    monkeypatch.setattr("managers.web_search.httpx.AsyncClient", lambda *a, **k: _Client())

    ok, err = asyncio.run(manager._search_tavily("x", 2))
    assert ok is False
    assert "[HATA] Tavily" in err
    assert manager.tavily_key == ""


def test_fetch_url_wraps_scrape_errors() -> None:
    manager = WebSearchManager(None)

    async def _scrape(_url: str) -> str:
        return "Hata: Sayfa içeriği çekilemedi - HTTP 500"

    manager.scrape_url = _scrape
    ok, payload = asyncio.run(manager.fetch_url("https://example.com"))

    assert ok is False
    assert payload.startswith("Hata: Sayfa içeriği çekilemedi")
