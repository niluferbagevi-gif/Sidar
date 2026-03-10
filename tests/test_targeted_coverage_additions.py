import asyncio
import types
from types import SimpleNamespace

from tests.test_github_manager_runtime import GM, _manager
from tests.test_llm_client_runtime import _collect, _load_llm_client_module
from tests.test_web_search_runtime import _load_web_search_module


def test_llmclient_stream_gemini_generator_branches(monkeypatch):
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=5)

    class _GemClient(llm_mod.GeminiClient):
        def __init__(self, _cfg):
            self.config = _cfg

        async def _stream_gemini_generator(self, _response_stream):
            yield "g1"

    fac = llm_mod.LLMClient("ollama", cfg)
    fac._client = _GemClient(cfg)
    out = asyncio.run(_collect(fac._stream_gemini_generator(object())))
    assert out == ["g1"]

    class _FakeGemini:
        def __init__(self, _cfg):
            pass

        async def _stream_gemini_generator(self, _response_stream):
            yield "fallback"

    monkeypatch.setattr(llm_mod, "GeminiClient", _FakeGemini)
    fac2 = llm_mod.LLMClient("ollama", cfg)
    out2 = asyncio.run(_collect(fac2._stream_gemini_generator(object())))
    assert out2 == ["fallback"]


def test_ollama_chat_sets_total_ms_and_stream_trailing_invalid_json(monkeypatch):
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=5, USE_GPU=False)
    client = llm_mod.OllamaClient(cfg)

    class _Span:
        def __init__(self):
            self.attrs = {}

        def set_attribute(self, k, v):
            self.attrs[k] = v

    class _CM:
        def __init__(self, span):
            self.span = span

        def __enter__(self):
            return self.span

        def __exit__(self, *args):
            return False

    class _Tracer:
        def __init__(self):
            self.span = _Span()

        def start_as_current_span(self, _):
            return _CM(self.span)

    monkeypatch.setattr(llm_mod, "_get_tracer", lambda _cfg: _Tracer())

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "ok"}}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *_args, **_kwargs):
            return _Resp()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    result = asyncio.run(client.chat([{"role": "user", "content": "u"}], stream=False, json_mode=False))
    assert result == "ok"

    class _RespStream:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b'{"message":{"content":"ok"}}\xff'

    class _SCtx:
        async def __aenter__(self):
            return _RespStream()

        async def __aexit__(self, *args):
            return None

    class _ClientStream(_Client):
        def stream(self, *_args, **_kwargs):
            return _SCtx()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _ClientStream)
    out = asyncio.run(_collect(client._stream_response("u", {"a": 1}, timeout=llm_mod.httpx.Timeout(5))))
    assert out == []


def test_web_search_return_and_scrape_success_lines(monkeypatch):
    mod = _load_web_search_module(monkeypatch)
    cfg = SimpleNamespace(
        SEARCH_ENGINE="tavily",
        TAVILY_API_KEY="tk",
        GOOGLE_SEARCH_API_KEY="",
        GOOGLE_SEARCH_CX="",
        WEB_SEARCH_MAX_RESULTS=5,
        WEB_FETCH_TIMEOUT=10,
        WEB_SCRAPE_MAX_CHARS=12000,
    )
    monkeypatch.setattr(mod.WebSearchManager, "_check_ddg", lambda self: False)
    manager = mod.WebSearchManager(cfg)

    async def tavily_ok(*_):
        return True, "plain"

    monkeypatch.setattr(manager, "_search_tavily", tavily_ok)
    ok, text = asyncio.run(manager.search("q"))
    assert ok is True and text == "plain"

    class _Resp:
        text = "<html><body>icerik</body></html>"
        encoding = None

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *_args, **_kwargs):
            return _Resp()

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
    text2 = asyncio.run(manager.scrape_url("https://example.com"))
    assert "icerik" in text2


def test_github_manager_missing_branches():
    class _Repo:
        full_name = "org/repo"
        default_branch = "main"

        def get_pulls(self, **kwargs):
            raise RuntimeError("repo-info")

        def get_contents(self, file_path, **kwargs):
            if kwargs.get("ref"):
                raise RuntimeError("with-ref")
            if file_path == "README":
                return types.SimpleNamespace(type="file", name="README")
            return types.SimpleNamespace(name="README", decoded_content=b"ok")

        def create_file(self, **kwargs):
            raise RuntimeError("create-boom")

        def get_pull(self, _num):
            class _PR:
                title = "T"

                def get_files(self):
                    return []

            return _PR()

    class _GH:
        @staticmethod
        def get_user():
            return types.SimpleNamespace(get_repos=lambda **_k: [types.SimpleNamespace(full_name="x/y", default_branch="main")])

    m = _manager(repo=_Repo(), gh=_GH(), available=True, token="t")

    ok, msg = m.list_repos(limit=0)
    assert ok is True and msg == []

    ok, info = m.get_repo_info()
    assert ok is False and "alınamadı" in info

    ok, read = m.read_remote_file("README", ref="dev")
    assert ok is False and "okunamadı" in read

    ok, listed = m.list_files(path="README")
    assert ok is True and "README" in listed

    ok, msg2 = m.create_or_update_file("x", "y", "m")
    assert ok is False and "yazma hatası" in msg2

    ok, diff = m.get_pull_request_diff(1)
    assert ok is True and "kod dosyası bulunmuyor" in diff


