import config
import types
import os
from pathlib import Path
import importlib

import pytest


def test_get_bool_env_truthy_and_default(monkeypatch):
    monkeypatch.setenv("FLAG_A", " yes ")
    monkeypatch.setenv("FLAG_B", "0")
    monkeypatch.delenv("FLAG_C", raising=False)

    assert config.get_bool_env("FLAG_A", False) is True
    assert config.get_bool_env("FLAG_B", True) is False
    assert config.get_bool_env("FLAG_C", True) is True


def test_get_int_float_and_list_env_parsing(monkeypatch):
    monkeypatch.setenv("INT_OK", "42")
    monkeypatch.setenv("INT_BAD", "abc")
    monkeypatch.setenv("FLOAT_OK", "3.14")
    monkeypatch.setenv("FLOAT_BAD", "-")
    monkeypatch.setenv("LIST_VAL", " a, b ,, c ")
    monkeypatch.delenv("LIST_EMPTY", raising=False)

    assert config.get_int_env("INT_OK", 7) == 42
    assert config.get_int_env("INT_BAD", 7) == 7
    assert config.get_float_env("FLOAT_OK", 1.2) == 3.14
    assert config.get_float_env("FLOAT_BAD", 1.2) == 1.2
    assert config.get_list_env("LIST_VAL", []) == ["a", "b", "c"]
    assert config.get_list_env("LIST_EMPTY", ["fallback"]) == ["fallback"]
    assert config.get_list_env("LIST_EMPTY", None) == []


def test_set_provider_mode_maps_and_rejects_invalid(monkeypatch):
    original = config.Config.AI_PROVIDER
    config.Config.AI_PROVIDER = "ollama"

    config.Config.set_provider_mode("online")
    assert config.Config.AI_PROVIDER == "gemini"

    config.Config.set_provider_mode("local")
    assert config.Config.AI_PROVIDER == "ollama"

    config.Config.set_provider_mode("invalid-provider")
    assert config.Config.AI_PROVIDER == "ollama"

    config.Config.AI_PROVIDER = original


def test_ensure_hardware_info_loaded_cpu_only(monkeypatch):
    monkeypatch.setattr(config.Config, "_hardware_loaded", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "x")
    monkeypatch.setattr(config.Config, "GPU_COUNT", 99)
    monkeypatch.setattr(config.Config, "CUDA_VERSION", "x")
    monkeypatch.setattr(config.Config, "DRIVER_VERSION", "x")

    config.Config._ensure_hardware_info_loaded()

    assert config.Config._hardware_loaded is True
    assert config.Config.USE_GPU is False
    assert config.Config.GPU_INFO == "Devre Dışı / CPU Modu"
    assert config.Config.GPU_COUNT == 0
    assert config.Config.CUDA_VERSION == "N/A"
    assert config.Config.DRIVER_VERSION == "N/A"
    assert config.Config.CPU_COUNT >= 1


def test_get_system_info_sanitizes_sensitive_fields(monkeypatch):
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full")
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "CPU")
    monkeypatch.setattr(config.Config, "GPU_COUNT", 0)
    monkeypatch.setattr(config.Config, "GPU_DEVICE", 0)
    monkeypatch.setattr(config.Config, "CUDA_VERSION", "N/A")
    monkeypatch.setattr(config.Config, "DRIVER_VERSION", "N/A")
    monkeypatch.setattr(config.Config, "MULTI_GPU", False)
    monkeypatch.setattr(config.Config, "GPU_MIXED_PRECISION", False)
    monkeypatch.setattr(config.Config, "GPU_MEMORY_FRACTION", 0.8)
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", 0.8)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 0.2)
    monkeypatch.setattr(config.Config, "CPU_COUNT", 4)
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False)
    monkeypatch.setattr(config.Config, "WEB_PORT", 7860)
    monkeypatch.setattr(config.Config, "WEB_GPU_PORT", 7861)
    monkeypatch.setattr(config.Config, "HF_HUB_OFFLINE", False)
    monkeypatch.setattr(config.Config, "RATE_LIMIT_WINDOW", 60)
    monkeypatch.setattr(config.Config, "RATE_LIMIT_CHAT", 20)
    monkeypatch.setattr(config.Config, "RATE_LIMIT_MUTATIONS", 60)
    monkeypatch.setattr(config.Config, "RATE_LIMIT_GET_IO", 30)
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", False)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://jaeger:4317")
    monkeypatch.setattr(config.Config, "ENABLE_SEMANTIC_CACHE", False)
    monkeypatch.setattr(config.Config, "SEMANTIC_CACHE_THRESHOLD", 0.95)
    monkeypatch.setattr(config.Config, "SEMANTIC_CACHE_TTL", 3600)
    monkeypatch.setattr(config.Config, "SEMANTIC_CACHE_MAX_ITEMS", 500)

    info = config.Config.get_system_info()

    assert info["provider"] == "ollama"
    assert info["gpu_enabled"] is False
    assert "REDIS_URL" not in info


