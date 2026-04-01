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


async def test_handle_returns_false_for_too_long_input():
    handler = _build_auto_handle()
    handled, response = await handler.handle("a" * 2001)
    assert handled is False
    assert response == ""


async def test_dot_status_routes_to_health_handler(monkeypatch):
    handler = _build_auto_handle()
    monkeypatch.setattr(handler, "_try_health", AsyncMock(return_value=(True, "ok")))

    handled, response = await handler.handle(".status")

    assert handled is True
    assert response == "ok"
    handler._try_health.assert_awaited_once()


def test_list_directory_detects_directory_phrasing():
    handler = _build_auto_handle()
    handled, response = handler._try_list_directory("kök dizin listele", "kök dizin listele")
    assert handled is True
    assert response == "list:."
