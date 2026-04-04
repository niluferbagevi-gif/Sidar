from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import config


def test_check_hardware_handles_missing_torch(monkeypatch) -> None:
    original_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("torch missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(config, "_is_wsl2", lambda: False)
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr("builtins.__import__", _fake_import)

    info = config.check_hardware()
    assert info.gpu_name == "PyTorch Yok"
    assert info.has_cuda is False


def test_validate_critical_settings_requires_provider_keys(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False, raising=False)

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "gemini", raising=False)
    monkeypatch.setattr(config.Config, "GEMINI_API_KEY", "", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    assert config.Config.validate_critical_settings() is False



def test_validate_critical_settings_litellm_gateway_required(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False, raising=False)

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "litellm", raising=False)
    monkeypatch.setattr(config.Config, "LITELLM_GATEWAY_URL", "", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_invalid_memory_key(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False, raising=False)

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "not-a-fernet-key", raising=False)

    class _BadFernet:
        def __init__(self, _raw: bytes) -> None:
            raise ValueError("bad key")

    fake_fernet_module = SimpleNamespace(Fernet=_BadFernet)
    monkeypatch.setitem(__import__("sys").modules, "cryptography.fernet", fake_fernet_module)

    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_fails_when_gpu_required_but_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", True, raising=False)
    monkeypatch.setattr(config.Config, "USE_GPU", False, raising=False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    assert config.Config.validate_critical_settings() is False


def test_env_parsers_and_wsl2_fallback(monkeypatch) -> None:
    monkeypatch.setenv("X_INT", "abc")
    monkeypatch.setenv("X_FLOAT", "abc")
    monkeypatch.delenv("X_LIST", raising=False)

    assert config.get_int_env("X_INT", 11) == 11
    assert config.get_float_env("X_FLOAT", 1.2) == 1.2
    assert config.get_list_env("X_LIST", None) == []

    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("boom")))
    assert config._is_wsl2() is False


def test_check_hardware_gpu_disabled(monkeypatch) -> None:
    monkeypatch.setenv("USE_GPU", "false")
    info = config.check_hardware()
    assert info.gpu_name == "Devre Dışı (Kullanıcı)"
    assert info.has_cuda is False


def test_check_hardware_fraction_and_optional_dependency_paths(monkeypatch) -> None:
    class _Cuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def device_count() -> int:
            return 1

        @staticmethod
        def get_device_name(_idx: int) -> str:
            return "FakeGPU"

        @staticmethod
        def set_per_process_memory_fraction(_frac: float, device: int = 0) -> None:
            raise RuntimeError("cannot set")

    fake_torch = SimpleNamespace(cuda=_Cuda(), version=SimpleNamespace(cuda="12.4"))

    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "torch":
            return fake_torch
        if name == "pynvml":
            return SimpleNamespace(
                nvmlInit=lambda: None,
                nvmlSystemGetDriverVersion=lambda: "555.10",
                nvmlShutdown=lambda: None,
            )
        if name == "multiprocessing":
            raise RuntimeError("no cpu count")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("GPU_MEMORY_FRACTION", "2.0")
    monkeypatch.delenv("LLM_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.delenv("RAG_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    info = config.check_hardware()
    assert info.has_cuda is True
    assert info.gpu_name == "FakeGPU"
    assert info.driver_version == "555.10"
    assert info.cpu_count == 1


def test_check_hardware_generic_exception_path(monkeypatch) -> None:
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "torch":
            raise RuntimeError("unexpected")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)
    monkeypatch.setenv("USE_GPU", "true")

    info = config.check_hardware()
    assert info.gpu_name == "Tespit Edilemedi"


def test_config_hardware_lazy_load_cpu_branch(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "USE_GPU", False, raising=False)
    monkeypatch.setattr(config.Config, "_hardware_loaded", False, raising=False)

    config.Config._ensure_hardware_info_loaded()

    assert config.Config.GPU_INFO == "Devre Dışı / CPU Modu"
    assert config.Config.CUDA_VERSION == "N/A"
    assert config.Config._hardware_loaded is True


def test_initialize_directories_failure(monkeypatch, tmp_path) -> None:
    importlib.reload(config)
    bad_dir = tmp_path / "blocked"
    monkeypatch.setattr(config.Config, "REQUIRED_DIRS", [bad_dir], raising=False)
    monkeypatch.setattr(Path, "mkdir", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("nope")))
    assert config.Config.initialize_directories() is False


def test_set_provider_mode_valid_and_invalid(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    config.Config.set_provider_mode("online")
    assert config.Config.AI_PROVIDER == "gemini"

    config.Config.set_provider_mode("invalid-mode")
    assert config.Config.AI_PROVIDER == "gemini"


def test_validate_critical_settings_importerror_and_provider_keys(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False, raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "x", raising=False)

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "openai", raising=False)
    monkeypatch.setattr(config.Config, "OPENAI_API_KEY", "", raising=False)

    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "cryptography.fernet":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    assert config.Config.validate_critical_settings() is False

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "anthropic", raising=False)
    monkeypatch.setattr(config.Config, "ANTHROPIC_API_KEY", "", raising=False)
    monkeypatch.setattr("builtins.__import__", original_import)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)
    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_ollama_url_variants(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False, raising=False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    class _Resp:
        def __init__(self, status_code: int):
            self.status_code = status_code

    called_urls: list[str] = []

    class _Client:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url: str):
            called_urls.append(url)
            if len(called_urls) == 1:
                return _Resp(500)
            raise RuntimeError("offline")

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(Client=_Client))

    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://localhost:11434", raising=False)
    assert config.Config.validate_critical_settings() is True
    assert called_urls[-1].endswith("/api/tags")

    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://localhost:11434/api", raising=False)
    assert config.Config.validate_critical_settings() is True
    assert called_urls[-1].endswith("/tags")


