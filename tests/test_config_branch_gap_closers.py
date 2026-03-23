import builtins
import importlib.util
import sys
import types
from pathlib import Path


def _load_config_module(module_name: str, dotenv_module=None):
    saved = sys.modules.get("dotenv")
    try:
        if dotenv_module is None:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = dotenv_module
        spec = importlib.util.spec_from_file_location(module_name, Path("config.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        if saved is None:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = saved


class _TraceModule:
    provider = None

    @classmethod
    def set_tracer_provider(cls, provider):
        cls.provider = provider


class _Resource:
    @staticmethod
    def create(payload):
        return payload


class _Provider:
    def __init__(self, resource):
        self.resource = resource
        self.processors = []

    def add_span_processor(self, processor):
        self.processors.append(processor)


class _Exporter:
    def __init__(self, endpoint, insecure):
        self.endpoint = endpoint
        self.insecure = insecure


class _BatchSpanProcessor:
    def __init__(self, exporter):
        self.exporter = exporter


def test_config_import_without_dotenv_module_uses_fallback_loader_and_defaults(monkeypatch, capsys):
    real_import = builtins.__import__

    def _import_without_dotenv(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "dotenv":
            raise ModuleNotFoundError("dotenv missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import_without_dotenv)
    monkeypatch.setenv("SIDAR_ENV", "broken-profile")
    monkeypatch.setattr(Path, "exists", lambda _self: False)

    cfg_mod = _load_config_module("config_branch_gap_missing_dotenv")

    out = capsys.readouterr().out
    assert "Belirtilen ortam dosyası bulunamadı: .env.broken-profile" in out
    assert cfg_mod.load_dotenv(dotenv_path="ignored") is False
    assert cfg_mod.Config.AI_PROVIDER in {"ollama", "gemini", "openai", "anthropic", "litellm"}


def test_init_telemetry_skips_optional_fastapi_and_httpx_instrumentation_when_not_applicable(monkeypatch):
    cfg_mod = _load_config_module("config_branch_gap_telemetry", types.SimpleNamespace(load_dotenv=lambda *a, **k: None))
    cfg_mod.Config.ENABLE_TRACING = True
    cfg_mod.Config.OTEL_EXPORTER_ENDPOINT = "http://otel:4317"
    cfg_mod.Config.OTEL_SERVICE_NAME = "sidar-test"
    cfg_mod.Config.OTEL_INSTRUMENT_FASTAPI = True
    cfg_mod.Config.OTEL_INSTRUMENT_HTTPX = False

    logger_calls = {"info": [], "warning": []}
    logger_obj = types.SimpleNamespace(
        info=lambda msg, *a: logger_calls["info"].append(msg % a if a else msg),
        warning=lambda msg, *a: logger_calls["warning"].append(msg % a if a else msg),
    )

    fastapi_calls = []

    class _FastAPIInstrumentor:
        @staticmethod
        def instrument_app(_app):
            fastapi_calls.append("instrumented")

    ok = cfg_mod.Config.init_telemetry(
        fastapi_app=None,
        logger_obj=logger_obj,
        trace_module=_TraceModule,
        otlp_exporter_cls=_Exporter,
        tracer_provider_cls=_Provider,
        resource_cls=_Resource,
        batch_span_processor_cls=_BatchSpanProcessor,
        fastapi_instrumentor_cls=_FastAPIInstrumentor,
        httpx_instrumentor_cls=lambda: (_ for _ in ()).throw(AssertionError("httpx should not run")),
    )

    assert ok is True
    assert fastapi_calls == []
    assert logger_calls["warning"] == []
    assert any("OpenTelemetry aktif" in msg for msg in logger_calls["info"])
    assert isinstance(_TraceModule.provider, _Provider)


def test_config_summary_gpu_without_driver_version_omits_driver_line(capsys):
    cfg_mod = _load_config_module("config_branch_gap_summary", types.SimpleNamespace(load_dotenv=lambda *a, **k: None))
    cfg_mod.Config.USE_GPU = True
    cfg_mod.Config.GPU_INFO = "RTX 5000"
    cfg_mod.Config.CUDA_VERSION = "12.4"
    cfg_mod.Config.GPU_COUNT = 1
    cfg_mod.Config.GPU_DEVICE = 0
    cfg_mod.Config.GPU_MIXED_PRECISION = False
    cfg_mod.Config.LLM_GPU_MEMORY_FRACTION = 0.5
    cfg_mod.Config.RAG_GPU_MEMORY_FRACTION = 0.25
    cfg_mod.Config.DRIVER_VERSION = "N/A"
    cfg_mod.Config.AI_PROVIDER = "openai"
    cfg_mod.Config.OPENAI_MODEL = "gpt-test"

    cfg_mod.Config.print_config_summary()
    out = capsys.readouterr().out

    assert "GPU              : ✓ RTX 5000  (CUDA 12.4)" in out
    assert "GPU Sayısı       : 1" in out
    assert "Sürücü Sürümü" not in out
    assert "OpenAI Modeli    : gpt-test" in out
