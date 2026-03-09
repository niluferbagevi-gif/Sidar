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


class _NoInt:
    def __int__(self):
        raise TypeError("cannot cast")


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


def test_init_with_none_config_and_basic_status_repr(monkeypatch, web_search_mod):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: False)
    manager = web_search_mod.WebSearchManager(config=None)

    assert manager.engine == "auto"
    assert manager.tavily_key == ""
    assert manager.google_key == ""
    assert manager.google_cx == ""
    assert manager.status() == "WebSearch: Kurulu veya yapılandırılmış motor yok."
    assert "engine=auto" in repr(manager)


def test_check_ddg_import_error_returns_false(monkeypatch, web_search_mod, base_cfg):
    manager = web_search_mod.WebSearchManager(base_cfg)

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "duckduckgo_search":
            raise ImportError("missing ddg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert manager._check_ddg() is False


def test_status_and_repr_all_engine_combinations(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: True)
    base_cfg.TAVILY_API_KEY = "t"
    base_cfg.GOOGLE_SEARCH_API_KEY = "g"
    base_cfg.GOOGLE_SEARCH_CX = "cx"
    manager = web_search_mod.WebSearchManager(base_cfg)

    text = manager.status()
    assert "Tavily" in text
    assert "Google" in text
    assert "DuckDuckGo" in text
    repr_text = repr(manager)
    assert "Tavily" in repr_text
    assert "Google" in repr_text
    assert "DuckDuckGo" in repr_text
    assert manager.is_available() is True


def test_search_clamps_invalid_max_results_typeerror_and_valueerror(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: True)
    base_cfg.SEARCH_ENGINE = "duckduckgo"
    manager = web_search_mod.WebSearchManager(base_cfg)

    calls = []

    async def fake_ddg(query, n):
        calls.append(n)
        return True, "ok"

    monkeypatch.setattr(manager, "_search_duckduckgo", fake_ddg)

    ok, _ = asyncio.run(manager.search("q", max_results=_NoInt()))
    assert ok is True
    ok, _ = asyncio.run(manager.search("q", max_results="abc"))
    assert ok is True
    assert calls == [manager.MAX_RESULTS, manager.MAX_RESULTS]


def test_search_google_and_duck_modes_direct_paths(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: True)

    base_cfg.SEARCH_ENGINE = "google"
    base_cfg.GOOGLE_SEARCH_API_KEY = "g"
    base_cfg.GOOGLE_SEARCH_CX = "cx"
    manager_g = web_search_mod.WebSearchManager(base_cfg)

    async def fake_google(*_):
        return True, manager_g._mark_no_results("none")

    monkeypatch.setattr(manager_g, "_search_google", fake_google)
    ok, text = asyncio.run(manager_g.search("q"))
    assert ok is True
    assert text == "none"

    base_cfg.SEARCH_ENGINE = "duckduckgo"
    manager_d = web_search_mod.WebSearchManager(base_cfg)

    async def fake_ddg(*_):
        return True, "duck text"

    monkeypatch.setattr(manager_d, "_search_duckduckgo", fake_ddg)
    ok, text = asyncio.run(manager_d.search("q"))
    assert ok is True
    assert text == "duck text"


def test_search_auto_falls_to_duckduckgo_after_no_result_markers(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: True)
    base_cfg.TAVILY_API_KEY = "t"
    base_cfg.GOOGLE_SEARCH_API_KEY = "g"
    base_cfg.GOOGLE_SEARCH_CX = "cx"
    manager = web_search_mod.WebSearchManager(base_cfg)

    async def no_t(*_):
        return True, manager._mark_no_results("t")

    async def no_g(*_):
        return True, manager._mark_no_results("g")

    async def yes_d(*_):
        return True, "duck-final"

    monkeypatch.setattr(manager, "_search_tavily", no_t)
    monkeypatch.setattr(manager, "_search_google", no_g)
    monkeypatch.setattr(manager, "_search_duckduckgo", yes_d)

    ok, text = asyncio.run(manager.search("q"))
    assert ok is True
    assert text == "duck-final"


def test_tavily_success_no_results_and_exceptions(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: False)
    base_cfg.TAVILY_API_KEY = "t"
    manager = web_search_mod.WebSearchManager(base_cfg)

    class _RespOK:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"title": "T1", "content": "Body", "url": "u"}]}

    class _RespEmpty(_RespOK):
        def json(self):
            return {"results": []}

    class _Client:
        def __init__(self, *args, **kwargs):
            self.mode = kwargs.get("mode", "ok")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return _RespOK()

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _Client)
    ok, text = asyncio.run(manager._search_tavily("qq", 2))
    assert ok is True
    assert "[Web Arama (Tavily): qq]" in text

    class _ClientEmpty(_Client):
        async def post(self, *args, **kwargs):
            return _RespEmpty()

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _ClientEmpty)
    ok, text = asyncio.run(manager._search_tavily("qq", 2))
    assert ok is True
    assert "Tavily'de sonuç bulunamadı" in text

    class _ClientHTTP(_Client):
        async def post(self, *args, **kwargs):
            req = web_search_mod.httpx.Request("POST", "x")
            raise web_search_mod.httpx.HTTPStatusError("boom", request=req, response=web_search_mod.httpx.Response(status_code=500))

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _ClientHTTP)
    ok, text = asyncio.run(manager._search_tavily("qq", 2))
    assert ok is False
    assert "[HATA] Tavily" in text

    class _ClientEx(_Client):
        async def post(self, *args, **kwargs):
            raise RuntimeError("kaboom")

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _ClientEx)
    ok, text = asyncio.run(manager._search_tavily("qq", 2))
    assert ok is False
    assert "kaboom" in text


