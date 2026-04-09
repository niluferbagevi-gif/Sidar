import importlib
import sys
from types import SimpleNamespace

import tests.unit.managers.test_youtube_manager as youtube_manager_tests


def test_youtube_manager_test_module_bootstrap_injects_httpx_stub_when_missing():
    original_httpx = sys.modules.pop("httpx", None)
    try:
        importlib.reload(youtube_manager_tests)
        injected = sys.modules.get("httpx")
        assert injected is not None
        assert hasattr(injected, "AsyncClient")
    finally:
        if original_httpx is not None:
            sys.modules["httpx"] = original_httpx
        else:
            sys.modules["httpx"] = SimpleNamespace(AsyncClient=object)
        importlib.reload(youtube_manager_tests)
