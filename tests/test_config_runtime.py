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