def test_get_config_returns_singleton(monkeypatch):
    monkeypatch.setattr(config, "_config_instance", None)
    first = config.get_config()
    second = config.get_config()

    assert first is second


def test_is_wsl2_returns_false_on_read_error(monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(OSError("x")))
    assert config._is_wsl2() is False


def test_check_hardware_paths(monkeypatch):
    monkeypatch.setenv("USE_GPU", "false")
    info = config.check_hardware()
    assert info.gpu_name == "Devre Dışı (Kullanıcı)"

    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("no torch")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    info2 = config.check_hardware()
    assert info2.gpu_name == "PyTorch Yok"


def test_initialize_directories_returns_false_when_mkdir_fails(monkeypatch):
    class _BadDir:
        name = "bad"

        def mkdir(self, **_kwargs):
            raise RuntimeError("fail")

    monkeypatch.setattr(config.Config, "REQUIRED_DIRS", [_BadDir()])
    assert config.Config.initialize_directories() is False


def test_validate_critical_settings_provider_and_memory_branches(monkeypatch):
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", True)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(config.Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config.Config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config.Config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config.Config, "LITELLM_GATEWAY_URL", "")
    assert config.Config.validate_critical_settings() is False

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "openai")
    assert config.Config.validate_critical_settings() is False

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "anthropic")
    assert config.Config.validate_critical_settings() is False

    monkeypatch.setattr(config.Config, "AI_PROVIDER", "litellm")
    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_ollama_http_paths(monkeypatch):
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://x")

    class _Resp:
        def __init__(self, status_code):
            self.status_code = status_code

    class _ClientOK:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, _url):
            return _Resp(200)

    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientOK))
    assert config.Config.validate_critical_settings() is True

    class _ClientBad(_ClientOK):
        def get(self, _url):
            return _Resp(503)

    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientBad))
    assert config.Config.validate_critical_settings() is True


def test_init_telemetry_branches(monkeypatch):
    class _Log:
        def __init__(self):
            self.warned = []
            self.info_msg = []

        def warning(self, msg, *args):
            self.warned.append(msg % args if args else msg)

        def info(self, msg, *args):
            self.info_msg.append(msg % args if args else msg)

    log = _Log()
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", False)
    assert config.Config.init_telemetry(logger_obj=log) is False

    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)
    assert config.Config.init_telemetry(logger_obj=log, trace_module=None) is False

    class _Trace:
        def set_tracer_provider(self, _provider):
            return None

    class _Resource:
        @staticmethod
        def create(_obj):
            return object()

    class _Provider:
        def __init__(self, resource):
            self.resource = resource

        def add_span_processor(self, _processor):
            return None

    class _Exporter:
        def __init__(self, endpoint, insecure):
            self.endpoint = endpoint
            self.insecure = insecure

    class _Batch:
        def __init__(self, exporter):
            self.exporter = exporter

    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", False)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel")
    assert (
        config.Config.init_telemetry(
            logger_obj=log,
            trace_module=_Trace(),
            otlp_exporter_cls=_Exporter,
            tracer_provider_cls=_Provider,
            resource_cls=_Resource,
            batch_span_processor_cls=_Batch,
        )
        is True
    )