def test_google_search_success_no_results_and_exception(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: False)
    base_cfg.GOOGLE_SEARCH_API_KEY = "g"
    base_cfg.GOOGLE_SEARCH_CX = "cx"
    manager = web_search_mod.WebSearchManager(base_cfg)

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return _Resp({"items": [{"title": "A", "snippet": "B", "link": "L"}]})

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _Client)
    ok, text = asyncio.run(manager._search_google("q", 2))
    assert ok is True
    assert "[Web Arama (Google): q]" in text

    class _ClientNo(_Client):
        async def get(self, *args, **kwargs):
            return _Resp({"items": []})

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _ClientNo)
    ok, text = asyncio.run(manager._search_google("q", 2))
    assert ok is True
    assert "Google'da sonuç bulunamadı" in text

    class _ClientEx(_Client):
        async def get(self, *args, **kwargs):
            raise RuntimeError("gerr")

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _ClientEx)
    ok, text = asyncio.run(manager._search_google("q", 2))
    assert ok is False
    assert "Google Search" in text


def test_duckduckgo_async_generator_and_sync_branch(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: True)
    manager = web_search_mod.WebSearchManager(base_cfg)

    class _AsyncDDGS:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self, query, max_results):
            async def _gen():
                yield {"title": "T", "body": "B", "href": "H"}
            return _gen()

    monkeypatch.setitem(sys.modules, "duckduckgo_search", SimpleNamespace(AsyncDDGS=_AsyncDDGS))
    ok, text = asyncio.run(manager._search_duckduckgo("q", 2))
    assert ok is True
    assert "DuckDuckGo" in text

    class _DDGS:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def text(self, query, max_results):
            return [{"title": "S", "body": "SB", "href": "SH"}]

    monkeypatch.setitem(sys.modules, "duckduckgo_search", SimpleNamespace(DDGS=_DDGS))
    ok, text = asyncio.run(manager._search_duckduckgo("q", 2))
    assert ok is True
    assert "S" in text


def test_duckduckgo_general_exception(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: True)
    manager = web_search_mod.WebSearchManager(base_cfg)
    monkeypatch.delitem(sys.modules, "duckduckgo_search", raising=False)
    ok, text = asyncio.run(manager._search_duckduckgo("q", 2))
    assert ok is False
    assert "[HATA] DuckDuckGo" in text


