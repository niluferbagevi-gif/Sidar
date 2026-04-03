import sys
import types
import asyncio

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

    def read_file(self, path):
        if path == "missing.py":
            return False, "not found"
        return True, "print('ok')\n"

    def validate_python_syntax(self, _content):
        return True, "valid python"

    def validate_json(self, _content):
        return False, "invalid json"


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


def test_try_read_file_uses_last_file_when_path_missing():
    handler = _build_auto_handle()
    handler.memory = SimpleNamespace(
        get_last_file=lambda: "agent/auto_handle.py",
        set_last_file=lambda _path: None,
    )
    handled, response = handler._try_read_file("dosya içeriğini göster", "dosya içeriğini göster")
    assert handled is True
    assert "[agent/auto_handle.py]" in response


def test_try_validate_file_json_and_missing_path_branches():
    handler = _build_auto_handle()
    handler.memory = SimpleNamespace(get_last_file=lambda: None)

    handled, response = handler._try_validate_file("dosya doğrula", "dosya doğrula")
    assert handled is True
    assert "Doğrulanacak dosya yolunu belirtin" in response

    handled, response = handler._try_validate_file("json dosya doğrula", "json dosya doğrula config.json")
    assert handled is True
    assert response.startswith("✗")


def test_try_clear_memory_supports_async_clear():
    import asyncio

    class _Memory:
        def __init__(self):
            self.called = False

        async def clear(self):
            self.called = True

    memory = _Memory()
    handler = _build_auto_handle()
    handler.memory = memory

    handled, response = asyncio.run(handler._try_clear_memory(".clear"))
    assert handled is True
    assert response == "✓ Konuşma belleği temizlendi."
    assert memory.called is True


def test_try_github_get_pr_handles_missing_token_and_file_mode():
    handler = _build_auto_handle()

    class _GitHub:
        def is_available(self):
            return False

    handler.github = _GitHub()
    handled, response = asyncio.run(handler._try_github_get_pr("pr #12 dosyaları", "pr #12 dosyaları"))
    assert handled is True
    assert "token ayarlanmamış" in response

    class _GitHubOk:
        def is_available(self):
            return True

        def get_pr_files(self, number):
            return True, f"files:{number}"

    handler.github = _GitHubOk()
    handled, response = asyncio.run(handler._try_github_get_pr("pr #34 dosya değişiklik", "pr #34 dosya değişiklik"))
    assert handled is True
    assert response == "files:34"


def test_try_audit_timeout_and_exception_paths(monkeypatch):
    handler = _build_auto_handle()
    handler.code = SimpleNamespace(audit_project=lambda _path: "ok")

    async def _timeout(*_args, **_kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(handler, "_run_blocking", _timeout)
    handled, response = asyncio.run(handler._try_audit(".audit"))
    assert handled is True
    assert "zaman aşımına" in response

    async def _error(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(handler, "_run_blocking", _error)
    handled, response = asyncio.run(handler._try_audit("sistemi tara"))
    assert handled is True
    assert "hata oluştu: boom" in response


def test_dot_command_routes_audit_and_gpu(monkeypatch):
    handler = _build_auto_handle()
    monkeypatch.setattr(handler, "_try_audit", AsyncMock(return_value=(True, "audit-ok")))
    monkeypatch.setattr(handler, "_try_gpu_optimize", AsyncMock(return_value=(True, "gpu-ok")))

    handled, response = asyncio.run(handler.handle(".audit"))
    assert handled is True and response == "audit-ok"

    handled, response = asyncio.run(handler.handle(".gpu"))
    assert handled is True and response == "gpu-ok"


def test_dot_command_unknown_returns_false():
    handler = _build_auto_handle()
    handled, response = asyncio.run(handler._try_dot_command(".unknown", ".unknown"))
    assert handled is False
    assert response == ""