@pytest.mark.parametrize("provider", ["ollama", "gemini", "openai", "litellm", "anthropic"])
def test_print_config_summary_provider_branches(monkeypatch, capsys, provider):
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar")
    monkeypatch.setattr(config.Config, "VERSION", "x")
    monkeypatch.setattr(config.Config, "AI_PROVIDER", provider)
    monkeypatch.setattr(config.Config, "USE_GPU", True)
    monkeypatch.setattr(config.Config, "GPU_INFO", "GPU")
    monkeypatch.setattr(config.Config, "CUDA_VERSION", "12")
    monkeypatch.setattr(config.Config, "GPU_COUNT", 1)
    monkeypatch.setattr(config.Config, "GPU_DEVICE", 0)
    monkeypatch.setattr(config.Config, "GPU_MIXED_PRECISION", False)
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", 0.7)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 0.3)
    monkeypatch.setattr(config.Config, "DRIVER_VERSION", "N/A")
    monkeypatch.setattr(config.Config, "CPU_COUNT", 4)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full")
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False)
    monkeypatch.setattr(config.Config, "CODING_MODEL", "code")
    monkeypatch.setattr(config.Config, "TEXT_MODEL", "text")
    monkeypatch.setattr(config.Config, "GEMINI_MODEL", "gem")
    monkeypatch.setattr(config.Config, "OPENAI_MODEL", "gpt")
    monkeypatch.setattr(config.Config, "LITELLM_GATEWAY_URL", "http://lite")
    monkeypatch.setattr(config.Config, "LITELLM_MODEL", "lite")
    monkeypatch.setattr(config.Config, "ANTHROPIC_MODEL", "claude")
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    config.Config.print_config_summary()
    assert "Yapılandırma Özeti" in capsys.readouterr().out


def test_print_config_summary_cpu_branch(monkeypatch, capsys):
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar")
    monkeypatch.setattr(config.Config, "VERSION", "x")
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "CPU")
    monkeypatch.setattr(config.Config, "CPU_COUNT", 2)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "sandbox")
    monkeypatch.setattr(config.Config, "DEBUG_MODE", True)
    monkeypatch.setattr(config.Config, "ANTHROPIC_MODEL", "claude")
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "x")
    config.Config.print_config_summary()
    out = capsys.readouterr().out
    assert "CPU Modu" in out
    assert "Bellek Şifreleme : Etkin" in out


def test_validate_critical_settings_memory_key_and_crypto_missing(monkeypatch):
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://x")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "not-a-valid-fernet")

    class _Resp:
        status_code = 200

    class _ClientOK:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, _url):
            return _Resp()

    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientOK))
    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_ollama_client_exception(monkeypatch):
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://x")

    class _ClientBoom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientBoom))
    assert config.Config.validate_critical_settings() is True