def test_scrape_url_error_branches_and_truncate_noop(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: False)
    manager = web_search_mod.WebSearchManager(base_cfg)

    class _ClientTimeout:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            raise web_search_mod.httpx.TimeoutException("t")

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _ClientTimeout)
    text = asyncio.run(manager.scrape_url("https://e"))
    assert "zaman aşımı" in text

    class _ClientRequest(_ClientTimeout):
        async def get(self, *args, **kwargs):
            raise web_search_mod.httpx.RequestError("r")

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _ClientRequest)
    text = asyncio.run(manager.scrape_url("https://e"))
    assert "bağlantı/istek hatası" in text

    class _ClientHTTP(_ClientTimeout):
        async def get(self, *args, **kwargs):
            req = web_search_mod.httpx.Request("GET", "x")
            raise web_search_mod.httpx.HTTPStatusError("h", request=req, response=web_search_mod.httpx.Response(status_code=418))

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _ClientHTTP)
    text = asyncio.run(manager.scrape_url("https://e"))
    assert "HTTP 418" in text

    class _ClientEx(_ClientTimeout):
        async def get(self, *args, **kwargs):
            raise RuntimeError("unknown")

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _ClientEx)
    text = asyncio.run(manager.scrape_url("https://e"))
    assert "unknown" in text

    short = manager._truncate_content("abc")
    assert short == "abc"


def test_class_helpers_and_fake_helper_classes_for_test_coverage(monkeypatch, web_search_mod):
    marked = web_search_mod.WebSearchManager._mark_no_results("x")
    assert web_search_mod.WebSearchManager._is_actionable_result(True, marked) is False
    assert web_search_mod.WebSearchManager._is_actionable_result(True, "ok") is True
    assert web_search_mod.WebSearchManager._normalize_result_text(marked) == "x"

    # test dosyasındaki sahte sınıfların satırlarını da çalıştır
    err = _FakeHTTPStatusError("m", request=_FakeRequest("GET", "u"), response=_FakeResponse(status_code=500))
    assert err.response.status_code == 500
    assert isinstance(_FakeRequestError("a"), Exception)
    assert isinstance(_FakeTimeoutException("a"), Exception)
    assert _FakeTimeout(1, connect=2).kwargs["connect"] == 2

    client = _FakeAsyncClient()
    assert asyncio.run(client.__aenter__()) is client
    assert asyncio.run(client.post("u")).status_code == 200
    assert "ok" in asyncio.run(client.get("u")).text
    assert asyncio.run(client.__aexit__(None, None, None)) is False

    tag_soup = _FakeSoup("<script>x</script><p>a</p>", "html.parser")
    tags = tag_soup(["script"])
    assert tags
    tags[0].decompose()
    assert "script" not in tag_soup.html


def test_search_auto_fallback_all_paths(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: True)
    base_cfg.SEARCH_ENGINE = "unknown_engine"  # direct bypass
    base_cfg.TAVILY_API_KEY = "t"
    base_cfg.GOOGLE_SEARCH_API_KEY = "g"
    base_cfg.GOOGLE_SEARCH_CX = "cx"
    manager = web_search_mod.WebSearchManager(base_cfg)

    async def fake_tavily(*_):
        return False, "tavily fail"

    async def fake_google(*_):
        return True, manager._mark_no_results("google no results")

    async def fake_ddg(*_):
        return True, "ddg success"

    monkeypatch.setattr(manager, "_search_tavily", fake_tavily)
    monkeypatch.setattr(manager, "_search_google", fake_google)
    monkeypatch.setattr(manager, "_search_duckduckgo", fake_ddg)

    ok, text = asyncio.run(manager.search("q"))
    assert ok is True
    assert text == "ddg success"


