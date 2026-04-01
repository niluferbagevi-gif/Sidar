import importlib
import logging
import os
import sys
import types
from pathlib import Path

import pytest

import config


@pytest.fixture(autouse=True)
def reset_singleton_and_hardware(monkeypatch):
    monkeypatch.setattr(config, "_config_instance", None, raising=False)
    monkeypatch.setattr(config.Config, "_hardware_loaded", False, raising=False)


def test_get_bool_env_variants(monkeypatch):
    monkeypatch.delenv("BOOL_KEY", raising=False)
    assert config.get_bool_env("BOOL_KEY", default=True) is True

    monkeypatch.setenv("BOOL_KEY", " yes ")
    assert config.get_bool_env("BOOL_KEY", default=False) is True

    monkeypatch.setenv("BOOL_KEY", "0")
    assert config.get_bool_env("BOOL_KEY", default=True) is False

    monkeypatch.setenv("BOOL_KEY", "   ")
    assert config.get_bool_env("BOOL_KEY", default=False) is False


def test_get_int_and_float_env_fallback(monkeypatch):
    monkeypatch.setenv("INT_KEY", "10")
    assert config.get_int_env("INT_KEY", default=1) == 10

    monkeypatch.setenv("INT_KEY", "abc")
    assert config.get_int_env("INT_KEY", default=7) == 7

    monkeypatch.setenv("FLOAT_KEY", "1.25")
    assert config.get_float_env("FLOAT_KEY", default=0.5) == 1.25

    monkeypatch.setenv("FLOAT_KEY", "bad")
    assert config.get_float_env("FLOAT_KEY", default=0.75) == 0.75


def test_get_list_env(monkeypatch):
    monkeypatch.delenv("LIST_KEY", raising=False)
    assert config.get_list_env("LIST_KEY", ["a"]) == ["a"]

    monkeypatch.setenv("LIST_KEY", "a, b ,, c")
    assert config.get_list_env("LIST_KEY") == ["a", "b", "c"]

    monkeypatch.setenv("LIST_KEY", "x|y|z")
    assert config.get_list_env("LIST_KEY", separator="|") == ["x", "y", "z"]


def test_is_wsl2_true_and_false(monkeypatch):
    class FakePath:
        def __init__(self, content, raises=False):
            self.content = content
            self.raises = raises

        def read_text(self):
            if self.raises:
                raise OSError("boom")
            return self.content

    monkeypatch.setattr(config, "Path", lambda *_args, **_kwargs: FakePath("5.10.16.3-microsoft-standard"))
    assert config._is_wsl2() is True

    monkeypatch.setattr(config, "Path", lambda *_args, **_kwargs: FakePath("linux"))
    assert config._is_wsl2() is False

    monkeypatch.setattr(config, "Path", lambda *_args, **_kwargs: FakePath("", raises=True))
    assert config._is_wsl2() is False


def test_check_hardware_use_gpu_disabled(monkeypatch):
    monkeypatch.setenv("USE_GPU", "false")
    hw = config.check_hardware()
    assert hw.has_cuda is False
    assert hw.gpu_name == "Devre Dışı (Kullanıcı)"


def test_check_hardware_with_cuda_and_fraction(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("GPU_MEMORY_FRACTION", "0.6")
    monkeypatch.delenv("LLM_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.delenv("RAG_GPU_MEMORY_FRACTION", raising=False)

    calls = {}

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 2

        @staticmethod
        def get_device_name(_idx):
            return "FakeGPU"

        @staticmethod
        def set_per_process_memory_fraction(frac, device=0):
            calls["frac"] = frac
            calls["device"] = device

    fake_torch = types.SimpleNamespace(cuda=FakeCuda, version=types.SimpleNamespace(cuda="12.4"))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    hw = config.check_hardware()

    assert hw.has_cuda is True
    assert hw.gpu_name == "FakeGPU"
    assert hw.gpu_count == 2
    assert hw.cuda_version == "12.4"
    assert calls == {"frac": 0.6, "device": 0}


def test_check_hardware_import_error(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("no torch")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    hw = config.check_hardware()
    assert hw.gpu_name == "PyTorch Yok"


def test_config_initialize_directories(monkeypatch, tmp_path):
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    monkeypatch.setattr(config.Config, "REQUIRED_DIRS", [d1, d2], raising=False)
    assert config.Config.initialize_directories() is True
    assert d1.exists() and d2.exists()


def test_set_provider_mode_valid_and_invalid(monkeypatch):
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    config.Config.set_provider_mode("online")
    assert config.Config.AI_PROVIDER == "gemini"

    config.Config.set_provider_mode("invalid-provider")
    assert config.Config.AI_PROVIDER == "gemini"


def test_ensure_hardware_info_loaded_gpu_disabled(monkeypatch):
    monkeypatch.setattr(config.Config, "USE_GPU", False, raising=False)
    monkeypatch.setattr(config.Config, "_hardware_loaded", False, raising=False)

    config.Config._ensure_hardware_info_loaded()

    assert config.Config._hardware_loaded is True
    assert config.Config.GPU_INFO == "Devre Dışı / CPU Modu"
    assert config.Config.GPU_COUNT == 0


def test_ensure_hardware_info_loaded_gpu_enabled(monkeypatch):
    fake = config.HardwareInfo(
        has_cuda=True,
        gpu_name="GPU-X",
        gpu_count=3,
        cpu_count=8,
        cuda_version="12.1",
        driver_version="550",
    )
    monkeypatch.setattr(config, "check_hardware", lambda: fake)
    monkeypatch.setattr(config.Config, "USE_GPU", True, raising=False)
    monkeypatch.setattr(config.Config, "_hardware_loaded", False, raising=False)

    config.Config._ensure_hardware_info_loaded()

    assert config.Config.USE_GPU is True
    assert config.Config.GPU_INFO == "GPU-X"
    assert config.Config.GPU_COUNT == 3
    assert config.Config.CPU_COUNT == 8
    assert config.Config.CUDA_VERSION == "12.1"
    assert config.Config.DRIVER_VERSION == "550"


def test_validate_critical_settings_gemini_missing_key(monkeypatch):
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "gemini", raising=False)
    monkeypatch.setattr(config.Config, "GEMINI_API_KEY", "", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None), raising=False)
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True), raising=False)

    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_ollama_happy_path(monkeypatch):
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://localhost:11434/api", raising=False)
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None), raising=False)
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True), raising=False)

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            assert url.endswith("/tags")
            return FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(Client=FakeClient))

    assert config.Config.validate_critical_settings() is True


