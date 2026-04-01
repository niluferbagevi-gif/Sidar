import importlib
import logging
import os
import sys
import types
import pathlib
from pathlib import Path

import pytest

import config


@pytest.fixture(autouse=True)
def reset_singleton_and_hardware(monkeypatch):
    """Her testten önce Config singleton'ını ve donanım yükleme bayrağını sıfırlar."""
    monkeypatch.setattr(config, "_config_instance", None, raising=False)
    monkeypatch.setattr(config.Config, "_hardware_loaded", False, raising=False)


# ═══════════════════════════════════════════════════════════════
# ÇEVRE DEĞİŞKENLERİ (ENV) TESTLERİ
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# DONANIM (HARDWARE) TESTLERİ
# ═══════════════════════════════════════════════════════════════

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


def test_check_hardware_with_cuda_fraction_and_pynvml(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("GPU_MEMORY_FRACTION", "0.6")
    monkeypatch.delenv("LLM_GPU_MEMORY_FRACTION", raising=False)
    monkeypatch.delenv("RAG_GPU_MEMORY_FRACTION", raising=False)

    calls = {}

    class FakeCuda:
        @staticmethod
        def is_available(): return True
        @staticmethod
        def device_count(): return 2
        @staticmethod
        def get_device_name(_idx): return "FakeGPU"
        @staticmethod
        def set_per_process_memory_fraction(frac, device=0):
            calls["frac"] = frac
            calls["device"] = device

    fake_torch = types.SimpleNamespace(cuda=FakeCuda, version=types.SimpleNamespace(cuda="12.4"))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    # pynvml mock ekleyerek driver version satırlarını da %100 test edelim
    class FakePynvml:
        @staticmethod
        def nvmlInit(): pass
        @staticmethod
        def nvmlSystemGetDriverVersion(): return "550.54"
        @staticmethod
        def nvmlShutdown(): pass

    monkeypatch.setitem(sys.modules, "pynvml", FakePynvml)

    hw = config.check_hardware()

    assert hw.has_cuda is True
    assert hw.gpu_name == "FakeGPU"
    assert hw.gpu_count == 2
    assert hw.cuda_version == "12.4"
    assert hw.driver_version == "550.54"
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


def test_ensure_hardware_info_loaded_gpu_disabled(monkeypatch):
    monkeypatch.setattr(config.Config, "USE_GPU", False, raising=False)
    monkeypatch.setattr(config.Config, "_hardware_loaded", False, raising=False)
    config.Config._ensure_hardware_info_loaded()

    assert config.Config._hardware_loaded is True
    assert config.Config.GPU_INFO == "Devre Dışı / CPU Modu"
    assert config.Config.GPU_COUNT == 0


def test_ensure_hardware_info_loaded_gpu_enabled(monkeypatch):
    fake = config.HardwareInfo(
        has_cuda=True, gpu_name="GPU-X", gpu_count=3,
        cpu_count=8, cuda_version="12.1", driver_version="550",
    )
    monkeypatch.setattr(config, "check_hardware", lambda: fake)
    monkeypatch.setattr(config.Config, "USE_GPU", True, raising=False)
    monkeypatch.setattr(config.Config, "_hardware_loaded", False, raising=False)
    config.Config._ensure_hardware_info_loaded()

    assert config.Config.USE_GPU is True
    assert config.Config.GPU_INFO == "GPU-X"
    assert config.Config.GPU_COUNT == 3
    assert config.Config.CPU_COUNT == 8


# ═══════════════════════════════════════════════════════════════
# CONFIG UYGULAMA TESTLERİ
# ═══════════════════════════════════════════════════════════════

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

    config.Config.set_provider_mode("anthropic")
    assert config.Config.AI_PROVIDER == "anthropic"

    config.Config.set_provider_mode("invalid-provider")
    # Mevcut mod korunmalı
    assert config.Config.AI_PROVIDER == "anthropic"


@pytest.mark.parametrize("provider, key_attr", [
    ("gemini", "GEMINI_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("litellm", "LITELLM_GATEWAY_URL"),
])
def test_validate_critical_settings_missing_provider_keys(monkeypatch, provider, key_attr):
    # Tüm AI sağlayıcılarında API Key / URL eksikse False dönmesini test et
    monkeypatch.setattr(config.Config, "AI_PROVIDER", provider, raising=False)
    monkeypatch.setattr(config.Config, key_attr, "", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "valid_key_simulated", raising=False)
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None), raising=False)
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True), raising=False)

    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_invalid_fernet(monkeypatch):
    # Geçersiz Fernet key verildiğinde yakalanan Exception kontrolü
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "gecersiz_bir_anahtar", raising=False)
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None), raising=False)
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True), raising=False)

    assert config.Config.validate_critical_settings() is False


