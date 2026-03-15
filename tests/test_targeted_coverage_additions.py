import asyncio
import types
from types import SimpleNamespace
import pytest

from tests.test_github_manager_runtime import GM, _manager
from tests.test_llm_client_runtime import _collect, _load_llm_client_module
from tests.test_sidar_agent_runtime import _make_react_ready_agent
from tests.test_sidar_agent_runtime import LEGACY_INTERNAL_METHODS_MISSING
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


@pytest.mark.skipif(LEGACY_INTERNAL_METHODS_MISSING, reason="Legacy private SidarAgent internals were removed")
def test_react_loop_handles_json_array_items_that_fail_toolcall_validation():
    agent = _make_react_ready_agent(max_steps=1)
    agent.memory = SimpleNamespace(get_messages_for_llm=lambda: [], add=lambda *_: None)

    async def _gen_once(text):
        yield text

    class _LLM:
        async def chat(self, **kwargs):
            # JSON parse başarılı; fakat liste öğesi ToolCall şemasına uymadığı için
            # _react_loop içinde ValidationError dalına düşmelidir.
            return _gen_once('[{"gecersiz_alan": "deger"}]')

    agent.llm = _LLM()
    out = asyncio.run(_collect(agent._react_loop("x")))
    assert out[-1].startswith("Üzgünüm, bu istek için güvenilir")


def test_recursive_chunk_text_flushes_current_chunk_before_splitting_large_part(tmp_path):
    rag_mod = _load_rag_module(tmp_path)
    store = _new_store(rag_mod, tmp_path)

    text = "kisa metin. " + "BU_TEK_KELIME_ON_KARAKTERDEN_COK_DAHA_UZUN_BIR_KELIMEDIR_VE_BOSLUK_YOKTUR."
    chunks = store._recursive_chunk_text(text, size=10, overlap=0)

    assert chunks
    assert "kisa metin." in chunks
    assert any(chunk.startswith(" BU_TEK") for chunk in chunks)


def test_recursive_chunk_text_flushes_before_large_newline_part_and_continues(tmp_path):
    rag_mod = _load_rag_module(tmp_path)
    store = _new_store(rag_mod, tmp_path)

    text = "Kisa Metin\n" + ("A" * 2000)
    chunks = store._recursive_chunk_text(text, size=1000, overlap=0)

    assert chunks
    assert chunks[0] == "Kisa Metin"
    assert any(chunk.startswith("\nA") for chunk in chunks[1:])


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


@pytest.mark.skipif(LEGACY_INTERNAL_METHODS_MISSING, reason="Legacy private SidarAgent internals were removed")
def test_web_server_and_agent_error_surface_runtime_stubs(monkeypatch):
    from tests.test_web_server_runtime import _load_web_server, _make_agent

    ws_mod = _load_web_server()
    fake_agent, _calls = _make_agent(ai_provider="ollama", ollama_online=False)

    async def _fake_get_agent():
        return fake_agent

    monkeypatch.setattr(ws_mod, "get_agent", _fake_get_agent)

    # web server fonksiyon yolları
    from tests.test_web_server_runtime import _FakeRequest
    sess = asyncio.run(ws_mod.get_sessions(_FakeRequest(path="/"), user=types.SimpleNamespace(id="u1", username="alice")))
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