def test_get_system_info(monkeypatch):
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None), raising=False)
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar", raising=False)
    monkeypatch.setattr(config.Config, "VERSION", "5.2.0", raising=False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)

    info = config.Config.get_system_info()
    assert info["project"] == "Sidar"
    assert info["version"] == "5.2.0"
    assert info["provider"] == "ollama"
    assert "REDIS_URL" not in info


def test_init_telemetry_disabled(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", False, raising=False)
    assert config.Config.init_telemetry() is False


def test_init_telemetry_success(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_SERVICE_NAME", "sidar", raising=False)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel:4317", raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", True, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", True, raising=False)

    class FakeResource:
        @staticmethod
        def create(data):
            return data

    class FakeProvider:
        def __init__(self, resource):
            self.resource = resource
            self.added = []

        def add_span_processor(self, processor):
            self.added.append(processor)

    class FakeExporter:
        def __init__(self, endpoint, insecure):
            self.endpoint = endpoint
            self.insecure = insecure

    class FakeBatch:
        def __init__(self, exporter):
            self.exporter = exporter

    class FakeTrace:
        def __init__(self):
            self.provider = None

        def set_tracer_provider(self, provider):
            self.provider = provider

    class FakeFastAPIInstrumentor:
        called = False

        @classmethod
        def instrument_app(cls, app):
            cls.called = True

    class FakeHTTPXInstrumentor:
        called = False

        def instrument(self):
            self.__class__.called = True

    trace = FakeTrace()
    ok = config.Config.init_telemetry(
        fastapi_app=object(),
        trace_module=trace,
        otlp_exporter_cls=FakeExporter,
        tracer_provider_cls=FakeProvider,
        resource_cls=FakeResource,
        batch_span_processor_cls=FakeBatch,
        fastapi_instrumentor_cls=FakeFastAPIInstrumentor,
        httpx_instrumentor_cls=FakeHTTPXInstrumentor,
    )
    assert ok is True
    assert isinstance(trace.provider, FakeProvider)
    assert FakeFastAPIInstrumentor.called is True
    assert FakeHTTPXInstrumentor.called is True


def test_init_telemetry_import_failure(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True, raising=False)

    class DummyLogger:
        def __init__(self):
            self.warned = False

        def warning(self, *_args, **_kwargs):
            self.warned = True

    log = DummyLogger()

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    assert config.Config.init_telemetry(logger_obj=log) is False
    assert log.warned is True


def test_print_config_summary(monkeypatch, capsys):
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar", raising=False)
    monkeypatch.setattr(config.Config, "VERSION", "5.2.0", raising=False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(config.Config, "USE_GPU", False, raising=False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "CPU", raising=False)
    monkeypatch.setattr(config.Config, "CPU_COUNT", 4, raising=False)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full", raising=False)
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False, raising=False)
    monkeypatch.setattr(config.Config, "CODING_MODEL", "code", raising=False)
    monkeypatch.setattr(config.Config, "TEXT_MODEL", "text", raising=False)
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    config.Config.print_config_summary()
    out = capsys.readouterr().out
    assert "Yapılandırma Özeti" in out
    assert "AI Sağlayıcı" in out


def test_get_config_singleton(monkeypatch):
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None), raising=False)
    c1 = config.get_config()
    c2 = config.get_config()
    assert c1 is c2


def test_reload_config_without_dotenv(monkeypatch):
    # dotenv modülü yoksa fallback load_dotenv fonksiyonu devreye girmeli.
    monkeypatch.setitem(sys.modules, "dotenv", None)
    mod = importlib.reload(config)
    assert callable(mod.load_dotenv)
    importlib.reload(mod)