def test_search_docs_fallback_query(monkeypatch, web_search_mod, base_cfg):
    base_cfg.TAVILY_API_KEY = ""
    base_cfg.GOOGLE_SEARCH_API_KEY = ""
    manager = web_search_mod.WebSearchManager(base_cfg)

    captured = {}

    async def fake_search(q, max_results=None):
        captured["q"] = q
        return True, "ok"

    monkeypatch.setattr(manager, "search", fake_search)
    asyncio.run(manager.search_docs("lib", "top"))
    assert "official docs reference" in captured["q"]


def test_scrape_url_requesterror_path(monkeypatch, web_search_mod, base_cfg):
    manager = web_search_mod.WebSearchManager(base_cfg)

    class _ClientReqErr:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise web_search_mod.httpx.RequestError("req err")

    monkeypatch.setattr(web_search_mod.httpx, "AsyncClient", _ClientReqErr)
    text = asyncio.run(manager.scrape_url("http://err"))
    assert "bağlantı/istek hatası" in text


def test_duckduckgo_general_exception_242(monkeypatch, web_search_mod, base_cfg):
    monkeypatch.setattr(web_search_mod.WebSearchManager, "_check_ddg", lambda self: True)
    manager = web_search_mod.WebSearchManager(base_cfg)

    class DummyAsyncDDGS:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def text(self, query, max_results):
            raise ValueError("Random DDG Error")

    monkeypatch.setitem(sys.modules, "duckduckgo_search", SimpleNamespace(AsyncDDGS=DummyAsyncDDGS))
    ok, text = asyncio.run(manager._search_duckduckgo("q", 5))
    assert ok is False
    assert "Random DDG Error" in text



def test_web_search_remaining_exceptions_and_stackoverflow(monkeypatch, web_search_mod, base_cfg):
    base_cfg.TAVILY_API_KEY = "t"
    base_cfg.GOOGLE_SEARCH_API_KEY = "g"
    base_cfg.GOOGLE_SEARCH_CX = "cx"
    mgr = web_search_mod.WebSearchManager(base_cfg)

    # Satır 117: Tavily 500 Server Error (401/403 olmayan HTTP hatası)
    async def mock_tavily_err(*args, **kwargs):
        req = web_search_mod.httpx.Request("POST", "http://t")
        resp = web_search_mod.httpx.Response(status_code=500)
        raise web_search_mod.httpx.HTTPStatusError("500 Err", request=req, response=resp)

    monkeypatch.setattr(web_search_mod.httpx.AsyncClient, "post", mock_tavily_err)
    asyncio.run(mgr._search_tavily("q", 1))

    # Satır 132: Google genel API Exception'ı
    async def mock_google_err(*args, **kwargs):
        raise Exception("Google generic error")

    monkeypatch.setattr(web_search_mod.httpx.AsyncClient, "get", mock_google_err)
    asyncio.run(mgr._search_google("q", 1))

    # Satır 242: DuckDuckGo bekleme sırasında genel Exception
    async def mock_ddg_err(*args, **kwargs):
        raise Exception("DDG generic error")

    monkeypatch.setattr(asyncio, "wait_for", mock_ddg_err)
    asyncio.run(mgr._search_duckduckgo("q", 1))

    # Satır 262: scrape_url HTTP RequestError (Timeout değil, URL çözülememe vs.)
    async def mock_req_err(*args, **kwargs):
        raise web_search_mod.httpx.RequestError("ReqErr")

    monkeypatch.setattr(web_search_mod.httpx.AsyncClient, "get", mock_req_err)
    asyncio.run(mgr.scrape_url("http://test"))

    # Satır 296-301: search_stackoverflow her iki dal (if/else)
    async def fake_search(q, max_results):
        return True, q

    monkeypatch.setattr(mgr, "search", fake_search)

    # 1. Dal: Google/Tavily aktifken (site: filter)
    _, q1 = asyncio.run(mgr.search_stackoverflow("python array"))
    assert "site:stackoverflow.com" in q1

    # 2. Dal: Sadece DuckDuckGo aktifken (düz arama)
    mgr.tavily_key = ""
    mgr.google_key = ""
    _, q2 = asyncio.run(mgr.search_stackoverflow("python array"))
    assert "stackoverflow python array" in q2