def test_init_telemetry_runtime_failure(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel")

    class _Trace:
        def set_tracer_provider(self, _provider):
            raise RuntimeError("set fail")

    class _Resource:
        @staticmethod
        def create(_obj):
            return object()

    class _Provider:
        def __init__(self, resource):
            self.resource = resource
        def add_span_processor(self, _processor):
            return None

    class _Exporter:
        def __init__(self, endpoint, insecure):
            pass

    class _Batch:
        def __init__(self, exporter):
            pass

    assert (
        config.Config.init_telemetry(
            trace_module=_Trace(),
            otlp_exporter_cls=_Exporter,
            tracer_provider_cls=_Provider,
            resource_cls=_Resource,
            batch_span_processor_cls=_Batch,
        )
        is False
    )


def test_init_telemetry_dependency_auto_import_failure(monkeypatch):
    import builtins

    class _Log:
        def __init__(self):
            self.warned = []

        def warning(self, msg, *args):
            self.warned.append(msg % args if args else msg)

    log = _Log()
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)

    original_import = builtins.__import__

    def _fail_otel_import(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError("opentelemetry unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_otel_import)

    assert (
        config.Config.init_telemetry(
            logger_obj=log,
            trace_module=config._DEPENDENCY_AUTO,
            otlp_exporter_cls=config._DEPENDENCY_AUTO,
            tracer_provider_cls=config._DEPENDENCY_AUTO,
            resource_cls=config._DEPENDENCY_AUTO,
            batch_span_processor_cls=config._DEPENDENCY_AUTO,
        )
        is False
    )
    assert any("OpenTelemetry bağımlılıkları yüklenemedi" in m for m in log.warned)


def test_module_reload_env_branches(monkeypatch):
    monkeypatch.setenv("SIDAR_ENV", "production")
    calls = {"base": False, "spec": False}

    def fake_exists(self):
        p = str(self)
        if p.endswith(".env"):
            calls["base"] = True
            return True
        if p.endswith(".env.production"):
            calls["spec"] = True
            return True
        return False

    monkeypatch.setattr(Path, "exists", fake_exists)
    assert Path("README.md").exists() is False
    importlib.reload(config)
    assert calls["base"] is True
    assert calls["spec"] is True


def test_module_reload_env_missing_optional_and_warning(monkeypatch):
    monkeypatch.setenv("SIDAR_ENV", "prodx")

    def fake_exists(self):
        p = str(self)
        if p.endswith(".env"):
            return True
        if p.endswith(".env.prodx"):
            return False
        return False

    monkeypatch.setattr(Path, "exists", fake_exists)
    assert Path("README.md").exists() is False
    importlib.reload(config)


def test_module_reload_env_optional_alias_and_no_base(monkeypatch):
    monkeypatch.setenv("SIDAR_ENV", "dev")

    def fake_exists_alias(self):
        p = str(self)
        if p.endswith(".env"):
            return True
        if p.endswith(".env.dev"):
            return False
        return False

    monkeypatch.setattr(Path, "exists", fake_exists_alias)
    assert Path("README.md").exists() is False
    importlib.reload(config)

    monkeypatch.setenv("SIDAR_ENV", "")

    def fake_exists_none(self):
        return False

    monkeypatch.setattr(Path, "exists", fake_exists_none)
    importlib.reload(config)

    def fake_exists_base_only(self):
        return str(self).endswith(".env")

    monkeypatch.setattr(Path, "exists", fake_exists_base_only)
    importlib.reload(config)


def test_check_hardware_cuda_and_optional_modules(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: True)
    monkeypatch.setenv("LLM_GPU_MEMORY_FRACTION", "0.6")
    monkeypatch.setenv("RAG_GPU_MEMORY_FRACTION", "0.3")

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 2,
            get_device_name=lambda _idx: "FakeGPU",
            set_per_process_memory_fraction=lambda frac, device=0: None,
        ),
        version=types.SimpleNamespace(cuda="12.1"),
    )
    fake_pynvml = types.SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlSystemGetDriverVersion=lambda: "550.1",
        nvmlShutdown=lambda: None,
    )
    fake_mp = types.SimpleNamespace(cpu_count=lambda: 16)

    modules = __import__("sys").modules
    monkeypatch.setitem(modules, "torch", fake_torch)
    monkeypatch.setitem(modules, "pynvml", fake_pynvml)
    monkeypatch.setitem(modules, "multiprocessing", fake_mp)

    info = config.check_hardware()
    assert info.has_cuda is True
    assert info.gpu_name == "FakeGPU"
    assert info.driver_version == "550.1"
    assert info.cpu_count == 16


def test_check_hardware_non_cuda_and_generic_exception(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: True)

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        version=types.SimpleNamespace(cuda=None),
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", fake_torch)
    info = config.check_hardware()
    assert info.gpu_name == "CUDA Bulunamadı"

    class _BoomTorch:
        class cuda:
            @staticmethod
            def is_available():
                raise RuntimeError("boom")

    monkeypatch.setitem(__import__("sys").modules, "torch", _BoomTorch)
    info2 = config.check_hardware()
    assert info2.gpu_name == "Tespit Edilemedi"


