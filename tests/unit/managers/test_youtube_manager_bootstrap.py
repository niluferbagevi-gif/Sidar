import importlib
import sys
from types import SimpleNamespace

import tests.unit.managers.test_youtube_manager as youtube_manager_tests


def test_youtube_manager_test_module_bootstrap_injects_httpx_stub_when_missing():
    actual_httpx = sys.modules["httpx"]
    sys.modules["httpx"] = None

    original_httpx = sys.modules.pop("httpx", None)
    try:
        importlib.reload(youtube_manager_tests)
        injected = sys.modules.get("httpx")
        assert injected is not None
        assert hasattr(injected, "AsyncClient")
    finally:
        assert original_httpx is None
        sys.modules["httpx"] = SimpleNamespace(AsyncClient=object)
        importlib.reload(youtube_manager_tests)
        sys.modules["httpx"] = actual_httpx


def test_youtube_manager_test_module_bootstrap_restores_original_httpx_module():
    actual_httpx = sys.modules["httpx"]
    original_httpx = SimpleNamespace(AsyncClient=object, marker="original")
    sys.modules["httpx"] = original_httpx

    captured_original = sys.modules.pop("httpx", None)
    try:
        importlib.reload(youtube_manager_tests)
        injected = sys.modules.get("httpx")
        assert injected is not None
        assert hasattr(injected, "AsyncClient")
    finally:
        sys.modules["httpx"] = captured_original
        importlib.reload(youtube_manager_tests)
        sys.modules["httpx"] = actual_httpx
