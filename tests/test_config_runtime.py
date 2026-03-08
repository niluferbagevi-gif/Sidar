import builtins
import importlib.util
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


def test_config_summary_print(capsys):
    cfg_mod = _load_config_module()
    c = cfg_mod.Config()
    c.print_config_summary()
    out, _ = capsys.readouterr()
    assert "Yapılandırma Özeti" in out