def test_check_hardware_invalid_fraction_and_fraction_set_exception(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("GPU_MEMORY_FRACTION", "2.0")
    monkeypatch.delenv("LLM_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.delenv("RAG_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    def _raise_set(*_args, **_kwargs):
        raise RuntimeError("set frac fail")

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            get_device_name=lambda _idx: "FakeGPU",
            set_per_process_memory_fraction=_raise_set,
        ),
        version=types.SimpleNamespace(cuda="12.1"),
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", fake_torch)
    info = config.check_hardware()
    assert info.has_cuda is True


def test_check_hardware_cpu_count_fallback(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        version=types.SimpleNamespace(cuda=None),
    )
    modules = __import__("sys").modules
    monkeypatch.setitem(modules, "torch", fake_torch)

    class _BoomMP:
        @staticmethod
        def cpu_count():
            raise RuntimeError("no cpu")

    monkeypatch.setitem(modules, "multiprocessing", _BoomMP)
    info = config.check_hardware()
    assert info.cpu_count == 1


def test_check_hardware_nvml_exception_is_ignored(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        version=types.SimpleNamespace(cuda=None),
    )
    modules = __import__("sys").modules
    monkeypatch.setitem(modules, "torch", fake_torch)
    monkeypatch.setitem(
        modules,
        "pynvml",
        types.SimpleNamespace(nvmlInit=lambda: (_ for _ in ()).throw(RuntimeError("nvml fail"))),
    )

    info = config.check_hardware()
    assert info.gpu_name == "CUDA Bulunamadı"


def test_ensure_hardware_info_loaded_short_circuit(monkeypatch):
    monkeypatch.setattr(config.Config, "_hardware_loaded", True)
    before = config.Config.GPU_INFO
    config.Config._ensure_hardware_info_loaded()
    assert config.Config.GPU_INFO == before


def test_initialize_directories_success_debug_path(monkeypatch, tmp_path):
    monkeypatch.setattr(config.Config, "REQUIRED_DIRS", [tmp_path / "ok_dir"])
    assert config.Config.initialize_directories() is True


def test_validate_critical_settings_invalid_fernet_and_ollama_api_suffix(monkeypatch):
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://localhost:11434/api")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "bad")

    class _Fernet:
        def __init__(self, _val):
            raise ValueError("bad key")

    fake_crypto = types.SimpleNamespace(Fernet=_Fernet)
    monkeypatch.setitem(__import__("sys").modules, "cryptography.fernet", fake_crypto)

    class _Resp:
        status_code = 200

    class _ClientOK:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, url):
            assert url.endswith("/tags")
            return _Resp()

    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientOK))
    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_missing_cryptography_dependency(monkeypatch):
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None))
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True))
    monkeypatch.setattr(config.Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(config.Config, "USE_GPU", False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "abc123")

    class _Resp:
        status_code = 200

    class _ClientOK:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, _url):
            return _Resp()

    monkeypatch.setitem(__import__("sys").modules, "httpx", types.SimpleNamespace(Client=_ClientOK))
    monkeypatch.delitem(__import__("sys").modules, "cryptography.fernet", raising=False)
    monkeypatch.delitem(__import__("sys").modules, "cryptography", raising=False)

    import builtins
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "cryptography.fernet":
            raise ImportError("cryptography missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert config.Config.validate_critical_settings() is False


def test_init_telemetry_dependency_auto_success_with_instrumentation(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel")
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", True)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", True)
    monkeypatch.setattr(config.Config, "OTEL_SERVICE_NAME", "svc")

    trace_mod = types.SimpleNamespace(set_tracer_provider=lambda provider: None)
    otlp_mod = types.SimpleNamespace(OTLPSpanExporter=lambda endpoint, insecure: object())
    sdk_trace = types.SimpleNamespace(TracerProvider=lambda resource: types.SimpleNamespace(add_span_processor=lambda p: None))
    sdk_resource = types.SimpleNamespace(Resource=types.SimpleNamespace(create=lambda x: object()))
    sdk_export = types.SimpleNamespace(BatchSpanProcessor=lambda exporter: object())
    fastapi_inst = types.SimpleNamespace(FastAPIInstrumentor=types.SimpleNamespace(instrument_app=lambda app: None))
    httpx_inst = types.SimpleNamespace(HTTPXClientInstrumentor=lambda: types.SimpleNamespace(instrument=lambda: None))

    modules = __import__("sys").modules
    monkeypatch.setitem(modules, "opentelemetry", types.SimpleNamespace(trace=trace_mod))
    monkeypatch.setitem(modules, "opentelemetry.trace", trace_mod)
    monkeypatch.setitem(modules, "opentelemetry.exporter.otlp.proto.grpc.trace_exporter", otlp_mod)
    monkeypatch.setitem(modules, "opentelemetry.sdk.trace", sdk_trace)
    monkeypatch.setitem(modules, "opentelemetry.sdk.resources", sdk_resource)
    monkeypatch.setitem(modules, "opentelemetry.sdk.trace.export", sdk_export)
    monkeypatch.setitem(modules, "opentelemetry.instrumentation.fastapi", fastapi_inst)
    monkeypatch.setitem(modules, "opentelemetry.instrumentation.httpx", httpx_inst)

    assert config.Config.init_telemetry(fastapi_app=object()) is True


def test_init_telemetry_custom_fastapi_and_missing_httpx_instrumentor(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel")
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", True)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", True)

    class _Trace:
        def set_tracer_provider(self, _provider):
            return None

    class _Resource:
        @staticmethod
        def create(_obj):
            return object()

    class _Provider:
        def __init__(self, resource):
            self.resource = resource
        def add_span_processor(self, _processor):
            return None

    class _Exporter:
        def __init__(self, endpoint, insecure):
            pass

    class _Batch:
        def __init__(self, exporter):
            pass

    class _FastAPIInstr:
        @staticmethod
        def instrument_app(_app):
            return None

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "opentelemetry.instrumentation.httpx":
            raise ImportError("missing httpx instr")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert __import__("math").__name__ == "math"
    assert (
        config.Config.init_telemetry(
            fastapi_app=object(),
            trace_module=_Trace(),
            otlp_exporter_cls=_Exporter,
            tracer_provider_cls=_Provider,
            resource_cls=_Resource,
            batch_span_processor_cls=_Batch,
            fastapi_instrumentor_cls=_FastAPIInstr,
        )
        is True
    )


def test_print_config_summary_with_driver_version(monkeypatch, capsys):
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar")
    monkeypatch.setattr(config.Config, "VERSION", "x")
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(config.Config, "USE_GPU", True)
    monkeypatch.setattr(config.Config, "GPU_INFO", "GPU")
    monkeypatch.setattr(config.Config, "CUDA_VERSION", "12")
    monkeypatch.setattr(config.Config, "GPU_COUNT", 2)
    monkeypatch.setattr(config.Config, "GPU_DEVICE", 0)
    monkeypatch.setattr(config.Config, "GPU_MIXED_PRECISION", True)
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", 0.7)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 0.3)
    monkeypatch.setattr(config.Config, "DRIVER_VERSION", "550.10")
    monkeypatch.setattr(config.Config, "CPU_COUNT", 8)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full")
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False)
    monkeypatch.setattr(config.Config, "GEMINI_MODEL", "gem")
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag")
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "")
    config.Config.print_config_summary()
    assert "Sürücü Sürümü" in capsys.readouterr().out


