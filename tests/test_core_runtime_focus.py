import asyncio
import importlib.util
import json
import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _temp_module(name: str, mod):
    prev = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        yield
    finally:
        if prev is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prev


def _load_security_module(tmp_path: Path):
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        ACCESS_LEVEL = "sandbox"
        BASE_DIR = tmp_path

    cfg_mod.Config = _Cfg
    with _temp_module("config", cfg_mod):
        spec = importlib.util.spec_from_file_location("security_under_test", Path("managers/security.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod


def _load_memory_module():
    spec = importlib.util.spec_from_file_location("memory_under_test", Path("core/memory.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _load_rag_module(tmp_path: Path):
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 80
        RAG_CHUNK_OVERLAP = 20
        HF_TOKEN = ""
        HF_HUB_OFFLINE = False

    cfg_mod.Config = _Cfg
    with _temp_module("config", cfg_mod):
        spec = importlib.util.spec_from_file_location("rag_under_test", Path("core/rag.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod


def test_security_manager_runtime_paths(tmp_path):
    sec_mod = _load_security_module(tmp_path)
    SecurityManager = sec_mod.SecurityManager

    sec = SecurityManager(access_level="full", base_dir=tmp_path)
    (tmp_path / "ok.txt").write_text("x", encoding="utf-8")

    assert sec.can_read(str(tmp_path / "ok.txt")) is True
    assert sec.can_read("/etc/passwd") is False
    assert sec.is_safe_path(str(tmp_path / "ok.txt")) is True
    assert sec.is_safe_path("../outside") is False

    assert sec.can_write(str(tmp_path / "a.txt")) is True
    assert sec.can_write("/etc/hosts") is False

    assert sec.can_execute() is True
    assert sec.can_run_shell() is True

    sec_sb = SecurityManager(access_level="sandbox", base_dir=tmp_path)
    assert sec_sb.can_write(str(tmp_path / "temp" / "x.txt")) is True
    assert sec_sb.can_write(str(tmp_path / "x.txt")) is False

    sec_r = SecurityManager(access_level="restricted", base_dir=tmp_path)
    assert sec_r.can_write(str(tmp_path / "temp" / "x.txt")) is False
    assert sec_r.can_execute() is False
    assert sec_r.can_run_shell() is False

    assert sec_sb.set_level("full") is True
    assert sec_sb.set_level("full") is False
    assert "[OpenClaw] Erişim Seviyesi" in sec_sb.status_report()
    assert "SecurityManager" in repr(sec_sb)


def test_conversation_memory_sessions_and_summary(tmp_path, monkeypatch):
    mem_mod = _load_memory_module()
    ConversationMemory = mem_mod.ConversationMemory

    mem_file = tmp_path / "memory.json"
    m = ConversationMemory(mem_file, max_turns=3, keep_last=2)

    # Session & persistence flows
    sid = m.active_session_id
    assert sid is not None
    m.add("user", "merhaba")
    m.add("assistant", "selam")
    m.set_last_file("a.py")
    assert m.get_last_file() == "a.py"

    sessions = m.get_all_sessions()
    assert sessions and sessions[0]["id"] == sid

    m.update_title("Yeni Başlık")
    assert m.active_title == "Yeni Başlık"

    # Tokenizer fallback/import path
    monkeypatch.setitem(sys.modules, "tiktoken", types.SimpleNamespace(get_encoding=lambda _: types.SimpleNamespace(encode=lambda t: list(t))))
    assert m._estimate_tokens() > 0

    assert isinstance(m.needs_summarization(), bool)
    m.apply_summary("özet metin")
    msgs = m.get_messages_for_llm()
    assert any("KONUŞMA ÖZETİ" in x["content"] for x in msgs)

    assert m.load_session(sid) is True
    assert m.delete_session("missing") is False

    # Broken JSON quarantine path
    bad = m.sessions_dir / "broken.json"
    bad.write_text("{bad", encoding="utf-8")
    all_sessions = m.get_all_sessions()
    assert isinstance(all_sessions, list)
    assert (m.sessions_dir / "broken.json.broken").exists()

    m.clear()
    assert len(m) == 0
    m.force_save()
    assert "ConversationMemory" in repr(m)


def test_document_store_core_flows_without_chroma(tmp_path, monkeypatch):
    rag_mod = _load_rag_module(tmp_path)
    DocumentStore = rag_mod.DocumentStore

    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)
    store = DocumentStore(tmp_path / "rag_store", cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=60, RAG_CHUNK_OVERLAP=10, HF_TOKEN="", HF_HUB_OFFLINE=False))

    # Basic add/file paths
    missing_ok, missing_msg = store.add_document_from_file(str(tmp_path / "nope.txt"))
    assert missing_ok is False and "bulunamadı" in missing_msg

    bad_ext = tmp_path / "x.bin"
    bad_ext.write_bytes(b"x")
    ok, msg = store.add_document_from_file(str(bad_ext))
    assert ok is False and "Desteklenmeyen" in msg

    txt = tmp_path / "note.txt"
    txt.write_text("Python RAG test içeriği. Python ve güvenlik.", encoding="utf-8")
    ok, msg = store.add_document_from_file(str(txt), title="Not", session_id="s1")
    assert ok is True and "eklendi" in msg

    assert store.doc_count == 1
    docs = store.get_index_info(session_id="s1")
    assert len(docs) == 1

    doc_id = docs[0]["id"]
    got_ok, content = store.get_document(doc_id, session_id="s1")
    assert got_ok is True and "Python" in content

    # search mode dispatches
    ok, out = store.search("Python", mode="keyword", session_id="s1")
    assert isinstance(ok, bool) and isinstance(out, str)

    ok, out = store.search("Python", mode="auto", session_id="s1")
    assert ok is True and out

    # helpers
    assert store._recursive_chunk_text("A" * 200, size=50, overlap=10)
    assert "hello" in store._clean_html("<html><body><script>x</script>hello &amp; world</body></html>")
    assert store._extract_snippet("abc def ghi", "def")
    assert "Belge Deposu" in store.list_documents(session_id="s1")
    assert "RAG:" in store.status()

    # url add with stub httpx
    class _Resp:
        text = "<title>Sayfa</title><p>metin</p>"

        @staticmethod
        def raise_for_status():
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return _Resp()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=_Client))
    ok, msg = asyncio.run(store.add_document_from_url("https://example.com", session_id="s1"))
    assert ok is True

    # delete path
    del_msg = store.delete_document(doc_id, session_id="s1")
    assert "silindi" in del_msg or "bulunamadı" in del_msg


def test_document_store_handles_chroma_and_fts_runtime_exceptions(tmp_path, monkeypatch):
    rag_mod = _load_rag_module(tmp_path)
    DocumentStore = rag_mod.DocumentStore

    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)
    store = DocumentStore(
        tmp_path / "rag_store_err",
        cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=60, RAG_CHUNK_OVERLAP=10, HF_TOKEN="", HF_HUB_OFFLINE=False),
    )

    class _BrokenConn:
        def execute(self, *args, **kwargs):
            raise RuntimeError("db disconnected")

    store._bm25_available = True
    store.fts_conn = _BrokenConn()
    assert store._fetch_bm25("python test", top_k=3, session_id="s1") == []

    class _BrokenCollection:
        def count(self):
            return 10

        def query(self, **kwargs):
            raise RuntimeError("chroma unavailable")

    store.collection = _BrokenCollection()
    store._chroma_available = True
    store._bm25_available = True
    store._index = {"d1": {"session_id": "s1", "title": "Doc"}}
    monkeypatch.setattr(store, "_rrf_search", lambda q, k, s: (_ for _ in ()).throw(RuntimeError("rrf error")))
    monkeypatch.setattr(store, "_chroma_search", lambda q, k, s: (_ for _ in ()).throw(RuntimeError("chroma error")))
    monkeypatch.setattr(store, "_bm25_search", lambda q, k, s: (True, "[RAG Arama: python] (Motor: BM25)"))
    ok, out = store.search("python", mode="auto", session_id="s1")
    assert ok is True
    assert "BM25" in out