def test_rag_remaining_branches_for_fp16_chunk_delete_and_keyword(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)

    # 65-66: fp16 wrapper (__call__ özel metot olduğundan doğrudan __call__ çağrılır)
    ef_mod = types.ModuleType("chromadb.utils.embedding_functions")

    class _EF:
        def __call__(self, input):
            return [f"ok:{len(input)}"]

    ef_mod.SentenceTransformerEmbeddingFunction = lambda **kwargs: _EF()
    torch_mod = types.ModuleType("torch")
    torch_mod.cuda = types.SimpleNamespace(is_available=lambda: True)
    torch_mod.float16 = "fp16"

    class _Auto:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    torch_mod.autocast = lambda **kwargs: _Auto()
    monkeypatch.setitem(__import__("sys").modules, "chromadb.utils.embedding_functions", ef_mod)
    monkeypatch.setitem(__import__("sys").modules, "torch", torch_mod)
    monkeypatch.setitem(__import__("sys").modules, "torch.amp", types.ModuleType("torch.amp"))

    ef = mod._build_embedding_function(use_gpu=True, gpu_device=0, mixed_precision=True)
    assert ef.__call__(["x"]) == ["ok:1"]

    st = _new_store(mod, tmp_path)

    # 276 ve 280-281: recursive splitter iç dalları
    assert st._recursive_chunk_text("a b", size=1, overlap=0)
    forced = st._recursive_chunk_text("aaaa", size=2, overlap=1)
    assert all(len(part) <= 2 for part in forced)

    # 465: kilit içinde doc önceden silinmiş dalı
    doc_id = st.add_document("T", "body", session_id="s1")

    class _RaceLock:
        def __enter__(self_nonlocal):
            st._index.pop(doc_id, None)
            return self_nonlocal

        def __exit__(self_nonlocal, *args):
            return False

    st._write_lock = _RaceLock()
    assert "zaten silinmiş" in st.delete_document(doc_id)

    # 693: keyword search sırasında dosya yoksa FileNotFoundError
    st._index = {"miss": {"title": "X", "tags": [], "session_id": "s1", "source": ""}}
    ok, out = st._keyword_search("x", top_k=1, session_id="s1")
    assert ok is True and "Kelime Eşleşmesi" in out


def test_web_server_remaining_branches_for_redis_ws_metrics_and_github(monkeypatch):
    from tests.test_web_server_runtime import _FakeRequest, _load_web_server, _make_agent

    ws_mod = _load_web_server()
    agent, _ = _make_agent()

    async def _fake_get_agent():
        return agent

    monkeypatch.setattr(ws_mod, "get_agent", _fake_get_agent)

    # 191-192: redis ping başarılı kurulumu
    ws_mod._redis_client = None
    ws_mod._redis_lock = None
    redis_client = asyncio.run(ws_mod._get_redis())
    assert redis_client is not None

    # 262: ddos middleware call_next devamı
    req = _FakeRequest(method="GET", path="/api")
    async def _next(_r):
        return "OK"
    res = asyncio.run(ws_mod.ddos_rate_limit_middleware(req, _next))
    assert res == "OK"

    # 369-371: websocket chunk ve done gönderimi
    class _WS:
        def __init__(self):
            self.sent = []
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self._i = 0

        async def accept(self):
            return None

        async def send_json(self, payload):
            self.sent.append(payload)

        async def receive_text(self):
            self._i += 1
            if self._i == 1:
                return '{"action":"auth","token":"tok"}'
            if self._i == 2:
                return '{"message":"first","action":"send"}'
            await asyncio.sleep(0.05)
            raise ws_mod.WebSocketDisconnect()

    ws = _WS()

    async def _limited(*_a, **_k):
        return False

    monkeypatch.setattr(ws_mod, "_redis_is_rate_limited", _limited)

    async def _respond(_msg):
        yield "x"

    agent.respond = _respond
    asyncio.run(ws_mod.websocket_chat(ws))
    assert any(p.get("chunk") == "x" or p.get("content") == "x" for p in ws.sent)
    assert any(p.get("done") is True for p in ws.sent)

    # 520-527: prometheus import başarılı branch
    prom = types.ModuleType("prometheus_client")

    class _Gauge:
        def __init__(self, *_a, **_k):
            pass

        def set(self, _v):
            return None

    prom.CollectorRegistry = lambda: object()
    prom.Gauge = _Gauge
    prom.generate_latest = lambda _reg: b"m"
    prom.CONTENT_TYPE_LATEST = "text/plain"
    monkeypatch.setitem(__import__("sys").modules, "prometheus_client", prom)

    metrics_res = asyncio.run(ws_mod.metrics(_FakeRequest(headers={"Accept": "text/plain"})))
    assert getattr(metrics_res, "media_type", "") == "text/plain"

    # 775 / 787: github pr endpoint success branch
    agent.github = types.SimpleNamespace(
        is_available=lambda: True,
        repo_name="o/r",
        get_pull_requests_detailed=lambda **_k: (True, [{"n": 1}], None),
        get_pull_request=lambda _n: (True, {"number": _n}),
    )
    prs = asyncio.run(ws_mod.github_prs())
    detail = asyncio.run(ws_mod.github_pr_detail(7))
    assert prs.content["success"] is True and detail.content["success"] is True


