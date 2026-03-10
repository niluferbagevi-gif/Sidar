import asyncio
import types
from types import SimpleNamespace

from tests.test_github_manager_runtime import GM, _manager
from tests.test_llm_client_runtime import _collect, _load_llm_client_module
from tests.test_rag_runtime_extended import _load_rag_module, _new_store
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


def test_ollama_stream_trailing_exact_buffer_hit(monkeypatch):
    """chat(stream=True) ile sonda \n olmayan geçerli JSON'un trailing parse ile dönmesini doğrular."""
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=5, USE_GPU=False)
    client = llm_mod.OllamaClient(cfg)

    class _Resp:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b'{"message": {"content": "trailing_success"}}'

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
    stream_iter = asyncio.run(client.chat([{"role": "user", "content": "hi"}], stream=True, json_mode=False))
    chunks = asyncio.run(_collect(stream_iter))
    assert "trailing_success" in chunks


def test_rag_exception_paths_for_fts_chunking_and_chroma_delete(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)

    # _init_fts genel exception yolu (236-238)
    st = mod.DocumentStore.__new__(mod.DocumentStore)
    st.store_dir = tmp_path
    st._index = {}
    import sqlite3
    monkeypatch.setattr(sqlite3, "connect", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fts down")))
    st._init_fts()
    assert st._bm25_available is False

    # _recursive_chunk_text force split yolu (280-281)
    force_chunks = st._recursive_chunk_text("abcdefgh", size=2, overlap=1)
    assert force_chunks and all(len(c) <= 2 for c in force_chunks)

    # delete_document içinde Chroma delete exception yolu (476-480)
    store = _new_store(mod, tmp_path)
    doc_id = store.add_document("T", "icerik", session_id="global")

    class _BrokenCol:
        def delete(self, **kwargs):
            raise RuntimeError("chroma delete fail")

    store._chroma_available = True
    store.collection = _BrokenCol()
    msg = store.delete_document(doc_id, session_id="global")
    assert "Belge silindi" in msg


def test_ollama_stream_trailing_split_invalid_then_valid_hits_jsondecode_continue(monkeypatch):
    """trailing while-loop içinde hem JSONDecodeError(218-219) hem valid content yolunu çalıştırır."""
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=5, USE_GPU=False)
    client = llm_mod.OllamaClient(cfg)

    class _Decoder:
        def decode(self, _raw, final=False):
            if final:
                return '\n{bad-json}\n{"message":{"content":"after-bad"}}\n'
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
    assert out == ["after-bad"]


def test_web_server_and_agent_error_surface_runtime_stubs(monkeypatch):
    from tests.test_web_server_runtime import _load_web_server, _make_agent

    ws_mod = _load_web_server()
    fake_agent, _calls = _make_agent(ai_provider="ollama", ollama_online=False)

    async def _fake_get_agent():
        return fake_agent

    monkeypatch.setattr(ws_mod, "get_agent", _fake_get_agent)

    # web server fonksiyon yolları
    sess = asyncio.run(ws_mod.get_sessions())
    assert getattr(sess, "status_code", 0) == 200
    rag_res = asyncio.run(ws_mod.rag_search(q="", mode="auto", top_k=1))
    assert getattr(rag_res, "status_code", 0) in (200, 400)

    # agent tarafında bilinmeyen tool / parse fallback
    from tests.test_sidar_agent_runtime import _make_agent_for_runtime, SA_MOD

    ag = _make_agent_for_runtime()
    ag._tools = {}
    ok_unknown = asyncio.run(ag._execute_tool("olmayan_tool_xyz", {"x": 1}))
    assert ok_unknown is None or "Bilinmeyen" in str(ok_unknown) or "Unknown" in str(ok_unknown)

    ag.cfg.BASE_DIR = "."

    async def _noop_audit(*_a, **_k):
        return None

    ag._log_audit = _noop_audit

    def _bad_parse(_name, _arg):
        raise RuntimeError("parse fail")

    monkeypatch.setattr(SA_MOD, "parse_tool_argument", _bad_parse)

    async def _ok_handler(_arg):
        return "ok"

    ag._tools = {"write_file": _ok_handler}
    out = asyncio.run(ag._execute_tool("write_file", {"bad": 1}))
    assert out == "ok"


def test_ollama_stream_transient_json_error_then_success_in_trailing_loop(monkeypatch):
    """Trailing parse döngüsünde ilk JSON decode hatası sonrası ikinci satırın başarıyla üretilmesini doğrular."""
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(OLLAMA_URL="http://localhost:11434/api", OLLAMA_TIMEOUT=5, USE_GPU=False)
    client = llm_mod.OllamaClient(cfg)

    real_loads = llm_mod.json.loads
    state = {"n": 0}

    def flaky_loads(payload):
        state["n"] += 1
        if state["n"] == 1:
            raise llm_mod.json.JSONDecodeError("boom", payload, 0)
        return real_loads(payload)

    monkeypatch.setattr(llm_mod.json, "loads", flaky_loads)

    class _Decoder:
        def decode(self, _raw, final=False):
            if final:
                return '\n{"message":{"content":"first"}}\n{"message":{"content":"second"}}\n'
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
    assert out == ["second"]


def test_web_server_blocked_anyio_import_and_health_route_path():
    from tests.test_web_server_runtime import _load_web_server_with_blocked_imports, _make_agent

    ws_mod = _load_web_server_with_blocked_imports()
    agent, _calls = _make_agent(ai_provider="ollama", ollama_online=False)

    async def _fake_get_agent():
        return agent

    ws_mod.get_agent = _fake_get_agent
    response = asyncio.run(ws_mod.health_check())
    assert getattr(response, "status_code", 0) in (200, 503)