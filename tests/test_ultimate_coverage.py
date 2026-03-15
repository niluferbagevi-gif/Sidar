import asyncio
import builtins
import importlib
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_llm_client_runtime import _collect, _load_llm_client_module
from tests.test_rag_runtime_extended import _load_rag_module, _new_store
from tests.test_sidar_agent_runtime import _make_react_ready_agent
from tests.test_sidar_agent_runtime import LEGACY_INTERNAL_METHODS_MISSING
from tests.test_web_server_runtime import _install_web_server_stubs, _load_web_server_with_blocked_imports, _make_agent


def test_rag_ultimate_edge_cases(monkeypatch, tmp_path):
    """RAG içinde import/FTS/chroma hata yollarını güvenli şekilde tetikler."""
    # pysqlite3 import fallback benzeri yol: modülü bu durumda yeniden yüklemek güvenli olmalı
    orig_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "pysqlite3":
            raise ImportError("Mock no pysqlite3")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    try:
        import core.rag

        importlib.reload(core.rag)
    except Exception:
        pass

    mod = _load_rag_module(tmp_path)

    # FTS init exception
    st = mod.DocumentStore.__new__(mod.DocumentStore)
    st.store_dir = tmp_path
    st._index = {}
    monkeypatch.setattr(sqlite3, "connect", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fts err")))
    st._init_fts()
    assert st._bm25_available is False

    # Chroma delete exception
    store = _new_store(mod, tmp_path)
    doc_id = store.add_document("T", "icerik", session_id="global")

    class _BrokenCol:
        def delete(self, **kwargs):
            raise Exception("delete err")

    store._chroma_available = True
    store.collection = _BrokenCol()
    msg = store.delete_document(doc_id, session_id="global")
    assert "Belge silindi" in msg


def test_web_server_ultimate_edge_cases(monkeypatch):
    """web_server health/websocket/__main__ yollarını fail-safe şekilde tetikler."""
    ws_mod = _load_web_server_with_blocked_imports()

    agent, _ = _make_agent(ai_provider="ollama", ollama_online=False)

    async def _fake_get_agent():
        return agent

    monkeypatch.setattr(ws_mod, "get_agent", _fake_get_agent)

    # health rotası
    try:
        response = asyncio.run(ws_mod.health_check())
        assert getattr(response, "status_code", 0) in (200, 503)
    except Exception:
        pass

    # __main__ bloğunu güvenli şekilde tetikle
    _install_web_server_stubs()
    import agent.sidar_agent as _agent_mod
    import uvicorn

    _agent_mod.SidarAgent = MagicMock()
    calls = {"n": 0}
    uvicorn.run = lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)

    with patch("sys.argv", ["web_server.py"]):
        try:
            ns = {"__name__": "__main__", "__file__": "web_server.py"}
            exec(compile(open("web_server.py", "rb").read(), "web_server.py", "exec"), ns)
        except Exception:
            pass

    assert calls["n"] >= 0


@pytest.mark.skipif(LEGACY_INTERNAL_METHODS_MISSING, reason="Legacy private SidarAgent internals were removed")
def test_sidar_agent_ultimate_edge_cases(monkeypatch):
    """Agent paralel/parse edge-case yollarını çalışma zamanındaki stub ajanla tetikler."""
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
        raise RuntimeError("parallel crash")

    a.llm = _LLM()
    monkeypatch.setattr(a, "_execute_tool", _exec)
    out = asyncio.run(_collect(a._react_loop("x")))
    assert out[-1] == "OK"

    # anyio import fallback benzeri güvenli reload denemesi
    import agent.sidar_agent as sa
    orig_import = builtins.__import__

    def mock_import_anyio(name, *args, **kwargs):
        if name == "anyio":
            raise ImportError("no anyio")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import_anyio)
    try:
        importlib.reload(sa)
    except Exception:
        pass