def test_validate_critical_settings_missing_cryptography_lib(monkeypatch):
    # Geçerli Fernet var ancak cryptography kütüphanesi yoksa (ImportError simülasyonu)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "8kXg-_1l9w-sY7Y4Y1J_mH7W2Z3eU4v5Q6r7t8y9u0I=", raising=False)
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None), raising=False)
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True), raising=False)

    real_import = __import__
    def fake_import(name, *args, **kwargs):
        if name == "cryptography.fernet":
            raise ImportError("no cryptography")
        return real_import(name, *args, **kwargs)
    
    monkeypatch.setattr("builtins.__import__", fake_import)
    
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
        def __init__(self, timeout): self.timeout = timeout
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def get(self, url):
            assert url.endswith("/tags")
            return FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(Client=FakeClient))

    assert config.Config.validate_critical_settings() is True


def test_validate_critical_settings_ollama_unreachable(monkeypatch):
    # Ollama kapalıyken Exception fırlatması durumu veya 404 dönmesi
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None), raising=False)
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True), raising=False)

    class FakeClientRaise:
        def __init__(self, timeout): pass
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def get(self, url): raise ConnectionError("Ollama kapali")

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(Client=FakeClientRaise))
    # Exception tetiklenecek, ancak validate_critical_settings 'is_valid' True dönebilir 
    # çünkü Ollama erişilememesi sadece bir warning'dir (kodunuzdaki mantığa göre)
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
        def create(data): return data

    class FakeProvider:
        def __init__(self, resource): self.resource = resource; self.added = []
        def add_span_processor(self, processor): self.added.append(processor)

    class FakeExporter:
        def __init__(self, endpoint, insecure): self.endpoint = endpoint; self.insecure = insecure

    class FakeBatch:
        def __init__(self, exporter): self.exporter = exporter

    class FakeTrace:
        def __init__(self): self.provider = None
        def set_tracer_provider(self, provider): self.provider = provider

    class FakeFastAPIInstrumentor:
        called = False
        @classmethod
        def instrument_app(cls, app): cls.called = True

    class FakeHTTPXInstrumentor:
        called = False
        def instrument(self): self.__class__.called = True

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
        def __init__(self): self.warned = False
        def warning(self, *_args, **_kwargs): self.warned = True

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
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "litellm", raising=False) # Farklı bir branch test
    monkeypatch.setattr(config.Config, "USE_GPU", True, raising=False) # GPU var dalını test
    monkeypatch.setattr(config.Config, "GPU_INFO", "RTX", raising=False)
    monkeypatch.setattr(config.Config, "CPU_COUNT", 4, raising=False)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full", raising=False)
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False, raising=False)
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "fernet-key", raising=False)

    config.Config.print_config_summary()
    out = capsys.readouterr().out
    assert "Yapılandırma Özeti" in out
    assert "LiteLLM Gateway" in out
    assert "GPU              : ✓ RTX" in out
    assert "Etkin (Fernet)" in out


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