def test_init_telemetry_with_explicit_httpx_instrumentor(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True)
    monkeypatch.setattr(config.Config, "OTEL_EXPORTER_ENDPOINT", "http://otel")
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", True)

    class _Trace:
        def set_tracer_provider(self, _provider):
            return None

    class _Resource:
        @staticmethod
        def create(_obj):
            return object()

    class _Provider:
        def __init__(self, resource):
            self.resource = resource
        def add_span_processor(self, _processor):
            return None

    class _Exporter:
        def __init__(self, endpoint, insecure):
            pass

    class _Batch:
        def __init__(self, exporter):
            pass

    class _HttpxInstr:
        def instrument(self):
            return None

    assert (
        config.Config.init_telemetry(
            trace_module=_Trace(),
            otlp_exporter_cls=_Exporter,
            tracer_provider_cls=_Provider,
            resource_cls=_Resource,
            batch_span_processor_cls=_Batch,
            httpx_instrumentor_cls=_HttpxInstr,
        )
        is True
    )


# Coverage gap tests for config.py branches
def test_repair_log_file_permissions_coverage(monkeypatch, tmp_path):
    log_file = tmp_path / "test_repair.log"
    log_file.touch()

    monkeypatch.setattr(os, "access", lambda path, mode: False)

    called_chown = []

    def fake_chown(path, uid, gid):
        called_chown.append((path, uid, gid))

    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(os, "getgid", lambda: 1000, raising=False)
    monkeypatch.setattr(os, "chown", fake_chown, raising=False)

    called_chmod = []

    def fake_chmod(self, mode):
        called_chmod.append(mode)

    monkeypatch.setattr(Path, "chmod", fake_chmod)

    config._repair_log_file_permissions(log_file)

    if hasattr(os, "chown"):
        assert len(called_chown) == 1
    assert len(called_chmod) == 1


def test_repair_log_file_permissions_returns_when_already_writable(monkeypatch, tmp_path):
    log_file = tmp_path / "already_writable.log"
    log_file.touch()

    monkeypatch.setattr(os, "access", lambda path, mode: True)

    called_chmod = []

    def fake_chmod(self, mode):
        called_chmod.append(mode)

    monkeypatch.setattr(Path, "chmod", fake_chmod)

    config._repair_log_file_permissions(log_file)

    assert called_chmod == []


def test_repair_log_file_permissions_skips_chown_when_ids_missing(monkeypatch, tmp_path):
    log_file = tmp_path / "missing_ids.log"
    log_file.touch()

    monkeypatch.setattr(os, "access", lambda path, mode: False)
    monkeypatch.setattr(os, "getuid", lambda: None, raising=False)
    monkeypatch.setattr(os, "getgid", lambda: None, raising=False)

    called_chmod = []
    monkeypatch.setattr(Path, "chmod", lambda self, mode: called_chmod.append(mode))

    config._repair_log_file_permissions(log_file)
    assert len(called_chmod) == 1


