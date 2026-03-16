"""
RAG DocumentStore.search() OTel span enstrümantasyonu testleri.

Doğrulananlar:
- _otel_trace mevcut ve ENABLE_TRACING=True → span başlatılır, attribute'lar set edilir
- _otel_trace=None → span oluşturulmaz, search normal çalışır
- Span içinde: sidar.rag.mode, sidar.rag.session_id, sidar.rag.query_len, sidar.rag.success
"""

import ast
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest


# ─── Kaynak kodu doğrulama ────────────────────────────────────────────────

def test_rag_otel_import_present():
    """rag.py'de OTel import bloğu bulunmalı (try/except ile)."""
    src = Path("core/rag.py").read_text(encoding="utf-8")
    assert "from opentelemetry import trace as _otel_trace" in src
    assert "_otel_trace = None" in src


def test_rag_search_uses_start_as_current_span():
    """search() metodu start_as_current_span('rag.search') kullanmalı."""
    src = Path("core/rag.py").read_text(encoding="utf-8")
    assert 'start_as_current_span("rag.search")' in src


def test_rag_search_span_attributes_in_source():
    """Doğru span attribute anahtarları kaynak kodda bulunmalı."""
    src = Path("core/rag.py").read_text(encoding="utf-8")
    for attr in ("sidar.rag.mode", "sidar.rag.session_id", "sidar.rag.query_len", "sidar.rag.success"):
        assert attr in src, f"Eksik span attribute: {attr}"


def test_rag_search_span_wraps_asyncio_to_thread():
    """span bloğu asyncio.to_thread çağrısını sarmalıyor olmalı."""
    src = Path("core/rag.py").read_text(encoding="utf-8")
    # span bloğu içinde to_thread çağrısı
    tree = ast.parse(src)
    DocumentStore = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "DocumentStore")
    search_fn = next(n for n in DocumentStore.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "search")
    fn_src = ast.get_source_segment(src, search_fn) or ""
    assert "asyncio.to_thread" in fn_src
    assert "start_as_current_span" in fn_src


# ─── Modül yükleme yardımcısı ─────────────────────────────────────────────

def _load_rag_module():
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 50
        RAG_CHUNK_OVERLAP = 10
        HF_TOKEN = ""
        HF_HUB_OFFLINE = False

    cfg_mod.Config = _Cfg
    prev = sys.modules.get("config")
    try:
        sys.modules["config"] = cfg_mod
        spec = importlib.util.spec_from_file_location("rag_otel_test", Path("core/rag.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        if prev is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = prev


def _new_store(mod, tmp_path):
    """DocumentStore'u ağır bağımlılıklar olmadan oluşturur."""
    cfg = types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=50, RAG_CHUNK_OVERLAP=10, HF_TOKEN="", HF_HUB_OFFLINE=False)
    old_check = mod.DocumentStore._check_import
    try:
        mod.DocumentStore._check_import = lambda self, _: False
        return mod.DocumentStore(tmp_path / "rag_store", cfg=cfg)
    finally:
        mod.DocumentStore._check_import = old_check


# ─── Sahte tracer ──────────────────────────────────────────────────────────

class _SpanCtx:
    def __init__(self):
        self.attrs: dict = {}
        self.name: str | None = None

    def set_attribute(self, k, v):
        self.attrs[k] = v


class _FakeTracer:
    def __init__(self):
        self.span = _SpanCtx()
        self.started: str | None = None

    def start_as_current_span(self, name):
        self.started = name
        self.span.name = name
        return self._CM(self.span)

    class _CM:
        def __init__(self, span):
            self._span = span

        def __enter__(self):
            return self._span

        def __exit__(self, *args):
            return False


def _make_otel_mod(tracer: _FakeTracer):
    class _OTel:
        @staticmethod
        def get_tracer(_name):
            return tracer

    return _OTel


# ─── Çalışma zamanı testleri ──────────────────────────────────────────────

def test_rag_search_span_attributes_at_runtime(tmp_path, monkeypatch):
    """search() çağrısı span'ı başlatmalı ve tüm attribute'ları set etmeli."""
    mod = _load_rag_module()
    store = _new_store(mod, tmp_path)

    tr = _FakeTracer()
    monkeypatch.setattr(mod, "_otel_trace", _make_otel_mod(tr))

    # asyncio.to_thread → doğrudan senkron çağrıyı simüle et
    async def _fake_to_thread(fn, *args, **kwargs):
        return (True, "test sonucu")

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    result = asyncio.run(store.search("test sorgusu", top_k=3, mode="auto", session_id="sess-1"))

    assert tr.started == "rag.search"
    assert tr.span.attrs["sidar.rag.mode"] == "auto"
    assert tr.span.attrs["sidar.rag.session_id"] == "sess-1"
    assert tr.span.attrs["sidar.rag.query_len"] == len("test sorgusu")
    assert tr.span.attrs["sidar.rag.success"] is True
    assert result == (True, "test sonucu")


def test_rag_search_no_span_when_otel_none(tmp_path, monkeypatch):
    """_otel_trace=None iken span oluşturulmadan search çalışmalı."""
    mod = _load_rag_module()
    store = _new_store(mod, tmp_path)

    monkeypatch.setattr(mod, "_otel_trace", None)

    async def _fake_to_thread(fn, *args, **kwargs):
        return (False, "sonuç yok")

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    result = asyncio.run(store.search("sorgu", mode="chroma", session_id="s"))
    assert result == (False, "sonuç yok")


def test_rag_search_query_len_attribute_is_correct(tmp_path, monkeypatch):
    """query_len attribute'u gerçek sorgu uzunluğunu yansıtmalı."""
    mod = _load_rag_module()
    store = _new_store(mod, tmp_path)

    tr = _FakeTracer()
    monkeypatch.setattr(mod, "_otel_trace", _make_otel_mod(tr))

    async def _fake_to_thread(fn, *args, **kwargs):
        return (True, "ok")

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    query = "bu bir test sorgusudur ve tam uzunluğu ölçülmeli"
    asyncio.run(store.search(query))

    assert tr.span.attrs["sidar.rag.query_len"] == len(query)


def test_rag_search_success_false_propagated_to_span(tmp_path, monkeypatch):
    """_search_sync False döndürdüğünde sidar.rag.success=False set edilmeli."""
    mod = _load_rag_module()
    store = _new_store(mod, tmp_path)

    tr = _FakeTracer()
    monkeypatch.setattr(mod, "_otel_trace", _make_otel_mod(tr))

    async def _fake_to_thread(fn, *args, **kwargs):
        return (False, "veri bulunamadı")

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    result = asyncio.run(store.search("olmayan konu"))
    assert tr.span.attrs["sidar.rag.success"] is False
    assert result[0] is False


def test_rag_search_mode_pgvector_propagated(tmp_path, monkeypatch):
    """mode='pgvector' değeri span attribute'una doğru iletilmeli."""
    mod = _load_rag_module()
    store = _new_store(mod, tmp_path)

    tr = _FakeTracer()
    monkeypatch.setattr(mod, "_otel_trace", _make_otel_mod(tr))

    async def _fake_to_thread(fn, *args, **kwargs):
        return (True, "pgvector sonucu")

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    asyncio.run(store.search("vektör sorgusu", mode="pgvector"))
    assert tr.span.attrs["sidar.rag.mode"] == "pgvector"