def test_get_system_info_calls_lazy_loader(monkeypatch) -> None:
    called = {"v": False}

    def _mark(cls):
        called["v"] = True

    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(_mark))
    info = config.Config.get_system_info()

    assert called["v"] is True
    assert "provider" in info


def test_init_telemetry_import_failure(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True, raising=False)
    assert config.Config.init_telemetry(trace_module=None, otlp_exporter_cls=None, tracer_provider_cls=None) is False


def test_init_telemetry_success_and_runtime_failure(monkeypatch) -> None:
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel:4317", raising=False)
    monkeypatch.setattr(config.Config, "OTEL_SERVICE_NAME", "sidar-tests", raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", True, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", True, raising=False)

    class _Trace:
        provider = None

        @staticmethod
        def set_tracer_provider(provider):
            _Trace.provider = provider

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

    class _Batch:
        def __init__(self, exporter):
            self.exporter = exporter

    class _FastAPIInstr:
        called = False

        @classmethod
        def instrument_app(cls, _app):
            cls.called = True

    class _HttpxInstr:
        called = False

        def instrument(self):
            _HttpxInstr.called = True

    ok = config.Config.init_telemetry(
        fastapi_app=object(),
        trace_module=_Trace,
        otlp_exporter_cls=_Exporter,
        tracer_provider_cls=_Provider,
        resource_cls=_Resource,
        batch_span_processor_cls=_Batch,
        fastapi_instrumentor_cls=_FastAPIInstr,
        httpx_instrumentor_cls=_HttpxInstr,
    )
    assert ok is True
    assert _FastAPIInstr.called is True
    assert _HttpxInstr.called is True

    class _ExplodingProvider:
        def __init__(self, resource):
            raise RuntimeError("boom")

    fail = config.Config.init_telemetry(
        trace_module=_Trace,
        otlp_exporter_cls=_Exporter,
        tracer_provider_cls=_ExplodingProvider,
        resource_cls=_Resource,
        batch_span_processor_cls=_Batch,
    )
    assert fail is False


def test_print_config_summary_provider_branches(monkeypatch, capsys) -> None:
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar", raising=False)
    monkeypatch.setattr(config.Config, "VERSION", "x", raising=False)
    monkeypatch.setattr(config.Config, "USE_GPU", True, raising=False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "FakeGPU", raising=False)
    monkeypatch.setattr(config.Config, "CUDA_VERSION", "12.4", raising=False)
    monkeypatch.setattr(config.Config, "GPU_COUNT", 1, raising=False)
    monkeypatch.setattr(config.Config, "GPU_DEVICE", "0", raising=False)
    monkeypatch.setattr(config.Config, "GPU_MIXED_PRECISION", True, raising=False)
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", 0.5, raising=False)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 0.2, raising=False)
    monkeypatch.setattr(config.Config, "DRIVER_VERSION", "555", raising=False)
    monkeypatch.setattr(config.Config, "CPU_COUNT", 8, raising=False)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full", raising=False)
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False, raising=False)
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "openai", raising=False)
    monkeypatch.setattr(config.Config, "OPENAI_MODEL", "gpt", raising=False)
    config.Config.print_config_summary()

    monkeypatch.setattr(config.Config, "USE_GPU", False, raising=False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "anthropic", raising=False)
    monkeypatch.setattr(config.Config, "ANTHROPIC_MODEL", "claude", raising=False)
    config.Config.print_config_summary()

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "litellm", raising=False)
    monkeypatch.setattr(config.Config, "LITELLM_GATEWAY_URL", "", raising=False)
    monkeypatch.setattr(config.Config, "LITELLM_MODEL", "", raising=False)
    config.Config.print_config_summary()

    output = capsys.readouterr().out
    assert "OpenAI Modeli" in output
    assert "Anthropic Modeli" in output
    assert "LiteLLM Gateway" in output


def test_import_time_env_branches_reload(monkeypatch, tmp_path, capsys) -> None:
    base_env = tmp_path / ".env"
    base_env.write_text("A=1\n", encoding="utf-8")

    original_resolve = Path.resolve
    original_exists = Path.exists

    def _fake_resolve(self: Path):
        if str(self).endswith("config.py"):
            return tmp_path / "config.py"
        return original_resolve(self)

    def _fake_exists(self: Path):
        if self == tmp_path / ".env":
            return True
        if self == tmp_path / ".env.qa":
            return False
        return original_exists(self)

    monkeypatch.setenv("SIDAR_ENV", "qa")
    monkeypatch.setattr(Path, "resolve", _fake_resolve)
    monkeypatch.setattr(Path, "exists", _fake_exists)

    importlib.reload(config)
    output = capsys.readouterr().out
    assert ".env.qa" in output

    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.setattr(Path, "exists", lambda _self: False)
    importlib.reload(config)
    output = capsys.readouterr().out
    assert "'.env' dosyası bulunamadı" in output