def test_rotating_file_handler_permission_error_coverage(monkeypatch):
    class MockRotatingFileHandler:
        def __init__(self, *args, **kwargs):
            raise PermissionError("Coverage için Mock PermissionError")

        def setFormatter(self, *args, **kwargs):
            pass

    monkeypatch.setattr("logging.handlers.RotatingFileHandler", MockRotatingFileHandler)
    importlib.reload(config)
    assert config.logger.name == "Sidar.Config"


def test_pynvml_happy_and_exception_paths(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            get_device_name=lambda _idx: "TestGPU",
            set_per_process_memory_fraction=lambda f, d=0: None,
        ),
        version=types.SimpleNamespace(cuda="12.0"),
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", fake_torch)

    fake_pynvml_success = types.SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlSystemGetDriverVersion=lambda: "999.99",
        nvmlShutdown=lambda: None,
    )
    monkeypatch.setitem(__import__("sys").modules, "pynvml", fake_pynvml_success)
    info_success = config.check_hardware()
    assert info_success.driver_version == "999.99"

    def nvml_init_fail():
        raise RuntimeError("NVML Başlatılamadı")

    fake_pynvml_fail = types.SimpleNamespace(nvmlInit=nvml_init_fail)
    monkeypatch.setitem(__import__("sys").modules, "pynvml", fake_pynvml_fail)
    info_fail = config.check_hardware()
    assert info_fail.driver_version == "N/A"


def test_multiprocessing_happy_path(monkeypatch):
    monkeypatch.setenv("USE_GPU", "false")

    fake_mp = types.SimpleNamespace(cpu_count=lambda: 32)
    monkeypatch.setitem(__import__("sys").modules, "multiprocessing", fake_mp)

    info = config.check_hardware()
    assert info.cpu_count == 32


def test_main_block_coverage():
    import runpy

    os.environ["DEBUG_MODE"] = "1"
    config_path = os.path.join(os.path.dirname(__file__), "../../../config.py")

    try:
        if os.path.exists(config_path):
            runpy.run_path(config_path, run_name="__main__")
        else:
            runpy.run_module("config", run_name="__main__")
    except Exception:
        pass
    finally:
        os.environ.pop("DEBUG_MODE", None)


def test_check_hardware_multi_gpu_and_zero_gpu_device_paths(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("MULTI_GPU", "true")
    monkeypatch.delenv("LLM_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.delenv("RAG_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    called = []

    fake_torch_multi = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 2,
            get_device_name=lambda _idx: "MultiGPU",
            set_per_process_memory_fraction=lambda frac, device=0: called.append((frac, device)),
        ),
        version=types.SimpleNamespace(cuda="12.1"),
    )
    modules = __import__("sys").modules
    monkeypatch.setitem(modules, "torch", fake_torch_multi)
    monkeypatch.setitem(
        modules,
        "pynvml",
        types.SimpleNamespace(
            nvmlInit=lambda: None,
            nvmlSystemGetDriverVersion=lambda: "550.1",
            nvmlShutdown=lambda: None,
        ),
    )
    info = config.check_hardware()
    assert info.gpu_count == 2
    assert called == [(0.8, 0), (0.8, 1)]

    monkeypatch.setenv("MULTI_GPU", "false")
    called.clear()
    fake_torch_zero = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 0,
            get_device_name=lambda _idx: "NoDevice",
            set_per_process_memory_fraction=lambda frac, device=0: called.append((frac, device)),
        ),
        version=types.SimpleNamespace(cuda="12.1"),
    )
    monkeypatch.setitem(modules, "torch", fake_torch_zero)
    info_zero = config.check_hardware()
    assert info_zero.gpu_count == 0
    assert called == [(0.8, 0)]


def test_trusted_proxies_as_list_returns_copy(monkeypatch):
    monkeypatch.setattr(config.Config, "TRUSTED_PROXIES_LIST", ["10.0.0.1", "10.0.0.2"])
    result = config.Config.trusted_proxies_as_list()
    assert result == ["10.0.0.1", "10.0.0.2"]
    assert result is not config.Config.TRUSTED_PROXIES_LIST