def test_reload_config_env_file_branches(monkeypatch, capsys):
    load_calls = []

    def fake_load_dotenv(*_args, **kwargs):
        load_calls.append(kwargs)
        return True

    def fake_exists(self):
        name = self.name
        if name == ".env":
            return True
        if name == ".env.production":
            return True
        return False

    monkeypatch.setenv("SIDAR_ENV", "production")
    monkeypatch.setattr(pathlib.Path, "exists", fake_exists, raising=False)
    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=fake_load_dotenv))

    mod = importlib.reload(config)
    out = capsys.readouterr().out
    assert "Ortama özgü yapılandırma yüklendi" in out
    assert any(str(call.get("dotenv_path", "")).endswith(".env") for call in load_calls)
    assert any(call.get("override") is True for call in load_calls)
    assert mod.ENV_PATH.exists()


def test_reload_config_missing_env_file_warning(monkeypatch, capsys):
    def fake_exists(_self):
        return False

    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.setattr(pathlib.Path, "exists", fake_exists, raising=False)
    importlib.reload(config)
    out = capsys.readouterr().out
    assert ".env' dosyası bulunamadı" in out


def test_reload_config_missing_specific_env_file_warning(monkeypatch, capsys):
    def fake_exists(self):
        # Temel .env var, ancak ortama özel dosya yok -> satır 56 uyarısı
        return self.name == ".env"

    monkeypatch.setenv("SIDAR_ENV", "production")
    monkeypatch.setattr(pathlib.Path, "exists", fake_exists, raising=False)
    importlib.reload(config)
    out = capsys.readouterr().out
    assert "Belirtilen ortam dosyası bulunamadı: .env.production" in out


def test_check_hardware_wsl2_cuda_not_found(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: True)

    class FakeCuda:
        @staticmethod
        def is_available():
            return False

    fake_torch = types.SimpleNamespace(cuda=FakeCuda, version=types.SimpleNamespace(cuda="N/A"))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.delitem(sys.modules, "pynvml", raising=False)

    hw = config.check_hardware()
    assert hw.gpu_name == "CUDA Bulunamadı"


