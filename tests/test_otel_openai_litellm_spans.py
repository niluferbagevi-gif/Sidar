"""
OpenAI ve LiteLLM sağlayıcıları için OTel span enstrümantasyonu testleri.

Her sağlayıcı için doğrulananlar:
- Non-stream: start_as_current_span kullanılır, span_cm.__exit__ çağrılır
- Stream: start_span kullanılır
- Başarılı çağrıda doğru attribute'lar set edilir (provider, model, stream, total_ms)
- Hata yolunda span_cm.__exit__ yine çağrılır
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


# ─── Yardımcı: httpx stub ──────────────────────────────────────────────────

class _Timeout:
    def __init__(self, timeout, connect=None):
        self.timeout = timeout
        self.connect = connect


class _ConnectError(Exception):
    pass


def _load_llm_client():
    # core.llm_metrics'i stubla — dotenv/config import zincirini kırar
    if "core" not in sys.modules:
        core_pkg = types.ModuleType("core")
        core_pkg.__path__ = [str(Path("core").resolve())]
        sys.modules["core"] = core_pkg

    class _MetricsCol:
        def snapshot(self): return {"totals": {}}
        def record(self, **kw): pass  # _record_llm_metric tarafından çağrılır

    metrics_stub = types.ModuleType("core.llm_metrics")
    metrics_stub.get_current_metrics_user_id = lambda: None
    metrics_stub.get_llm_metrics_collector = lambda: _MetricsCol()
    sys.modules["core.llm_metrics"] = metrics_stub

    httpx_stub = types.SimpleNamespace(
        Timeout=_Timeout,
        ConnectError=_ConnectError,
        AsyncClient=None,
    )
    sys.modules["httpx"] = httpx_stub

    spec = importlib.util.spec_from_file_location("llm_client_otel_spans", Path("core/llm_client.py"))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def llm_mod():
    return _load_llm_client()


# ─── Yardımcı: sahte tracer ────────────────────────────────────────────────

class _Span:
    def __init__(self):
        self.attrs: dict = {}

    def set_attribute(self, k, v):
        self.attrs[k] = v

    def end(self):
        pass


class _CM:
    def __init__(self, span):
        self.span = span
        self.closed = False

    def __enter__(self):
        return self.span

    def __exit__(self, *args):
        self.closed = True
        return False


class _Tracer:
    def __init__(self):
        self.span = _Span()
        self.cm = _CM(self.span)
        self.cm_name: str | None = None
        self.span_name: str | None = None

    def start_as_current_span(self, name):
        self.cm_name = name
        return self.cm

    def start_span(self, name):
        self.span_name = name
        return self.span


def _make_trace_mod(tracer: _Tracer):
    class _TraceMod:
        @staticmethod
        def get_tracer(_name):
            return tracer

    return _TraceMod


# ─── Yardımcı: başarılı OpenAI HTTP yanıtı ────────────────────────────────

def _ok_resp(content='{"tool":"final_answer","argument":"ok"}'):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }

    return _Resp


def _make_http_client(resp_cls):
    class _Client:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json, headers):
            return resp_cls()

    return _Client


# ══════════════════════════════════════════════════════════════════════════════
# OpenAI Span Testleri
# ══════════════════════════════════════════════════════════════════════════════

def test_openai_span_nonstream_success_attributes(llm_mod, monkeypatch):
    """Başarılı non-stream çağrıda tüm span attribute'ları set edilmeli, span_cm kapatılmalı."""
    tr = _Tracer()
    monkeypatch.setattr(llm_mod, "trace", _make_trace_mod(tr))
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _make_http_client(_ok_resp()))

    cfg = SimpleNamespace(
        OPENAI_API_KEY="test-key",
        OPENAI_MODEL="gpt-4o-mini",
        OPENAI_TIMEOUT=60,
        ENABLE_TRACING=True,
    )
    client = llm_mod.OpenAIClient(cfg)
    asyncio.run(client.chat([{"role": "user", "content": "merhaba"}], stream=False))

    assert tr.cm_name == "llm.openai.chat"
    assert tr.span.attrs["sidar.llm.provider"] == "openai"
    assert tr.span.attrs["sidar.llm.model"] == "gpt-4o-mini"
    assert tr.span.attrs["sidar.llm.stream"] is False
    assert "sidar.llm.total_ms" in tr.span.attrs
    assert tr.cm.closed is True


