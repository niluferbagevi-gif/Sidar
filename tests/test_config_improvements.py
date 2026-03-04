"""Config iyileştirmeleri için hedefli regresyon testleri."""

import sys
import types

# Test ortamında python-dotenv yoksa config importu için basit stub sağla.
if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: False
    sys.modules["dotenv"] = dotenv_stub

from config import Config, HardwareInfo
import config as cfg_mod



def test_refresh_hardware_info_updates_runtime_fields(monkeypatch):
    """Config.refresh_hardware_info() lazy donanım bilgisini sınıfa yansıtır."""
    fake_info = HardwareInfo(
        has_cuda=True,
        gpu_name="Fake GPU",
        gpu_count=2,
        cpu_count=16,
        cuda_version="12.4",
        driver_version="550.99",
    )
    monkeypatch.setattr(cfg_mod, "get_hardware_info", lambda force_refresh=False: fake_info)

    info = Config.refresh_hardware_info(force=True)

    assert info is fake_info
    assert Config.USE_GPU is True
    assert Config.GPU_INFO == "Fake GPU"
    assert Config.GPU_COUNT == 2
    assert Config.CPU_COUNT == 16
    assert Config.CUDA_VERSION == "12.4"
    assert Config.DRIVER_VERSION == "550.99"


def test_validate_critical_settings_skips_ollama_probe_when_disabled(monkeypatch):
    """Ollama probe kapalıyken validate ağ çağrısı yapmadan bool döndürür."""
    monkeypatch.setattr(Config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "OLLAMA_PROBE_ON_VALIDATE", False)

    called = {"value": False}

    def _should_not_run(*args, **kwargs):
        called["value"] = True
        raise AssertionError("Probe kapalıyken check_hardware çağrılmamalı")

    monkeypatch.setattr(cfg_mod, "check_hardware", _should_not_run)

    result = Config.validate_critical_settings()

    assert isinstance(result, bool)
    assert called["value"] is False


def test_get_hardware_info_uses_cache(monkeypatch):
    """get_hardware_info(force_refresh=False) cache değerini yeniden kullanır."""
    counter = {"n": 0}

    def _fake_check_hardware():
        counter["n"] += 1
        return HardwareInfo(has_cuda=False, gpu_name="CPU", cpu_count=8)

    monkeypatch.setattr(cfg_mod, "_HARDWARE_CACHE", None)
    monkeypatch.setattr(cfg_mod, "check_hardware", _fake_check_hardware)

    first = cfg_mod.get_hardware_info()
    second = cfg_mod.get_hardware_info()

    assert first is second
    assert counter["n"] == 1