def test_ollama_stream_trailing_block_with_custom_decoder(monkeypatch):
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=5, USE_GPU=False)
    client = llm_mod.OllamaClient(cfg)

    class _Decoder:
        def decode(self, _raw, final=False):
            if final:
                return '\n{"message":{"content":"trail"}}\n{bad-json}'
            return ""

    monkeypatch.setattr(llm_mod.codecs, "getincrementaldecoder", lambda *_a, **_k: (lambda **_kw: _Decoder()))

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            if False:
                yield b""

    class _Ctx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *args):
            return None

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, *_args, **_kwargs):
            return _Ctx()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    out = asyncio.run(_collect(client._stream_response("u", {"a": 1}, timeout=llm_mod.httpx.Timeout(5))))
    assert out == ["trail"]


def test_web_search_auto_tavily_actionable_and_ddg_list_no_results(monkeypatch):
    mod = _load_web_search_module(monkeypatch)
    cfg = SimpleNamespace(
        SEARCH_ENGINE="auto",
        TAVILY_API_KEY="tk",
        GOOGLE_SEARCH_API_KEY="",
        GOOGLE_SEARCH_CX="",
        WEB_SEARCH_MAX_RESULTS=5,
        WEB_FETCH_TIMEOUT=10,
        WEB_SCRAPE_MAX_CHARS=12000,
    )
    monkeypatch.setattr(mod.WebSearchManager, "_check_ddg", lambda self: True)
    manager = mod.WebSearchManager(cfg)

    async def tavily_ok(*_):
        return True, "ACTION"

    monkeypatch.setattr(manager, "_search_tavily", tavily_ok)
    ok, text = asyncio.run(manager.search("q"))
    assert ok is True and text == "ACTION"

    class _AsyncDDGS:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def text(self, query, max_results):
            if query == "none":
                return []
            return [{"title": "T", "body": "B", "href": "H"}]

    monkeypatch.setitem(__import__("sys").modules, "duckduckgo_search", types.SimpleNamespace(AsyncDDGS=_AsyncDDGS))
    ok1, txt1 = asyncio.run(manager._search_duckduckgo("have", 3))
    assert ok1 is True and "DuckDuckGo" in txt1

    ok2, txt2 = asyncio.run(manager._search_duckduckgo("none", 3))
    assert ok2 is True and "sonuç bulunamadı" in txt2


def test_github_manager_extensionless_not_in_safe_list_hits_guard():
    class _Repo:
        def get_contents(self, *_args, **_kwargs):
            return types.SimpleNamespace(name="secret", decoded_content=b"x")

    m = _manager(repo=_Repo(), gh=None, available=True, token="t")
    ok, msg = m.read_remote_file("secret")
    assert ok is False
    assert "güvenli listede değil" in msg


def test_ollama_stream_trailing_valid_json_without_newline(monkeypatch):
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=5, USE_GPU=False)
    client = llm_mod.OllamaClient(cfg)

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b'{"message":{"content":"son_kelime"}}'

    class _Ctx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *args):
            return None

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, *_args, **_kwargs):
            return _Ctx()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    out = asyncio.run(_collect(client._stream_response("u", {"a": 1}, timeout=llm_mod.httpx.Timeout(5))))
    assert out == ["son_kelime"]


def test_ollama_stream_trailing_newline_message_content_branch(monkeypatch):
    """_stream_response trailing-decoder while-loop içinde message.content dalını zorlar."""
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=5, USE_GPU=False)
    client = llm_mod.OllamaClient(cfg)

    class _Decoder:
        def decode(self, _raw, final=False):
            if final:
                return '\n{"message":{"content":"tail-hit"}}\n'
            return ""

    monkeypatch.setattr(llm_mod.codecs, "getincrementaldecoder", lambda *_a, **_k: (lambda **_kw: _Decoder()))

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            if False:
                yield b""

    class _Ctx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *args):
            return None

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, *_args, **_kwargs):
            return _Ctx()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    out = asyncio.run(_collect(client._stream_response("u", {"a": 1}, timeout=llm_mod.httpx.Timeout(5))))
    assert out == ["tail-hit"]