def test_check_hardware_non_wsl2_cuda_not_found(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    class FakeCuda:
        @staticmethod
        def is_available():
            return False

    fake_torch = types.SimpleNamespace(cuda=FakeCuda, version=types.SimpleNamespace(cuda="N/A"))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    hw = config.check_hardware()
    assert hw.has_cuda is False
    assert hw.gpu_name == "CUDA Bulunamadı"


def test_check_hardware_invalid_fraction_and_set_fraction_exception(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("LLM_GPU_MEMORY_FRACTION", "0.9")
    monkeypatch.setenv("RAG_GPU_MEMORY_FRACTION", "0.5")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def get_device_name(_idx):
            return "GPU-Z"

        @staticmethod
        def set_per_process_memory_fraction(_frac, device=0):
            raise RuntimeError(f"cannot set on {device}")

    fake_torch = types.SimpleNamespace(cuda=FakeCuda, version=types.SimpleNamespace(cuda="12.2"))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    hw = config.check_hardware()
    assert hw.has_cuda is True
    assert hw.gpu_name == "GPU-Z"


def test_check_hardware_generic_exception_and_cpu_fallback(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    real_import = __import__

    class FakeMP:
        @staticmethod
        def cpu_count():
            raise RuntimeError("no cpu")

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            raise RuntimeError("torch boom")
        if name == "multiprocessing":
            return FakeMP
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    hw = config.check_hardware()
    assert hw.gpu_name == "Tespit Edilemedi"
    assert hw.cpu_count == 1


def test_check_hardware_pynvml_init_exception(monkeypatch):
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(config, "_is_wsl2", lambda: False)

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def get_device_name(_idx):
            return "GPU-Y"

        @staticmethod
        def set_per_process_memory_fraction(_frac, device=0):
            return None

    class BadPynvml:
        @staticmethod
        def nvmlInit():
            raise RuntimeError("nvml unavailable")

    fake_torch = types.SimpleNamespace(cuda=FakeCuda, version=types.SimpleNamespace(cuda="12.4"))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "pynvml", BadPynvml)

    hw = config.check_hardware()
    assert hw.gpu_name == "GPU-Y"
    assert hw.driver_version == "N/A"


def test_ensure_hardware_info_loaded_when_already_loaded(monkeypatch):
    monkeypatch.setattr(config.Config, "_hardware_loaded", True, raising=False)
    called = {"check": False}

    def fake_check():
        called["check"] = True
        return config.HardwareInfo(False, "N/A")

    monkeypatch.setattr(config, "check_hardware", fake_check)
    config.Config._ensure_hardware_info_loaded()
    assert called["check"] is False


def test_initialize_directories_failure_path(monkeypatch):
    class BadFolder:
        name = "bad"

        def mkdir(self, *args, **kwargs):
            raise OSError("no permission")

    monkeypatch.setattr(config.Config, "REQUIRED_DIRS", [BadFolder()], raising=False)
    assert config.Config.initialize_directories() is False


def test_validate_critical_settings_ollama_non_api_url_and_non_200(monkeypatch):
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(config.Config, "OLLAMA_URL", "http://localhost:11434", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setattr(config.Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None), raising=False)
    monkeypatch.setattr(config.Config, "initialize_directories", classmethod(lambda cls: True), raising=False)

    called = {"url": None}

    class FakeResponse:
        status_code = 404

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            called["url"] = url
            return FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(Client=FakeClient))
    assert config.Config.validate_critical_settings() is True
    assert called["url"].endswith("/api/tags")


def test_init_telemetry_import_default_classes_and_runtime_failure(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", True, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", True, raising=False)

    fake_trace_exporter_mod = types.SimpleNamespace(OTLPSpanExporter=lambda **_kwargs: object())
    fake_sdk_trace_mod = types.SimpleNamespace(TracerProvider=lambda resource: (_ for _ in ()).throw(RuntimeError("provider fail")))
    fake_resource_mod = types.SimpleNamespace(Resource=types.SimpleNamespace(create=lambda data: data))
    fake_span_export_mod = types.SimpleNamespace(BatchSpanProcessor=lambda _exporter: object())
    fake_fastapi_mod = types.SimpleNamespace(FastAPIInstrumentor=types.SimpleNamespace(instrument_app=lambda _app: None))

    monkeypatch.setitem(sys.modules, "opentelemetry.exporter.otlp.proto.grpc.trace_exporter", fake_trace_exporter_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", fake_sdk_trace_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", fake_resource_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", fake_span_export_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.instrumentation.fastapi", fake_fastapi_mod)
    monkeypatch.delitem(sys.modules, "opentelemetry.instrumentation.httpx", raising=False)

    fake_trace_module = types.SimpleNamespace(set_tracer_provider=lambda _provider: None)
    assert config.Config.init_telemetry(trace_module=fake_trace_module, fastapi_app=object()) is False


def test_init_telemetry_imports_fastapi_and_httpx_default_classes(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", True, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", True, raising=False)

    class FakeProvider:
        def __init__(self, resource):
            self.resource = resource

        def add_span_processor(self, _processor):
            return None

    class FakeTrace:
        def __init__(self):
            self.provider = None

        def set_tracer_provider(self, provider):
            self.provider = provider

    class FakeFastAPIInstrumentor:
        called = False

        @classmethod
        def instrument_app(cls, _app):
            cls.called = True

    class FakeHTTPXClientInstrumentor:
        called = False

        def instrument(self):
            self.__class__.called = True

    monkeypatch.setitem(
        sys.modules,
        "opentelemetry.instrumentation.fastapi",
        types.SimpleNamespace(FastAPIInstrumentor=FakeFastAPIInstrumentor),
    )
    monkeypatch.setitem(
        sys.modules,
        "opentelemetry.instrumentation.httpx",
        types.SimpleNamespace(HTTPXClientInstrumentor=FakeHTTPXClientInstrumentor),
    )

    trace = FakeTrace()
    ok = config.Config.init_telemetry(
        fastapi_app=object(),
        trace_module=trace,
        otlp_exporter_cls=lambda **_kwargs: object(),
        tracer_provider_cls=FakeProvider,
        resource_cls=types.SimpleNamespace(create=lambda data: data),
        batch_span_processor_cls=lambda _exporter: object(),
    )
    assert ok is True
    assert trace.provider is not None
    assert FakeFastAPIInstrumentor.called is True
    assert FakeHTTPXClientInstrumentor.called is True


def test_init_telemetry_fastapi_disabled_and_httpx_disabled(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", False, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", False, raising=False)

    class FakeProvider:
        def __init__(self, resource):
            self.resource = resource

        def add_span_processor(self, _processor):
            return None

    class FakeTrace:
        def __init__(self):
            self.provider = None

        def set_tracer_provider(self, provider):
            self.provider = provider

    ok = config.Config.init_telemetry(
        fastapi_app=object(),  # app veriyoruz ama FastAPI enstrümantasyonu kapalı
        trace_module=FakeTrace(),
        otlp_exporter_cls=lambda **_kwargs: object(),
        tracer_provider_cls=FakeProvider,
        resource_cls=types.SimpleNamespace(create=lambda data: data),
        batch_span_processor_cls=lambda _exporter: object(),
    )
    assert ok is True


def test_init_telemetry_httpx_import_failure_is_suppressed(monkeypatch):
    monkeypatch.setattr(config.Config, "ENABLE_TRACING", True, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_FASTAPI", False, raising=False)
    monkeypatch.setattr(config.Config, "OTEL_INSTRUMENT_HTTPX", True, raising=False)

    class FakeProvider:
        def __init__(self, resource):
            self.resource = resource

        def add_span_processor(self, _processor):
            return None

    class FakeTrace:
        def set_tracer_provider(self, _provider):
            return None

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "opentelemetry.instrumentation.httpx":
            raise ImportError("missing httpx instrumentor")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    ok = config.Config.init_telemetry(
        fastapi_app=None,
        trace_module=FakeTrace(),
        otlp_exporter_cls=lambda **_kwargs: object(),
        tracer_provider_cls=FakeProvider,
        resource_cls=types.SimpleNamespace(create=lambda data: data),
        batch_span_processor_cls=lambda _exporter: object(),
        fastapi_instrumentor_cls=None,
        httpx_instrumentor_cls=None,
    )
    assert ok is True


def test_print_config_summary_anthropic_branch(monkeypatch, capsys):
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar", raising=False)
    monkeypatch.setattr(config.Config, "VERSION", "5.2.0", raising=False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "anthropic", raising=False)
    monkeypatch.setattr(config.Config, "USE_GPU", True, raising=False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "RTX", raising=False)
    monkeypatch.setattr(config.Config, "GPU_COUNT", 1, raising=False)
    monkeypatch.setattr(config.Config, "GPU_DEVICE", 0, raising=False)
    monkeypatch.setattr(config.Config, "GPU_MIXED_PRECISION", False, raising=False)
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", 0.5, raising=False)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 0.2, raising=False)
    monkeypatch.setattr(config.Config, "DRIVER_VERSION", "551.23", raising=False)
    monkeypatch.setattr(config.Config, "CUDA_VERSION", "12.4", raising=False)
    monkeypatch.setattr(config.Config, "CPU_COUNT", 8, raising=False)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full", raising=False)
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False, raising=False)
    monkeypatch.setattr(config.Config, "ANTHROPIC_MODEL", "claude-x", raising=False)
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    config.Config.print_config_summary()
    out = capsys.readouterr().out
    assert "Sürücü Sürümü" in out
    assert "Anthropic Modeli : claude-x" in out


def test_print_config_summary_openai_branch(monkeypatch, capsys):
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar", raising=False)
    monkeypatch.setattr(config.Config, "VERSION", "5.2.0", raising=False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "openai", raising=False)
    monkeypatch.setattr(config.Config, "OPENAI_MODEL", "gpt-4.1", raising=False)
    monkeypatch.setattr(config.Config, "USE_GPU", False, raising=False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "CPU only", raising=False)
    monkeypatch.setattr(config.Config, "CPU_COUNT", 8, raising=False)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full", raising=False)
    monkeypatch.setattr(config.Config, "DEBUG_MODE", True, raising=False)
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    config.Config.print_config_summary()
    out = capsys.readouterr().out
    assert "GPU              : ✗ CPU Modu  (CPU only)" in out
    assert "OpenAI Modeli    : gpt-4.1" in out


def test_print_config_summary_ollama_without_driver(monkeypatch, capsys):
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar", raising=False)
    monkeypatch.setattr(config.Config, "VERSION", "5.2.0", raising=False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "ollama", raising=False)
    monkeypatch.setattr(config.Config, "USE_GPU", True, raising=False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "RTX", raising=False)
    monkeypatch.setattr(config.Config, "GPU_COUNT", 1, raising=False)
    monkeypatch.setattr(config.Config, "GPU_DEVICE", 0, raising=False)
    monkeypatch.setattr(config.Config, "GPU_MIXED_PRECISION", True, raising=False)
    monkeypatch.setattr(config.Config, "LLM_GPU_MEMORY_FRACTION", 0.4, raising=False)
    monkeypatch.setattr(config.Config, "RAG_GPU_MEMORY_FRACTION", 0.3, raising=False)
    monkeypatch.setattr(config.Config, "DRIVER_VERSION", "N/A", raising=False)  # 861->865
    monkeypatch.setattr(config.Config, "CUDA_VERSION", "12.4", raising=False)
    monkeypatch.setattr(config.Config, "CPU_COUNT", 8, raising=False)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full", raising=False)
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False, raising=False)
    monkeypatch.setattr(config.Config, "CODING_MODEL", "qwen2.5-coder:7b", raising=False)
    monkeypatch.setattr(config.Config, "TEXT_MODEL", "qwen2.5:7b", raising=False)  # 869-870
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    config.Config.print_config_summary()
    out = capsys.readouterr().out
    assert "Sürücü Sürümü" not in out
    assert "CODING Modeli    : qwen2.5-coder:7b" in out
    assert "TEXT Modeli      : qwen2.5:7b" in out