def test_web_server_upload_exception_and_finally_paths(monkeypatch):
    from tests.test_web_server_runtime import _FakeUploadFile, _load_web_server

    ws_mod = _load_web_server()

    class _Docs:
        def add_document_from_file(self, *_args):
            return True, "ok"

    agent = types.SimpleNamespace(
        memory=types.SimpleNamespace(active_session_id="s1"),
        docs=_Docs(),
    )

    async def _fake_get_agent():
        return agent

    monkeypatch.setattr(ws_mod, "get_agent", _fake_get_agent)

    # try/except: diske yazma hatası -> 500
    monkeypatch.setattr(ws_mod.shutil, "copyfileobj", lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk fail")))
    up1 = _FakeUploadFile("x.txt", b"1")
    res1 = asyncio.run(ws_mod.upload_rag_file(up1))
    assert res1.status_code == 500
    assert "disk fail" in res1.content.get("error", "")
    assert up1.closed is True

    # finally: close/rmtree hataları yutulmalı, başarılı yanıt dönmeli
    monkeypatch.setattr(ws_mod.shutil, "copyfileobj", lambda *_a, **_k: None)
    monkeypatch.setattr(ws_mod.shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("rm fail")))
    up2 = _FakeUploadFile("x2.txt", b"2")

    async def _close_fail():
        raise RuntimeError("close fail")

    up2.close = _close_fail
    res2 = asyncio.run(ws_mod.upload_rag_file(up2))
    assert res2.status_code == 200
    assert res2.content["success"] is True


def test_websocket_error_send_fallback_pass_branch(monkeypatch):
    from tests.test_web_server_runtime import _load_web_server, _make_agent

    ws_mod = _load_web_server()
    agent, _ = _make_agent()

    async def _fake_get_agent():
        return agent

    monkeypatch.setattr(ws_mod, "get_agent", _fake_get_agent)

    class _WS:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self._i = 0
            self.calls = 0

        async def accept(self):
            return None

        async def receive_text(self):
            self._i += 1
            if self._i == 1:
                return '{"action":"auth","token":"tok"}'
            if self._i == 2:
                return '{"message":"boom","action":"send"}'
            await asyncio.sleep(0.05)
            raise ws_mod.WebSocketDisconnect()

        async def send_json(self, _payload):
            self.calls += 1
            raise RuntimeError("send fail")

    async def _rl(*_a, **_k):
        return False

    async def _respond(_msg):
        yield "x"

    monkeypatch.setattr(ws_mod, "_redis_is_rate_limited", _rl)
    agent.respond = _respond
    ws = _WS()
    asyncio.run(ws_mod.websocket_chat(ws))
    assert ws.calls >= 2


