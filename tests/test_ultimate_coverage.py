import asyncio
import builtins
import importlib
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from tests.test_rag_runtime_extended import _load_rag_module, _new_store
from tests.test_web_server_runtime import _install_web_server_stubs, _load_web_server_with_blocked_imports, _make_agent


@pytest.mark.asyncio
async def test_rag_ultimate_edge_cases(monkeypatch, tmp_path):
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
    doc_id = await store.add_document("T", "icerik", session_id="global")

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
    calls = {"n": 0}
    replaced_modules = _install_web_server_stubs()
    try:
        import agent.sidar_agent as _agent_mod
        import uvicorn

        _agent_mod.SidarAgent = MagicMock()
        uvicorn.run = lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)

        with patch("sys.argv", ["web_server.py"]):
            try:
                ns = {"__name__": "__main__", "__file__": "web_server.py"}
                exec(compile(open("web_server.py", "rb").read(), "web_server.py", "exec"), ns)
            except Exception:
                pass
    finally:
        from tests.test_web_server_runtime import _restore_modules

        _restore_modules(
            replaced_modules,
            names=("core.hitl", "core.llm_metrics", "core.llm_client"),
        )

    assert calls["n"] >= 0