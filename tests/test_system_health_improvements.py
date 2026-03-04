"""SystemHealthManager iyileştirmeleri için hedefli regresyon testleri."""

from pathlib import Path
import importlib.util
import sys
import types


def _load_system_health_manager():
    pkg = types.ModuleType("managers")
    pkg.__path__ = [str(Path("managers").resolve())]
    sys.modules.setdefault("managers", pkg)

    spec = importlib.util.spec_from_file_location("managers.system_health", "managers/system_health.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["managers.system_health"] = mod
    spec.loader.exec_module(mod)
    return mod.SystemHealthManager


def test_get_cpu_usage_defaults_to_non_blocking_interval(monkeypatch):
    """get_cpu_usage() varsayılan olarak psutil'e interval=None ile gider."""
    SystemHealthManager = _load_system_health_manager()

    calls = []
    fake_psutil = types.SimpleNamespace(cpu_percent=lambda interval=None: calls.append(interval) or 12.5)
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    mgr = SystemHealthManager(use_gpu=False)
    mgr._psutil_available = True

    value = mgr.get_cpu_usage()

    assert value == 12.5
    # ctor seed + gerçek çağrı
    assert calls[0] is None
    assert calls[-1] is None


def test_close_is_idempotent_and_shuts_down_nvml_once(monkeypatch):
    """close() birden fazla çağrılsa da nvmlShutdown tek kez çağrılır."""
    SystemHealthManager = _load_system_health_manager()

    counter = {"shutdown": 0}
    fake_pynvml = types.SimpleNamespace(nvmlShutdown=lambda: counter.__setitem__("shutdown", counter["shutdown"] + 1))
    monkeypatch.setitem(sys.modules, "pynvml", fake_pynvml)

    mgr = SystemHealthManager(use_gpu=False)
    mgr._nvml_initialized = True

    mgr.close()
    mgr.close()

    assert counter["shutdown"] == 1
    assert mgr._nvml_initialized is False
