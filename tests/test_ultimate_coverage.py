import asyncio

from tests.test_llm_client_runtime import _collect, _load_llm_client_module
from tests.test_rag_runtime_extended import _load_rag_module, _new_store
from tests.test_sidar_agent_runtime import _make_react_ready_agent
from tests.test_web_server_runtime import _install_web_server_stubs, _load_web_server_with_blocked_imports, _make_agent


def test_ollama_trailing_loop_transient_decode_then_success(monkeypatch):
    """Trailing parse loop'ta ilk decode hatası sonrası ikinci satırın üretildiğini doğrular."""
    llm_mod = _load_llm_client_module()
    cfg = type("Cfg", (), {"OLLAMA_URL": "http://localhost:11434/api", "OLLAMA_TIMEOUT": 5, "USE_GPU": False})
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


def test_rag_fts_init_failure_and_chroma_delete_failure_paths(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)

    st = mod.DocumentStore.__new__(mod.DocumentStore)
    st.store_dir = tmp_path
    st._index = {}

    import sqlite3

    monkeypatch.setattr(sqlite3, "connect", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fts down")))
    st._init_fts()
    assert st._bm25_available is False

    store = _new_store(mod, tmp_path)
    doc_id = store.add_document("T", "icerik", session_id="global")

    class _BrokenCol:
        def delete(self, **kwargs):
            raise RuntimeError("chroma delete fail")

    store._chroma_available = True
    store.collection = _BrokenCol()
    msg = store.delete_document(doc_id, session_id="global")
    assert "Belge silindi" in msg


def test_webserver_blocked_anyio_main_exec_and_agent_parallel_error_path(monkeypatch):
    ws_mod = _load_web_server_with_blocked_imports()
    assert ws_mod._ANYIO_CLOSED is None

    agent, _ = _make_agent(ai_provider="ollama", ollama_online=False)

    async def _fake_get_agent():
        return agent

    ws_mod.get_agent = _fake_get_agent
    health = asyncio.run(ws_mod.health_check())
    assert getattr(health, "status_code", 0) in (200, 503)

    # __main__ yolu: uvicorn.run çağrısını gözlemle
    _install_web_server_stubs()
    import agent.sidar_agent as _agent_mod
    import uvicorn

    calls = {"n": 0}

    class _AgentCtor:
        VERSION = "x"

        def __init__(self, cfg):
            self.cfg = cfg
            self.memory = type("M", (), {"active_session_id": "s", "get_all_sessions": lambda self: []})()
            self.docs = type("D", (), {"search": lambda *a, **k: (False, []), "get_index_info": lambda *a, **k: []})()
            self.health = type("H", (), {"get_health_summary": lambda *a, **k: {"status": "ok", "ollama_online": False}, "check_ollama": lambda *a, **k: False, "get_gpu_info": lambda *a, **k: {}})()
            self.github = type("G", (), {"is_available": lambda *a, **k: False, "set_repo": lambda *a, **k: (False, "")})()
            self.web = type("W", (), {"is_available": lambda *a, **k: False})()
            self.pkg = type("P", (), {"status": lambda *a, **k: "ok"})()
            self.todo = type("T", (), {"get_tasks": lambda *a, **k: []})()
            self.security = type("S", (), {"level_name": "sandbox"})()

    _agent_mod.SidarAgent = _AgentCtor
    uvicorn.run = lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)

    import sys
    old_argv = sys.argv[:]
    sys.argv = ["web_server.py"]
    try:
        ns = {"__name__": "__main__", "__file__": "web_server.py"}
        exec(compile(open("web_server.py", "rb").read(), "web_server.py", "exec"), ns)
    finally:
        sys.argv = old_argv
    assert calls["n"] == 1

    # agent parallel error surface (runtime helper)
    a = _make_react_ready_agent(max_steps=2)
    a.memory = type("M", (), {"get_messages_for_llm": lambda self: [], "add": lambda *a, **k: None})()
    a._AUTO_PARALLEL_SAFE = {"list_dir", "health"}

    async def _gen_once(text):
        yield text

    class _LLM:
        def __init__(self):
            self.i = 0
            self.responses = [
                '[{"thought":"t1","tool":"list_dir","argument":"."},{"thought":"t2","tool":"health","argument":""}]',
                '{"thought":"done","tool":"final_answer","argument":"OK"}',
            ]

        async def chat(self, **kwargs):
            t = self.responses[self.i]
            self.i += 1
            return _gen_once(t)

    async def _exec(tool, arg):
        if tool == "list_dir":
            return "ok-list"
        raise RuntimeError("parallel boom")

    a.llm = _LLM()
    monkeypatch.setattr(a, "_execute_tool", _exec)
    out = asyncio.run(_collect(a._react_loop("x")))
    assert out[-1] == "OK"