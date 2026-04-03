from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from core.rag import DocumentStore


def test_chunk_text_handles_invalid_sizes_and_overlap() -> None:
    store = DocumentStore.__new__(DocumentStore)
    store.cfg = SimpleNamespace(RAG_CHUNK_SIZE=0, RAG_CHUNK_OVERLAP=-10)
    store._chunk_size = 0
    store._chunk_overlap = 0

    assert store._chunk_text("hello") == []

    store.cfg = SimpleNamespace(RAG_CHUNK_SIZE=5, RAG_CHUNK_OVERLAP=99)
    chunks = store._chunk_text("abcdefghij")
    assert chunks
    assert all(len(c) <= 5 for c in chunks)


def test_add_document_from_url_returns_error_on_http_exception(monkeypatch) -> None:
    store = DocumentStore.__new__(DocumentStore)
    store._validate_url_safe = lambda _url: None

    class _Resp:
        text = ""

        def raise_for_status(self):
            raise RuntimeError("boom")

    class _Client:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _url):
            return _Resp()

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.AsyncClient = _Client
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    ok, msg = asyncio.run(store.add_document_from_url("https://example.com"))
    assert ok is False
    assert "URL belge eklenemedi" in msg


def test_add_document_from_url_extracts_title_and_calls_add_document(monkeypatch) -> None:
    store = DocumentStore.__new__(DocumentStore)
    store._validate_url_safe = lambda _url: None
    store._clean_html = lambda html: "normalized"

    async def _add_document(title, content, source, tags, session_id):
        assert title == "Sample Title"
        assert content == "normalized"
        assert source == "https://example.com/page"
        assert session_id == "s1"
        return "doc123"

    store.add_document = _add_document

    class _Resp:
        text = "<html><title>Sample Title</title><body>ok</body></html>"

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _url):
            return _Resp()

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.AsyncClient = _Client
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    ok, msg = asyncio.run(store.add_document_from_url("https://example.com/page", session_id="s1"))
    assert ok is True
    assert "doc123" in msg


def test_add_document_from_file_rejects_nonexistent_and_outside_base(tmp_path: Path, monkeypatch) -> None:
    store = DocumentStore.__new__(DocumentStore)
    store.cfg = SimpleNamespace()

    missing_ok, missing_msg = store.add_document_from_file(str(tmp_path / "missing.py"))
    assert missing_ok is False
    assert "Dosya bulunamadı" in missing_msg

    outside = Path.cwd() / "rag_phase4_outside.txt"
    outside.write_text("x", encoding="utf-8")
    monkeypatch.setattr("core.rag.Config.BASE_DIR", tmp_path)
    ok, msg = store.add_document_from_file(str(outside))
    assert ok is False
    assert "proje dizini dışında" in msg