@pytest.mark.skipif(LEGACY_INTERNAL_METHODS_MISSING, reason="Legacy private SidarAgent internals were removed")
def test_sidar_agent_remaining_branches_for_react_tools_and_context(monkeypatch):
    from tests.test_sidar_agent_runtime import SA_MOD, _make_react_ready_agent, _make_agent_for_runtime

    # 337: boş liste toolcall
    a = _make_react_ready_agent(max_steps=1)

    async def _chat_empty_list(**_kwargs):
        async def _gen():
            yield "[]"
        return _gen()

    a.llm = types.SimpleNamespace(chat=_chat_empty_list)
    a.memory.get_messages_for_llm = lambda: []
    out = asyncio.run(_collect(a._react_loop("u")))
    assert any("Maksimum adım" in x for x in out)

    # 418: final_answer boş argüman fallback
    b = _make_react_ready_agent(max_steps=1)

    async def _chat_empty_answer(**_kwargs):
        async def _gen():
            yield '{"thought":"t","tool":"final_answer","argument":"   "}'
        return _gen()

    b.llm = types.SimpleNamespace(chat=_chat_empty_answer)
    b.memory.get_messages_for_llm = lambda: []
    out2 = asyncio.run(_collect(b._react_loop("u")))
    assert out2 == ["✓ İşlem tamamlandı."]

    # 495-498: react döngüsünde beklenmeyen exception
    c = _make_react_ready_agent(max_steps=1)

    async def _chat_tool(**_kwargs):
        async def _gen():
            yield '{"thought":"t","tool":"list_dir","argument":"."}'
        return _gen()

    async def _boom_tool(_name, _arg):
        raise RuntimeError("boom")

    c.llm = types.SimpleNamespace(chat=_chat_tool)
    c._execute_tool = _boom_tool
    c.memory.get_messages_for_llm = lambda: []
    out3 = asyncio.run(_collect(c._react_loop("u")))
    assert any("beklenmeyen bir hata" in x for x in out3)

    d = _make_agent_for_runtime()

    # 535-536 ve 549: schema dalları
    wf = SA_MOD.WriteFileSchema()
    wf.path = "  a.txt  "
    wf.content = "hello"
    pf = SA_MOD.PatchFileSchema()
    pf.path = " b.txt "
    pf.old_text = "x"
    pf.new_text = "y"

    d.code = types.SimpleNamespace(
        write_file=lambda path, content: (True, f"{path}:{content}"),
        patch_file=lambda path, old, new: (True, f"{path}:{old}>{new}"),
        grep_files=lambda *a, **k: (True, "grep-ok"),
    )
    assert asyncio.run(d._tool_write_file(wf)).startswith("a.txt")
    assert asyncio.run(d._tool_patch_file(pf)).startswith("b.txt")

    # 666: github_list_prs schema path
    d.github = types.SimpleNamespace(is_available=lambda: True, list_pull_requests=lambda **k: (True, str(k)))
    prs_arg = SA_MOD.GithubListPRsSchema()
    prs_arg.state = "closed"
    prs_arg.limit = 3
    assert "closed" in asyncio.run(d._tool_github_list_prs(prs_arg))

    # 1137-1138 / 1164 / 1169 / 1226 / 1466 / 1524-1525
    assert asyncio.run(d._tool_grep_files("pat|||.|||*|||bad")) == "grep-ok"
    d.todo = types.SimpleNamespace(set_tasks=lambda t: str(t))
    todo_res = asyncio.run(d._tool_todo_write(" |||task only"))
    assert "pending" in todo_res

    d.cfg = types.SimpleNamespace(
        PROJECT_NAME="P", VERSION="1", BASE_DIR=".", AI_PROVIDER="gemini", GEMINI_MODEL="g",
        ACCESS_LEVEL="sandbox", USE_GPU=True, GPU_INFO="gpu", GPU_COUNT=1, CUDA_VERSION="12",
        GITHUB_REPO="r", MEMORY_ENCRYPTION_KEY="",
    )
    d.security = types.SimpleNamespace(level_name="sandbox")
    d.memory.get_last_file = lambda: None
    d.github = types.SimpleNamespace(is_available=lambda: False)
    d.web = types.SimpleNamespace(is_available=lambda: False)
    d.docs = types.SimpleNamespace(status=lambda: "ok")
    class _Todo:
        def __len__(self):
            return 0
        def list_tasks(self):
            return ""
    d.todo = _Todo()
    d._load_instruction_files = lambda: ""
    d.code = types.SimpleNamespace(get_metrics=lambda: {"files_read": 0, "files_written": 0, "commands_executed": 0})
    ctx = asyncio.run(d._build_context())
    assert "Gemini Modeli" in ctx and "CUDA" in ctx

    d._instructions_lock = __import__("threading").Lock()
    d._instructions_cache = None
    d._instructions_mtimes = {}

    class _BadPath:
        def is_file(self):
            return True

        def resolve(self):
            return self

        def stat(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(SA_MOD.Path, "rglob", lambda self, _p: [_BadPath()])
    monkeypatch.setattr(SA_MOD.Path, "exists", lambda self: True)
    monkeypatch.setattr(SA_MOD.Path, "is_dir", lambda self: True)
    d.cfg.BASE_DIR = SA_MOD.Path(".")
    assert d._load_instruction_files() == ""


def test_sidar_agent_opentelemetry_import_error_with_runtime_loader(monkeypatch):
    import builtins
    from tests.test_sidar_agent_runtime import _load_sidar_agent_module

    real_import = builtins.__import__

    def _blocked(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError("blocked opentelemetry")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    mod = _load_sidar_agent_module()
    assert mod.trace is None


def test_rag_auto_mode_full_exceptions_to_bm25_fallback(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    store._chroma_available = True
    store._bm25_available = True
    store.collection = object()
    store._index = {"d1": {"session_id": "global", "title": "T", "tags": [], "source": ""}}

    def _raise(*_a, **_k):
        raise RuntimeError("simulated search error")

    monkeypatch.setattr(store, "_rrf_search", _raise)
    monkeypatch.setattr(store, "_chroma_search", _raise)
    monkeypatch.setattr(store, "_bm25_search", lambda *_a, **_k: (True, "bm25 fallback ok"))

    ok, result = store.search("test query", mode="auto")
    assert ok is True
    assert result == "bm25 fallback ok"


@pytest.mark.skipif(LEGACY_INTERNAL_METHODS_MISSING, reason="Legacy private SidarAgent internals were removed")
def test_sidar_agent_direct_route_edge_cases_extra(monkeypatch):
    from tests.test_sidar_agent_runtime import _make_agent_for_runtime

    agent = _make_agent_for_runtime()
    agent.cfg.TEXT_MODEL = "tm"
    agent.llm = types.SimpleNamespace()

    async def _chat_text(**_k):
        return "duz metin"

    monkeypatch.setattr(agent.llm, "chat", _chat_text, raising=False)
    assert asyncio.run(agent._try_direct_tool_route("merhaba")) is None

    async def _chat_dict(**_k):
        return {"tool": "none"}

    monkeypatch.setattr(agent.llm, "chat", _chat_dict, raising=False)
    assert asyncio.run(agent._try_direct_tool_route("merhaba")) is None

    async def _chat_disallowed(**_k):
        return '{"thought":"","tool":"rm_rf","argument":""}'

    monkeypatch.setattr(agent.llm, "chat", _chat_disallowed, raising=False)
    assert asyncio.run(agent._try_direct_tool_route("merhaba")) is None


@pytest.mark.skipif(LEGACY_INTERNAL_METHODS_MISSING, reason="Legacy private SidarAgent internals were removed")
def test_sidar_agent_react_parallel_exception_path_extra():
    from tests.test_sidar_agent_runtime import _make_react_ready_agent

    agent = _make_react_ready_agent(max_steps=3)
    agent.memory.get_messages_for_llm = lambda: []
    agent._AUTO_PARALLEL_SAFE = {"list_dir", "read_file"}

    calls = {"n": 0}

    async def _chat(**_k):
        calls["n"] += 1

        async def _gen():
            if calls["n"] == 1:
                yield '[{"thought":"a","tool":"list_dir","argument":"."},{"thought":"b","tool":"read_file","argument":"x.txt"}]'
            else:
                yield '{"thought":"done","tool":"final_answer","argument":"sonuc"}'

        return _gen()

    async def _exec(tool_name, _arg):
        if tool_name == "read_file":
            raise ValueError("Kritik Arac Hatasi")
        return "Arac Basarili"

    agent.llm = types.SimpleNamespace(chat=_chat)
    agent._execute_tool = _exec

    out = asyncio.run(_collect(agent._react_loop("test_parallel")))
    joined = "\n".join(out)
    assert "sonuc" in joined
    assert "\x00TOOL:list_dir\x00" in joined and "\x00TOOL:read_file\x00" in joined


def test_web_server_anyio_closed_and_upload_close_extra(monkeypatch):
    from tests.test_web_server_runtime import _FakeUploadFile, _load_web_server

    mod = _load_web_server()

    class _Docs:
        def add_document_from_file(self, *_args):
            return True, "ok"

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(active_session_id="s1"), docs=_Docs())

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    up = _FakeUploadFile("test.txt", b"content")

    async def _close_fail():
        raise ValueError("close fail")

    up.close = _close_fail
    monkeypatch.setattr(mod.shutil, "copyfileobj", lambda *_a, **_k: None)
    monkeypatch.setattr(mod.shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(OSError("rm fail")))
    resp = asyncio.run(mod.upload_rag_file(up))
    assert resp.status_code == 200
