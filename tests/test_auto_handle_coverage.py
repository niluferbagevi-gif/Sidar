import sys
import types

for _mod_name, _class_name in [
    ("managers.web_search", "WebSearchManager"),
    ("managers.package_info", "PackageInfoManager"),
    ("core.rag", "DocumentStore"),
]:
    _mod = types.ModuleType(_mod_name)
    _mod.__dict__[_class_name] = type(_class_name, (), {})
    sys.modules.setdefault(_mod_name, _mod)

for _mod_name, _class_name in [
    ("core.memory", "ConversationMemory"),
]:
    _mod = types.ModuleType(_mod_name)
    _mod.__dict__[_class_name] = type(_class_name, (), {})
    sys.modules.setdefault(_mod_name, _mod)

from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent.auto_handle import AutoHandle


class DummyCode:
    def list_directory(self, path):
        return True, f"list:{path}"


def _build_auto_handle():
    return AutoHandle(
        code=DummyCode(),
        health=SimpleNamespace(),
        github=SimpleNamespace(),
        memory=SimpleNamespace(get_last_file=lambda: None),
        web=SimpleNamespace(),
        pkg=SimpleNamespace(),
        docs=SimpleNamespace(),
        cfg=SimpleNamespace(AUTO_HANDLE_TIMEOUT=1),
    )


def test_handle_returns_false_for_too_long_input():
    import asyncio

    handler = _build_auto_handle()
    handled, response = asyncio.run(handler.handle("a" * 2001))
    assert handled is False
    assert response == ""


def test_dot_status_routes_to_health_handler(monkeypatch):
    import asyncio

    handler = _build_auto_handle()
    monkeypatch.setattr(handler, "_try_health", AsyncMock(return_value=(True, "ok")))

    handled, response = asyncio.run(handler.handle(".status"))

    assert handled is True
    assert response == "ok"
    handler._try_health.assert_awaited_once()


def test_list_directory_detects_directory_phrasing():
    handler = _build_auto_handle()
    handled, response = handler._try_list_directory("kök dizin listele", "kök dizin listele")
    assert handled is True
    assert response == "list:."


def test_extract_helpers_cover_path_and_url_patterns():
    handler = _build_auto_handle()
    assert handler._extract_path('dosyayı oku "agent/auto_handle.py"') == "agent/auto_handle.py"
    assert handler._extract_path("agent/sidar_agent.py dosyasını incele") == "agent/sidar_agent.py"
    assert handler._extract_url("şu adresi getir: https://example.com/docs?q=1") == "https://example.com/docs?q=1"


def test_dot_clear_routes_to_memory_handler(monkeypatch):
    import asyncio

    handler = _build_auto_handle()
    monkeypatch.setattr(handler, "_try_clear_memory", AsyncMock(return_value=(True, "cleared")))

    handled, response = asyncio.run(handler.handle(".clear"))

    assert handled is True
    assert response == "cleared"
    handler._try_clear_memory.assert_awaited_once()