def test_print_config_summary_gemini_branch(monkeypatch, capsys):
    monkeypatch.setattr(config.Config, "PROJECT_NAME", "Sidar", raising=False)
    monkeypatch.setattr(config.Config, "VERSION", "5.2.0", raising=False)
    monkeypatch.setattr(config.Config, "AI_PROVIDER", "gemini", raising=False)
    monkeypatch.setattr(config.Config, "GEMINI_MODEL", "gemini-2.5-pro", raising=False)  # 872
    monkeypatch.setattr(config.Config, "USE_GPU", False, raising=False)
    monkeypatch.setattr(config.Config, "GPU_INFO", "CPU only", raising=False)
    monkeypatch.setattr(config.Config, "CPU_COUNT", 8, raising=False)
    monkeypatch.setattr(config.Config, "ACCESS_LEVEL", "full", raising=False)
    monkeypatch.setattr(config.Config, "DEBUG_MODE", False, raising=False)
    monkeypatch.setattr(config.Config, "RAG_DIR", config.BASE_DIR / "data" / "rag", raising=False)
    monkeypatch.setattr(config.Config, "MEMORY_ENCRYPTION_KEY", "", raising=False)

    config.Config.print_config_summary()
    out = capsys.readouterr().out
    assert "Gemini Modeli    : gemini-2.5-pro" in out
