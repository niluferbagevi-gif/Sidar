import builtins
import importlib.util
import runpy
import sys
import types
from pathlib import Path


def _load_config_module():
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: None

    saved = sys.modules.get("dotenv")
    try:
        sys.modules["dotenv"] = dotenv_mod
        spec = importlib.util.spec_from_file_location("config_runtime_under_test", Path("config.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        if saved is None:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = saved


def test_get_env_helpers_coverage(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.delenv("TEST_KEY", raising=False)

    monkeypatch.setenv("TEST_KEY", "not_an_int")
    assert cfg_mod.get_int_env("TEST_KEY", 5) == 5

    monkeypatch.setenv("TEST_KEY", "not_a_float")
    assert cfg_mod.get_float_env("TEST_KEY", 2.5) == 2.5

    monkeypatch.setenv("TEST_KEY", "yes")
    assert cfg_mod.get_bool_env("TEST_KEY") is True
    monkeypatch.setenv("TEST_KEY", "1")
    assert cfg_mod.get_bool_env("TEST_KEY") is True

    monkeypatch.delenv("TEST_KEY", raising=False)
    assert cfg_mod.get_list_env("TEST_KEY", None) == []


def test_hardware_detection_wsl_and_cpu_fallback(monkeypatch):
    cfg_mod = _load_config_module()

    monkeypatch.setattr(cfg_mod.Path, "read_text", lambda _self: "microsoft standard")
    assert cfg_mod._is_wsl2() is True

    monkeypatch.setenv("USE_GPU", "false")
    hw = cfg_mod.check_hardware()
    assert hw.gpu_name == "Devre Dışı (Kullanıcı)"

    monkeypatch.setenv("USE_GPU", "true")
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "torch":
            raise ImportError("Mocked PyTorch Yok")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    hw2 = cfg_mod.check_hardware()
    assert "Yok" in hw2.gpu_name


def test_hardware_detection_torch_available_no_cuda(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.setenv("USE_GPU", "true")

    class FakeTorch:
        class cuda:
            @staticmethod
            def is_available():
                return False

    monkeypatch.setitem(sys.modules, "torch", FakeTorch())
    hw = cfg_mod.check_hardware()
    assert "CUDA Bulunamadı" in hw.gpu_name


def test_hardware_detection_torch_cuda_available(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("GPU_MEMORY_FRACTION", "9.9")

    calls = {"frac": None}

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def get_device_name(_dev):
            return "Mocked RTX"

        @staticmethod
        def set_per_process_memory_fraction(frac, device):
            calls["frac"] = (frac, device)

    class FakeTorch:
        cuda = FakeCuda()

        class version:
            cuda = "12.x"

    class FakeMultiprocessing:
        @staticmethod
        def cpu_count():
            return 4

    monkeypatch.setitem(sys.modules, "torch", FakeTorch())
    monkeypatch.setitem(sys.modules, "multiprocessing", FakeMultiprocessing())

    hw = cfg_mod.check_hardware()
    assert hw.has_cuda is True
    assert hw.gpu_name == "Mocked RTX"
    assert hw.cpu_count == 4
    assert calls["frac"] == (0.8, 0)


def test_hardware_detection_uses_split_llm_rag_gpu_fraction(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("LLM_GPU_MEMORY_FRACTION", "0.55")
    monkeypatch.setenv("RAG_GPU_MEMORY_FRACTION", "0.20")

    calls = {"frac": None}

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def get_device_name(_dev):
            return "Mocked RTX"

        @staticmethod
        def set_per_process_memory_fraction(frac, device):
            calls["frac"] = (frac, device)

    class FakeTorch:
        cuda = FakeCuda()

        class version:
            cuda = "12.x"

    monkeypatch.setitem(sys.modules, "torch", FakeTorch())
    _ = cfg_mod.check_hardware()
    assert calls["frac"] == (0.75, 0)


def test_config_summary_print(capsys):
    cfg_mod = _load_config_module()
    c = cfg_mod.Config()
    c.print_config_summary()
    out, _ = capsys.readouterr()
    assert "Yapılandırma Özeti" in out


def test_config_env_overrides_for_existing_fields(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tv-key")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "150")
    monkeypatch.setenv("REDIS_URL", "redis://test:6379")
    monkeypatch.setenv("WEB_SEARCH_MAX_RESULTS", "15")
    monkeypatch.setenv("WEB_FETCH_TIMEOUT", "21")
    monkeypatch.setenv("RATE_LIMIT_CHAT", "99")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    cfg_mod = _load_config_module()
    c = cfg_mod.Config()

    assert c.GEMINI_API_KEY == "g-key"
    assert c.TAVILY_API_KEY == "tv-key"
    assert c.OLLAMA_TIMEOUT == 150
    assert c.REDIS_URL == "redis://test:6379"
    assert c.WEB_SEARCH_MAX_RESULTS == 15
    assert c.WEB_FETCH_TIMEOUT == 21
    assert c.RATE_LIMIT_CHAT == 99
    assert c.HF_HUB_OFFLINE is True


def test_config_import_profile_and_missing_env_messages(monkeypatch):
    load_calls = []
    printed = []

    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: load_calls.append((a, k))

    saved = sys.modules.get("dotenv")
    try:
        sys.modules["dotenv"] = dotenv_mod
        monkeypatch.setattr(Path, "exists", lambda self: False)
        monkeypatch.setattr(builtins, "print", lambda *a, **k: printed.append(" ".join(map(str, a))))

        monkeypatch.setenv("SIDAR_ENV", "missing_profile")
        spec = importlib.util.spec_from_file_location("config_runtime_profile_under_test", Path("config.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        assert any("bulunamadı" in p for p in printed)

        printed.clear()
        monkeypatch.delenv("SIDAR_ENV", raising=False)
        spec2 = importlib.util.spec_from_file_location("config_runtime_missing_base_under_test", Path("config.py"))
        mod2 = importlib.util.module_from_spec(spec2)
        assert spec2 and spec2.loader
        spec2.loader.exec_module(mod2)
        assert any("'.env' dosyası bulunamadı" in p for p in printed)
    finally:
        if saved is None:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = saved


def test_config_import_profile_success_message_and_override_load(monkeypatch):
    load_calls = []
    printed = []

    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: load_calls.append((a, k))

    saved = sys.modules.get("dotenv")
    try:
        sys.modules["dotenv"] = dotenv_mod
        monkeypatch.setattr(builtins, "print", lambda *a, **k: printed.append(" ".join(map(str, a))))
        monkeypatch.setenv("SIDAR_ENV", "production")

        def fake_exists(self):
            path = str(self)
            return path.endswith(".env") or path.endswith(".env.production")

        monkeypatch.setattr(Path, "exists", fake_exists)

        spec = importlib.util.spec_from_file_location("config_runtime_profile_success_under_test", Path("config.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        assert any("Ortama özgü yapılandırma yüklendi" in p for p in printed)
        assert any(call[1].get("override") is True for call in load_calls)
    finally:
        if saved is None:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = saved


def test_runtime_config_provider_and_validate_branches(monkeypatch):
    cfg_mod = _load_config_module()

    errors = []
    warns = []
    infos = []
    monkeypatch.setattr(cfg_mod.logger, "error", lambda msg, *args: errors.append(msg % args if args else msg))
    monkeypatch.setattr(cfg_mod.logger, "warning", lambda msg, *args: warns.append(msg % args if args else msg))
    monkeypatch.setattr(cfg_mod.logger, "info", lambda msg, *args: infos.append(msg % args if args else msg))

    cfg_mod.Config.set_provider_mode("online")
    assert cfg_mod.Config.AI_PROVIDER == "gemini"
    cfg_mod.Config.set_provider_mode("invalid")
    assert any("Geçersiz sağlayıcı modu" in e for e in errors)

    cfg_mod.Config._hardware_loaded = True
    cfg_mod.Config.initialize_directories = classmethod(lambda cls: True)
    cfg_mod.Config.AI_PROVIDER = "gemini"
    cfg_mod.Config.GEMINI_API_KEY = ""
    cfg_mod.Config.MEMORY_ENCRYPTION_KEY = ""
    valid = cfg_mod.Config.validate_critical_settings()
    assert valid is False

    cfg_mod.Config.AI_PROVIDER = "ollama"
    cfg_mod.Config.OLLAMA_URL = "http://localhost:11434"

    class _Resp:
        status_code = 503

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, _url):
            return _Resp()

    httpx_mod = types.SimpleNamespace(Client=_Client)
    monkeypatch.setitem(sys.modules, "httpx", httpx_mod)
    cfg_mod.Config.GEMINI_API_KEY = "key"
    cfg_mod.Config.MEMORY_ENCRYPTION_KEY = "invalid"
    valid2 = cfg_mod.Config.validate_critical_settings()
    assert valid2 is False
    assert any("Ollama yanıt kodu" in w for w in warns)

    monkeypatch.delitem(sys.modules, "httpx", raising=False)
    cfg_mod.Config.MEMORY_ENCRYPTION_KEY = ""
    cfg_mod.Config.OLLAMA_URL = "http://invalid:11434/api"
    valid3 = cfg_mod.Config.validate_critical_settings()
    assert valid3 is True
    assert any(("ulaşılamadı" in w) or ("Ollama yanıt kodu" in w) for w in warns)


def test_check_hardware_general_exception_and_vram_set_exception(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("GPU_MEMORY_FRACTION", "0.5")

    class _CudaErr:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def get_device_name(_idx):
            return "GPU"

        @staticmethod
        def set_per_process_memory_fraction(_frac, device=0):
            raise RuntimeError("no-vram-set")

    torch_mod = types.SimpleNamespace(cuda=_CudaErr(), version=types.SimpleNamespace(cuda="12"))
    monkeypatch.setitem(sys.modules, "torch", torch_mod)
    hw = cfg_mod.check_hardware()
    assert hw.gpu_name == "GPU"

    real_import = builtins.__import__

    def _fail_torch(name, *args, **kwargs):
        if name == "torch":
            class _Boom(Exception):
                pass
            raise _Boom("torch boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_torch)
    hw2 = cfg_mod.check_hardware()
    assert hw2.gpu_name == "Tespit Edilemedi"


def test_initialize_directories_error_and_system_info_and_summary_and_main(monkeypatch, capsys):
    cfg_mod = _load_config_module()

    class _BadDir:
        name = "bad"

        def mkdir(self, *a, **k):
            raise OSError("nope")

    cfg_mod.Config.REQUIRED_DIRS = [_BadDir()]
    assert cfg_mod.Config.initialize_directories() is False

    called = {"ensure": 0}
    cfg_mod.Config._ensure_hardware_info_loaded = classmethod(lambda cls: called.__setitem__("ensure", called["ensure"] + 1))
    info = cfg_mod.Config.get_system_info()
    assert called["ensure"] == 1
    assert "provider" in info

    cfg_mod.Config.USE_GPU = True
    cfg_mod.Config.GPU_INFO = "RTX"
    cfg_mod.Config.CUDA_VERSION = "12.4"
    cfg_mod.Config.GPU_COUNT = 2
    cfg_mod.Config.GPU_DEVICE = 1
    cfg_mod.Config.GPU_MIXED_PRECISION = True
    cfg_mod.Config.DRIVER_VERSION = "550"
    cfg_mod.Config.AI_PROVIDER = "gemini"
    cfg_mod.Config.GEMINI_MODEL = "g-model"
    cfg_mod.Config.print_config_summary()
    out, _ = capsys.readouterr()
    assert "Sürücü Sürümü" in out
    assert "Gemini Modeli" in out

    cfg_mod.Config.DEBUG_MODE = True
    cfg_mod.Config.initialize_directories = classmethod(lambda cls: True)
    printed = []
    monkeypatch.setenv("DEBUG_MODE", "1")
    monkeypatch.setattr(builtins, "print", lambda *a, **k: printed.append(" ".join(map(str, a))))
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: None
    saved = sys.modules.get("dotenv")
    try:
        sys.modules["dotenv"] = dotenv_mod
        runpy.run_path("config.py", run_name="__main__")
    finally:
        if saved is None:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = saved
    assert printed

def test_config_remaining_edge_cases_runtime(monkeypatch, capsys):
    monkeypatch.setenv("SIDAR_ENV", "invalid_env_name_123")
    cfg_mod = _load_config_module()
    out = capsys.readouterr().out
    assert "Belirtilen ortam dosyası bulunamadı" in out

    monkeypatch.setenv("TEST_WS", "   ")
    assert cfg_mod.get_bool_env("TEST_WS", True) is True

    monkeypatch.setenv("TEST_LIST", "")
    assert cfg_mod.get_list_env("TEST_LIST", ["default"]) == ["default"]

    # cryptography yokmuş gibi davran: ImportError yolu
    real_import = builtins.__import__

    def _import_without_crypto(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("cryptography"):
            raise ImportError("no crypto")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import_without_crypto)
    cfg_mod.Config.AI_PROVIDER = "gemini"
    cfg_mod.Config.GEMINI_API_KEY = "ok"
    cfg_mod.Config.MEMORY_ENCRYPTION_KEY = "x"
    assert cfg_mod.Config.validate_critical_settings() is False

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, _url):
            return _Resp()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(Client=_Client))
    monkeypatch.setattr(builtins, "__import__", real_import)
    cfg_mod.Config.AI_PROVIDER = "ollama"
    cfg_mod.Config.MEMORY_ENCRYPTION_KEY = ""
    cfg_mod.Config.OLLAMA_URL = "http://localhost:11434"
    assert isinstance(cfg_mod.Config.validate_critical_settings(), bool)


def test_config_ultimate_edge_cases(monkeypatch, capsys):
    monkeypatch.setenv("SIDAR_ENV", "nonexistent_env_123")
    cfg_mod = _load_config_module()
    captured = capsys.readouterr()
    assert "Belirtilen ortam dosyası bulunamadı" in captured.out

    monkeypatch.setenv("TEST_EMPTY_LIST", " , , ")
    assert cfg_mod.get_list_env("TEST_EMPTY_LIST", ["default"]) == []

    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("GPU_MEMORY_FRACTION", "0.5")

    class _Cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def get_device_name(_idx):
            return "MockGPU"

        @staticmethod
        def set_per_process_memory_fraction(*_a, **_k):
            raise RuntimeError("CUDA mock exception")

    class _Torch:
        cuda = _Cuda()

        class version:
            cuda = "12"

    monkeypatch.setitem(sys.modules, "torch", _Torch())
    hw = cfg_mod.check_hardware()
    assert hw.gpu_name == "MockGPU"

def test_config_enforces_supervisor_mode(monkeypatch):
    monkeypatch.setenv("ENABLE_MULTI_AGENT", "false")
    cfg_mod = _load_config_module()

    c = cfg_mod.Config()
    assert c.ENABLE_MULTI_AGENT is True


def test_init_telemetry_returns_false_when_opentelemetry_imports_fail(monkeypatch):
    cfg_mod = _load_config_module()
    cfg_mod.Config.ENABLE_TRACING = True

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("opentelemetry"):
            raise ImportError("otel missing")
        return real_import(name, globals, locals, fromlist, level)

    logs = []
    logger_obj = types.SimpleNamespace(warning=lambda msg, *a: logs.append(msg % a if a else msg))
    monkeypatch.setattr(builtins, "__import__", _fake_import)

    assert cfg_mod.Config.init_telemetry(logger_obj=logger_obj) is False
    assert any("OpenTelemetry bağımlılıkları" in line for line in logs)


def test_init_telemetry_happy_path_and_runtime_exception(monkeypatch):
    cfg_mod = _load_config_module()
    cfg_mod.Config.ENABLE_TRACING = True
    cfg_mod.Config.OTEL_INSTRUMENT_FASTAPI = True
    cfg_mod.Config.OTEL_INSTRUMENT_HTTPX = True
    cfg_mod.Config.OTEL_EXPORTER_ENDPOINT = "http://otel:4317"

    calls = {"set_provider": 0, "instrument_app": 0, "instrument_httpx": 0}

    class _Trace:
        @staticmethod
        def set_tracer_provider(_provider):
            calls["set_provider"] += 1

    class _Resource:
        @staticmethod
        def create(_attrs):
            return {"service.name": "sidar"}

    class _Provider:
        def __init__(self, resource=None):
            self.resource = resource

        def add_span_processor(self, _processor):
            return None

    class _Exporter:
        def __init__(self, endpoint=None, insecure=True):
            self.endpoint = endpoint
            self.insecure = insecure

    class _Batch:
        def __init__(self, _exporter):
            return None

    class _FastAPIInstrumentor:
        @staticmethod
        def instrument_app(_app):
            calls["instrument_app"] += 1

    class _HTTPXInstrumentor:
        def instrument(self):
            calls["instrument_httpx"] += 1

    logs = {"info": [], "warning": []}
    logger_obj = types.SimpleNamespace(
        info=lambda msg, *a: logs["info"].append(msg % a if a else msg),
        warning=lambda msg, *a: logs["warning"].append(msg % a if a else msg),
    )

    ok = cfg_mod.Config.init_telemetry(
        service_name="sidar",
        fastapi_app=object(),
        logger_obj=logger_obj,
        trace_module=_Trace,
        otlp_exporter_cls=_Exporter,
        tracer_provider_cls=_Provider,
        resource_cls=_Resource,
        batch_span_processor_cls=_Batch,
        fastapi_instrumentor_cls=_FastAPIInstrumentor,
        httpx_instrumentor_cls=_HTTPXInstrumentor,
    )
    assert ok is True
    assert calls["set_provider"] == 1
    assert calls["instrument_app"] == 1
    assert calls["instrument_httpx"] == 1
    assert any("OpenTelemetry aktif" in line for line in logs["info"])

    class _BrokenExporter:
        def __init__(self, endpoint=None, insecure=True):
            raise RuntimeError("exporter init failed")

    failed = cfg_mod.Config.init_telemetry(
        logger_obj=logger_obj,
        trace_module=_Trace,
        otlp_exporter_cls=_BrokenExporter,
        tracer_provider_cls=_Provider,
        resource_cls=_Resource,
        batch_span_processor_cls=_Batch,
    )
    assert failed is False
    assert any("başlatılamadı" in line for line in logs["warning"])

def test_config_env_helper_functions_runtime(monkeypatch):
    cfg_mod = _load_config_module()

    monkeypatch.setenv("BOOL_X", "   ")
    assert cfg_mod.get_bool_env("BOOL_X", True) is True

    monkeypatch.setenv("INT_X", "bad")
    assert cfg_mod.get_int_env("INT_X", 7) == 7

    monkeypatch.setenv("FLOAT_X", "bad")
    assert cfg_mod.get_float_env("FLOAT_X", 1.25) == 1.25

    monkeypatch.setenv("LIST_X", "a|b| |c")
    assert cfg_mod.get_list_env("LIST_X", separator="|") == ["a", "b", "c"]


def test_config_import_dev_alias_uses_base_env_message(monkeypatch):
    load_calls = []
    printed = []

    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: load_calls.append((a, k))

    saved = sys.modules.get("dotenv")
    try:
        sys.modules["dotenv"] = dotenv_mod
        monkeypatch.setenv("SIDAR_ENV", "development")
        monkeypatch.setattr(builtins, "print", lambda *a, **k: printed.append(" ".join(map(str, a))))

        def _exists(path_obj):
            p = str(path_obj)
            return p.endswith(".env")

        monkeypatch.setattr(Path, "exists", _exists)

        spec = importlib.util.spec_from_file_location("config_runtime_dev_alias_under_test", Path("config.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        assert any("temel .env ayarları kullanılacak" in m for m in printed)
        assert len(load_calls) == 1
    finally:
        if saved is None:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = saved


def test_validate_critical_settings_for_openai_anthropic_and_litellm_missing_env(monkeypatch):
    cfg_mod = _load_config_module()
    cfg_mod.Config._hardware_loaded = True
    cfg_mod.Config.initialize_directories = classmethod(lambda cls: True)
    cfg_mod.Config.MEMORY_ENCRYPTION_KEY = ""

    errors = []
    monkeypatch.setattr(cfg_mod.logger, "error", lambda msg, *args: errors.append(msg % args if args else msg))

    cfg_mod.Config.AI_PROVIDER = "openai"
    cfg_mod.Config.OPENAI_API_KEY = ""
    assert cfg_mod.Config.validate_critical_settings() is False
    assert any("OPENAI_API_KEY" in e for e in errors)

    errors.clear()
    cfg_mod.Config.AI_PROVIDER = "anthropic"
    cfg_mod.Config.ANTHROPIC_API_KEY = ""
    assert cfg_mod.Config.validate_critical_settings() is False
    assert any("ANTHROPIC_API_KEY" in e for e in errors)

    errors.clear()
    cfg_mod.Config.AI_PROVIDER = "litellm"
    cfg_mod.Config.LITELLM_GATEWAY_URL = ""
    assert cfg_mod.Config.validate_critical_settings() is False
    assert any("LITELLM_GATEWAY_URL" in e for e in errors)

def test_get_env_helpers_typeerror_and_profile_trimmed_override(monkeypatch):
    cfg_mod = _load_config_module()

    real_getenv = cfg_mod.os.getenv
    monkeypatch.setattr(cfg_mod.os, "getenv", lambda *_a, **_k: object())
    assert cfg_mod.get_int_env("TYPE_ERR_INT", 9) == 9
    assert cfg_mod.get_float_env("TYPE_ERR_FLOAT", 1.75) == 1.75
    monkeypatch.setattr(cfg_mod.os, "getenv", real_getenv)

    load_calls = []
    printed = []
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: load_calls.append((a, k))

    saved = sys.modules.get("dotenv")
    try:
        sys.modules["dotenv"] = dotenv_mod
        monkeypatch.setenv("SIDAR_ENV", " Production ")
        monkeypatch.setattr(builtins, "print", lambda *a, **k: printed.append(" ".join(map(str, a))))

        def _exists(path_obj):
            path = str(path_obj)
            return path.endswith(".env") or path.endswith(".env.production")

        monkeypatch.setattr(Path, "exists", _exists)

        spec = importlib.util.spec_from_file_location("config_runtime_trimmed_profile_under_test", Path("config.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        assert len(load_calls) == 2
        assert load_calls[0][1].get("override") in (None, False)
        assert load_calls[1][1].get("override") is True
        assert any(".env.production" in msg for msg in printed)
    finally:
        if saved is None:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = saved

def test_hardware_detection_invalid_fraction_env_falls_back_to_safe_default(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("GPU_MEMORY_FRACTION", "harfli")
    monkeypatch.setenv("LLM_GPU_MEMORY_FRACTION", "yanlis")
    monkeypatch.setenv("RAG_GPU_MEMORY_FRACTION", "bozuk")

    calls = {"frac": None}

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def get_device_name(_dev):
            return "Mocked RTX"

        @staticmethod
        def set_per_process_memory_fraction(frac, device):
            calls["frac"] = (frac, device)

    class FakeTorch:
        cuda = FakeCuda()

        class version:
            cuda = "12.x"

    monkeypatch.setitem(sys.modules, "torch", FakeTorch())
    hw = cfg_mod.check_hardware()
    assert hw.has_cuda is True
    assert calls["frac"] == (0.8, 0)


def test_init_telemetry_imported_classes_and_missing_httpx_instrumentor(monkeypatch):
    cfg_mod = _load_config_module()
    cfg_mod.Config.ENABLE_TRACING = True
    cfg_mod.Config.OTEL_INSTRUMENT_FASTAPI = True
    cfg_mod.Config.OTEL_INSTRUMENT_HTTPX = True
    cfg_mod.Config.OTEL_EXPORTER_ENDPOINT = "http://otel:4317"

    calls = {"provider": 0, "fastapi": 0}

    class _TraceModule:
        @staticmethod
        def set_tracer_provider(_provider):
            calls["provider"] += 1

    class _Exporter:
        def __init__(self, endpoint=None, insecure=True):
            self.endpoint = endpoint
            self.insecure = insecure

    class _Provider:
        def __init__(self, resource=None):
            self.resource = resource

        def add_span_processor(self, _processor):
            return None

    class _Resource:
        @staticmethod
        def create(attrs):
            return attrs

    class _BatchSpanProcessor:
        def __init__(self, _exporter):
            return None

    class _FastAPIInstrumentor:
        @staticmethod
        def instrument_app(_app):
            calls["fastapi"] += 1

    import types as _types
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "opentelemetry.exporter.otlp.proto.grpc.trace_exporter":
            mod = _types.ModuleType(name)
            mod.OTLPSpanExporter = _Exporter
            return mod
        if name == "opentelemetry.sdk.trace":
            mod = _types.ModuleType(name)
            mod.TracerProvider = _Provider
            return mod
        if name == "opentelemetry.sdk.resources":
            mod = _types.ModuleType(name)
            mod.Resource = _Resource
            return mod
        if name == "opentelemetry.sdk.trace.export":
            mod = _types.ModuleType(name)
            mod.BatchSpanProcessor = _BatchSpanProcessor
            return mod
        if name == "opentelemetry.instrumentation.fastapi":
            mod = _types.ModuleType(name)
            mod.FastAPIInstrumentor = _FastAPIInstrumentor
            return mod
        if name == "opentelemetry.instrumentation.httpx":
            raise ImportError("httpx instrumentor missing")
        return real_import(name, globals, locals, fromlist, level)

    logs = {"info": [], "warning": []}
    logger_obj = _types.SimpleNamespace(
        info=lambda msg, *a: logs["info"].append(msg % a if a else msg),
        warning=lambda msg, *a: logs["warning"].append(msg % a if a else msg),
    )

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    ok = cfg_mod.Config.init_telemetry(
        fastapi_app=object(),
        logger_obj=logger_obj,
        trace_module=_TraceModule,
    )

    assert ok is True
    assert calls["provider"] == 1
    assert calls["fastapi"] == 1
    assert any("OpenTelemetry aktif" in line for line in logs["info"])


def test_config_summary_prints_litellm_gateway_and_model(capsys):
    cfg_mod = _load_config_module()
    cfg_mod.Config.AI_PROVIDER = "litellm"
    cfg_mod.Config.LITELLM_GATEWAY_URL = "http://gateway:4000"
    cfg_mod.Config.LITELLM_MODEL = "gpt-4o-mini"
    cfg_mod.Config.OPENAI_MODEL = "fallback-openai"

    cfg_mod.Config.print_config_summary()
    out, _ = capsys.readouterr()
    assert "LiteLLM Gateway" in out
    assert "http://gateway:4000" in out
    assert "LiteLLM Modeli" in out
    assert "gpt-4o-mini" in out
