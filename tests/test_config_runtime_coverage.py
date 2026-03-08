import importlib.util
import runpy
import sys
import types
from pathlib import Path


def _load_config_module(monkeypatch, name="config_under_test"):
    calls = []

    def _fake_load_dotenv(*, dotenv_path, override=False):
        calls.append((Path(dotenv_path).name, override))

    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=_fake_load_dotenv))

    spec = importlib.util.spec_from_file_location(name, Path("config.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, calls


def test_env_profile_loading_prefers_base_then_profile(monkeypatch, capsys):
    base = Path(".env")
    profile = Path(".env.production")
    base.write_text("X=1\n", encoding="utf-8")
    profile.write_text("X=2\n", encoding="utf-8")

    try:
        monkeypatch.setenv("SIDAR_ENV", "production")
        _, calls = _load_config_module(monkeypatch, "config_under_test_profile")
        out = capsys.readouterr().out
    finally:
        base.unlink(missing_ok=True)
        profile.unlink(missing_ok=True)

    assert calls == [(".env", False), (".env.production", True)]
    assert "Ortama özgü yapılandırma yüklendi" in out


def test_env_profile_loading_warns_when_profile_missing(monkeypatch, capsys):
    monkeypatch.setenv("SIDAR_ENV", "staging")
    _, calls = _load_config_module(monkeypatch, "config_under_test_profile_missing")
    out = capsys.readouterr().out

    assert calls == []
    assert "Belirtilen ortam dosyası bulunamadı" in out


def test_env_helpers_and_wsl2_fallback(monkeypatch):
    mod, _ = _load_config_module(monkeypatch, "config_under_test_helpers")

    monkeypatch.delenv("MISSING_BOOL", raising=False)
    monkeypatch.setenv("BAD_INT", "abc")
    monkeypatch.setenv("BAD_FLOAT", "xyz")
    monkeypatch.delenv("LIST_EMPTY", raising=False)

    assert mod.get_bool_env("MISSING_BOOL", default=True) is True
    assert mod.get_int_env("BAD_INT", default=11) == 11
    assert mod.get_float_env("BAD_FLOAT", default=1.25) == 1.25
    assert mod.get_list_env("LIST_EMPTY", default=["fallback"]) == ["fallback"]

    monkeypatch.setattr(Path, "read_text", lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    assert mod._is_wsl2() is False


def test_check_hardware_handles_disabled_gpu_and_torch_importerror(monkeypatch):
    mod, _ = _load_config_module(monkeypatch, "config_under_test_hw")

    monkeypatch.setenv("USE_GPU", "false")
    disabled = mod.check_hardware()
    assert disabled.gpu_name == "Devre Dışı (Kullanıcı)"

    monkeypatch.setenv("USE_GPU", "true")
    orig_import = __import__

    def _raising_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("no torch")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _raising_import)
    no_torch = mod.check_hardware()
    assert no_torch.gpu_name == "PyTorch Yok"


def test_config_methods_cover_error_and_warning_paths(monkeypatch, tmp_path):
    mod, _ = _load_config_module(monkeypatch, "config_under_test_methods")
    cfg = mod.Config

    cfg._hardware_loaded = False
    monkeypatch.setattr(mod, "check_hardware", lambda: mod.HardwareInfo(True, "RTX", 2, 8, "12.4", "550"))
    cfg._ensure_hardware_info_loaded()
    assert (cfg.USE_GPU, cfg.GPU_INFO, cfg.GPU_COUNT, cfg.CPU_COUNT) == (True, "RTX", 2, 8)

    class _BadFolder:
        name = "x"

        def mkdir(self, parents, exist_ok):
            raise OSError("nope")

    cfg.REQUIRED_DIRS = [_BadFolder()]
    assert cfg.initialize_directories() is False

    cfg.set_provider_mode("online")
    assert cfg.AI_PROVIDER == "gemini"
    cfg.set_provider_mode("invalid")
    assert cfg.AI_PROVIDER == "gemini"

    cfg._hardware_loaded = True
    cfg.initialize_directories = classmethod(lambda cls: True)
    cfg.AI_PROVIDER = "gemini"
    cfg.GEMINI_API_KEY = ""
    cfg.MEMORY_ENCRYPTION_KEY = "bad-key"

    class _BadFernet:
        def __init__(self, key):
            raise ValueError("bad key")

    monkeypatch.setitem(sys.modules, "cryptography.fernet", types.SimpleNamespace(Fernet=_BadFernet))
    assert cfg.validate_critical_settings() is False

    cfg.AI_PROVIDER = "ollama"
    cfg.OLLAMA_URL = "http://localhost:11434"

    class _Resp:
        status_code = 503

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url):
            return _Resp()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(Client=_Client))
    assert cfg.validate_critical_settings() is False

    cfg.AI_PROVIDER = "ollama"
    cfg.OLLAMA_URL = "http://localhost:11434/api"

    class _BrokenClient(_Client):
        def get(self, url):
            raise RuntimeError("down")

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(Client=_BrokenClient))
    info = cfg.get_system_info()
    assert info["provider"] == "ollama"


def test_print_summary_and_main_entrypoint(monkeypatch, capsys):
    mod, _ = _load_config_module(monkeypatch, "config_under_test_print")
    cfg = mod.Config
    cfg._hardware_loaded = True
    cfg.USE_GPU = False
    cfg.AI_PROVIDER = "gemini"
    cfg.MEMORY_ENCRYPTION_KEY = ""
    cfg.print_config_summary()
    out = capsys.readouterr().out
    assert "Yapılandırma Özeti" in out
    assert "Gemini Modeli" in out

    monkeypatch.setenv("DEBUG_MODE", "true")

    def _fake_load_dotenv(*, dotenv_path, override=False):
        return None

    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=_fake_load_dotenv))
    runpy.run_path("config.py", run_name="__main__")
