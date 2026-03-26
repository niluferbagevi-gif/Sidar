import builtins
import importlib.util
import sys
import types
from pathlib import Path


def _load_config_module():
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **k: None

    saved_dotenv = sys.modules.get("dotenv")
    try:
        sys.modules["dotenv"] = dotenv_mod
        spec = importlib.util.spec_from_file_location("config_under_test", Path("config.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        if saved_dotenv is None:
            sys.modules.pop("dotenv", None)
        else:
            sys.modules["dotenv"] = saved_dotenv


def test_is_wsl2_returns_false_on_read_error(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.setattr(cfg_mod.Path, "read_text", lambda _self: (_ for _ in ()).throw(OSError("x")))
    assert cfg_mod._is_wsl2() is False


def test_check_hardware_respects_use_gpu_disabled(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.setenv("USE_GPU", "false")
    info = cfg_mod.check_hardware()
    assert info.has_cuda is False
    assert info.gpu_name == "Devre Dışı (Kullanıcı)"


def test_check_hardware_cuda_branch_with_fraction_fix_and_nvml(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setenv("GPU_MEMORY_FRACTION", "2.0")

    calls = {"frac": None}

    class _Cuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 2

        @staticmethod
        def get_device_name(_idx):
            return "RTX"

        @staticmethod
        def set_per_process_memory_fraction(frac, device=0):
            calls["frac"] = (frac, device)

    torch_mod = types.SimpleNamespace(cuda=_Cuda(), version=types.SimpleNamespace(cuda="12.4"))
    pynvml_mod = types.SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlSystemGetDriverVersion=lambda: "550.54",
        nvmlShutdown=lambda: None,
    )
    mp_mod = types.SimpleNamespace(cpu_count=lambda: 16)

    monkeypatch.setitem(sys.modules, "torch", torch_mod)
    monkeypatch.setitem(sys.modules, "pynvml", pynvml_mod)
    monkeypatch.setitem(sys.modules, "multiprocessing", mp_mod)

    info = cfg_mod.check_hardware()
    assert info.has_cuda is True
    assert info.gpu_count == 2
    assert info.gpu_name == "RTX"
    assert info.cuda_version == "12.4"
    assert info.driver_version == "550.54"
    assert info.cpu_count == 16
    assert calls["frac"] == (0.8, 0)


def test_check_hardware_importerror_and_cpu_fallback(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.setenv("USE_GPU", "true")

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name in {"torch", "multiprocessing", "pynvml"}:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    info = cfg_mod.check_hardware()
    assert info.gpu_name == "PyTorch Yok"
    assert info.cpu_count == 1


def test_check_hardware_no_cuda_non_wsl_logs_cpu_mode(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.setenv("USE_GPU", "true")
    monkeypatch.setattr(cfg_mod, "_is_wsl2", lambda: False)

    log_calls = []
    monkeypatch.setattr(cfg_mod.logger, "info", lambda msg, *a: log_calls.append(msg % a if a else msg))

    class _Cuda:
        @staticmethod
        def is_available():
            return False

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=_Cuda(), version=types.SimpleNamespace(cuda=None)))

    info = cfg_mod.check_hardware()
    assert info.gpu_name == "CUDA Bulunamadı"
    assert any("CPU modunda çalışılacak" in call for call in log_calls)


def test_config_ensure_hardware_info_loaded_gpu_and_cpu_modes(monkeypatch):
    cfg_mod = _load_config_module()
    monkeypatch.setattr(cfg_mod.os, "cpu_count", lambda: None)

    cfg_mod.Config._hardware_loaded = False
    cfg_mod.Config.USE_GPU = False
    cfg_mod.Config._ensure_hardware_info_loaded()
    assert cfg_mod.Config.GPU_INFO == "Devre Dışı / CPU Modu"
    assert cfg_mod.Config.CPU_COUNT == 1

    cfg_mod.Config._hardware_loaded = False
    cfg_mod.Config.USE_GPU = True

    monkeypatch.setattr(
        cfg_mod,
        "check_hardware",
        lambda: cfg_mod.HardwareInfo(
            has_cuda=True,
            gpu_name="A100",
            gpu_count=1,
            cpu_count=0,
            cuda_version="12.1",
            driver_version="550",
        ),
    )
    monkeypatch.setattr(cfg_mod.os, "cpu_count", lambda: 8)

    cfg_mod.Config._ensure_hardware_info_loaded()
    assert cfg_mod.Config.USE_GPU is True
    assert cfg_mod.Config.GPU_INFO == "A100"
    assert cfg_mod.Config.GPU_COUNT == 1
    assert cfg_mod.Config.CPU_COUNT == 8
    assert cfg_mod.Config.CUDA_VERSION == "12.1"
    assert cfg_mod.Config.DRIVER_VERSION == "550"