def test_openai_span_nonstream_error_closes_span(llm_mod, monkeypatch):
    """HTTP hatası (LLMAPIError) durumunda span_cm.__exit__ yine çağrılmalı."""
    tr = _Tracer()
    monkeypatch.setattr(llm_mod, "trace", _make_trace_mod(tr))

    class _FailClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json, headers):
            raise RuntimeError("ağ hatası")

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _FailClient)

    cfg = SimpleNamespace(
        OPENAI_API_KEY="test-key",
        OPENAI_MODEL="gpt-4o-mini",
        OPENAI_TIMEOUT=60,
        ENABLE_TRACING=True,
        LLM_MAX_RETRIES=0,
    )
    client = llm_mod.OpenAIClient(cfg)
    with pytest.raises(llm_mod.LLMAPIError):
        asyncio.run(client.chat([{"role": "user", "content": "x"}], stream=False))

    assert tr.span.attrs["sidar.llm.provider"] == "openai"
    assert tr.cm.closed is True


def test_openai_span_stream_uses_start_span(llm_mod, monkeypatch):
    """Stream modda start_span (context manager değil) kullanılmalı."""
    tr = _Tracer()
    monkeypatch.setattr(llm_mod, "trace", _make_trace_mod(tr))

    # _stream_openai sonucu aiter'dir; burada sadece span metodunu kontrol ediyoruz
    # NOT: async değil sync — kod doğrudan stream_iter = self._stream_openai(...) çağırır (await değil)
    def _fake_stream(*a, **kw):
        async def _gen():
            yield '{"tool":"final_answer","argument":"x"}'
        return _gen()

    cfg = SimpleNamespace(
        OPENAI_API_KEY="test-key",
        OPENAI_MODEL="gpt-4o-mini",
        OPENAI_TIMEOUT=60,
        ENABLE_TRACING=True,
    )
    client = llm_mod.OpenAIClient(cfg)
    client._stream_openai = _fake_stream

    result = asyncio.run(client.chat([{"role": "user", "content": "x"}], stream=True))
    # stream=True iken start_span çağrılmalı (start_as_current_span değil)
    assert tr.span_name == "llm.openai.chat"
    assert tr.cm_name is None  # start_as_current_span çağrılmamalı
    assert tr.span.attrs["sidar.llm.provider"] == "openai"
    assert tr.span.attrs["sidar.llm.stream"] is True


def test_openai_no_span_when_tracing_disabled(llm_mod, monkeypatch):
    """ENABLE_TRACING=False olduğunda span oluşturulmamalı."""
    tr = _Tracer()
    monkeypatch.setattr(llm_mod, "trace", _make_trace_mod(tr))
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _make_http_client(_ok_resp()))

    cfg = SimpleNamespace(
        OPENAI_API_KEY="test-key",
        OPENAI_MODEL="gpt-4o-mini",
        OPENAI_TIMEOUT=60,
        ENABLE_TRACING=False,
    )
    client = llm_mod.OpenAIClient(cfg)
    asyncio.run(client.chat([{"role": "user", "content": "x"}], stream=False))

    # tracer hiç kullanılmamalı
    assert tr.cm_name is None
    assert tr.span_name is None
    assert tr.span.attrs == {}


def test_openai_no_span_when_trace_module_none(llm_mod, monkeypatch):
    """trace modülü None iken span oluşturulmamalı."""

    class _Client:
        def __init__(self, timeout=None): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, json, headers): return _ok_resp()()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(llm_mod, "trace", None)

    cfg = SimpleNamespace(
        OPENAI_API_KEY="test-key",
        OPENAI_MODEL="gpt-4o-mini",
        OPENAI_TIMEOUT=60,
        ENABLE_TRACING=True,
    )
    client = llm_mod.OpenAIClient(cfg)
    result = asyncio.run(client.chat([{"role": "user", "content": "x"}], stream=False))
    assert result  # hatasız tamamlanmalı


# ══════════════════════════════════════════════════════════════════════════════
# LiteLLM Span Testleri
# ══════════════════════════════════════════════════════════════════════════════

def test_litellm_span_nonstream_success_attributes(llm_mod, monkeypatch):
    """Başarılı non-stream LiteLLM çağrıda span attribute'ları doğru set edilmeli."""
    tr = _Tracer()
    monkeypatch.setattr(llm_mod, "trace", _make_trace_mod(tr))
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _make_http_client(_ok_resp()))

    cfg = SimpleNamespace(
        LITELLM_GATEWAY_URL="http://localhost:4000",
        LITELLM_API_KEY="test-key",
        LITELLM_MODEL="gpt-4o-mini",
        LITELLM_FALLBACK_MODELS="",
        LITELLM_TIMEOUT=60,
        ENABLE_TRACING=True,
    )
    client = llm_mod.LiteLLMClient(cfg)
    asyncio.run(client.chat([{"role": "user", "content": "merhaba"}], stream=False))

    assert tr.cm_name == "llm.litellm.chat"
    assert tr.span.attrs["sidar.llm.provider"] == "litellm"
    assert tr.span.attrs["sidar.llm.stream"] is False
    assert "sidar.llm.model" in tr.span.attrs
    assert "sidar.llm.total_ms" in tr.span.attrs
    assert tr.cm.closed is True


def test_litellm_span_all_models_fail_closes_span(llm_mod, monkeypatch):
    """Tüm modeller başarısız olduğunda span_cm.__exit__ çağrılmalı."""
    tr = _Tracer()
    monkeypatch.setattr(llm_mod, "trace", _make_trace_mod(tr))

    class _FailClient:
        def __init__(self, timeout): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, json, headers):
            raise RuntimeError("gateway down")

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _FailClient)

    cfg = SimpleNamespace(
        LITELLM_GATEWAY_URL="http://localhost:4000",
        LITELLM_API_KEY="",
        LITELLM_MODEL="gpt-4o-mini",
        LITELLM_FALLBACK_MODELS="",
        LITELLM_TIMEOUT=60,
        ENABLE_TRACING=True,
        LLM_MAX_RETRIES=0,
    )
    client = llm_mod.LiteLLMClient(cfg)
    with pytest.raises(llm_mod.LLMAPIError):
        asyncio.run(client.chat([{"role": "user", "content": "x"}], stream=False))

    assert tr.span.attrs["sidar.llm.provider"] == "litellm"
    assert tr.cm.closed is True


def test_litellm_span_stream_uses_start_span(llm_mod, monkeypatch):
    """Stream modda LiteLLM start_span kullanmalı."""
    tr = _Tracer()
    monkeypatch.setattr(llm_mod, "trace", _make_trace_mod(tr))

    # NOT: async değil sync — kod doğrudan stream_iter = self._stream_openai_compatible(...) çağırır
    def _fake_compat(*a, **kw):
        async def _gen():
            yield '{"tool":"final_answer","argument":"x"}'
        return _gen()

    cfg = SimpleNamespace(
        LITELLM_GATEWAY_URL="http://localhost:4000",
        LITELLM_API_KEY="",
        LITELLM_MODEL="gpt-4o-mini",
        LITELLM_FALLBACK_MODELS="",
        LITELLM_TIMEOUT=60,
        ENABLE_TRACING=True,
    )
    client = llm_mod.LiteLLMClient(cfg)
    client._stream_openai_compatible = _fake_compat

    asyncio.run(client.chat([{"role": "user", "content": "x"}], stream=True))

    assert tr.span_name == "llm.litellm.chat"
    assert tr.cm_name is None
    assert tr.span.attrs["sidar.llm.provider"] == "litellm"
    assert tr.span.attrs["sidar.llm.stream"] is True


def test_litellm_fallback_model_used_on_first_failure(llm_mod, monkeypatch):
    """İlk model başarısız olunca fallback model denenmeli; başarıda span kapatılmalı."""
    tr = _Tracer()
    monkeypatch.setattr(llm_mod, "trace", _make_trace_mod(tr))

    call_count = {"n": 0}

    class _FlakyClient:
        def __init__(self, timeout): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, json, headers):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("first model fail")
            return _ok_resp()()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _FlakyClient)

    cfg = SimpleNamespace(
        LITELLM_GATEWAY_URL="http://localhost:4000",
        LITELLM_API_KEY="",
        LITELLM_MODEL="primary-model",
        LITELLM_FALLBACK_MODELS=["fallback-model"],   # list — _candidate_models iterates directly
        LITELLM_TIMEOUT=60,
        ENABLE_TRACING=True,
        LLM_MAX_RETRIES=0,
    )
    client = llm_mod.LiteLLMClient(cfg)
    asyncio.run(client.chat([{"role": "user", "content": "x"}], stream=False))

    assert call_count["n"] == 2
    # fallback model adı span'a yazılmış olmalı
    assert tr.span.attrs.get("sidar.llm.model") == "fallback-model"
    assert tr.cm.closed is True


def test_litellm_no_span_when_url_missing(llm_mod, monkeypatch):
    """LITELLM_GATEWAY_URL yokken erken dönüş yapılmalı; span oluşturulmamalı."""
    tr = _Tracer()
    monkeypatch.setattr(llm_mod, "trace", _make_trace_mod(tr))

    cfg = SimpleNamespace(
        LITELLM_GATEWAY_URL="",
        LITELLM_API_KEY="",
        LITELLM_MODEL="gpt-4o-mini",
        LITELLM_FALLBACK_MODELS="",
        LITELLM_TIMEOUT=60,
        ENABLE_TRACING=True,
    )
    client = llm_mod.LiteLLMClient(cfg)
    result = asyncio.run(client.chat([{"role": "user", "content": "x"}], stream=False))

    # Span hiç oluşturulmamalı (URL kontrolü span öncesinde)
    assert tr.cm_name is None
    assert tr.span_name is None
    assert "LITELLM_GATEWAY_URL" in result
