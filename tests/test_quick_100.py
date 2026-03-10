import asyncio
import builtins
from unittest.mock import MagicMock

import pytest


def _require_runtime_imports():
    pytest.importorskip("dotenv")
    pytest.importorskip("pydantic")


def test_config_validate_critical_settings_importerror_for_cryptography(monkeypatch):
    _require_runtime_imports()
    from config import Config

    monkeypatch.setattr(Config, "MEMORY_ENCRYPTION_KEY", "invalid-key")
    monkeypatch.setattr(Config, "_ensure_hardware_info_loaded", lambda: None)
    monkeypatch.setattr(Config, "initialize_directories", lambda: True)
    monkeypatch.setattr(Config, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "set")

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name.startswith("cryptography"):
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert Config.validate_critical_settings() is False


def test_auto_handle_validate_unsupported_extension():
    _require_runtime_imports()
    from agent.auto_handle import AutoHandle

    mock_code = MagicMock()
    mock_code.read_file.return_value = (True, "dummy content")

    ah = AutoHandle(
        code=mock_code,
        health=MagicMock(),
        github=MagicMock(),
        memory=MagicMock(get_last_file=lambda: None),
        web=MagicMock(),
        pkg=MagicMock(),
        docs=MagicMock(),
    )

    is_handled, msg = ah._try_validate_file("sözdizimi doğrula", "validate test.txt")
    assert is_handled is True
    assert "desteklenmiyor" in msg


def test_auto_handle_validate_py_and_json_paths():
    _require_runtime_imports()
    from agent.auto_handle import AutoHandle

    mock_code = MagicMock()
    mock_code.read_file.side_effect = [(True, "print('x')"), (True, "{}")]
    mock_code.validate_python_syntax.return_value = (True, "py ok")
    mock_code.validate_json.return_value = (False, "json fail")

    mock_memory = MagicMock()
    mock_memory.get_last_file.return_value = "fallback.py"

    ah = AutoHandle(
        code=mock_code,
        health=MagicMock(),
        github=MagicMock(),
        memory=mock_memory,
        web=MagicMock(),
        pkg=MagicMock(),
        docs=MagicMock(),
    )

    handled_py, msg_py = ah._try_validate_file("sözdizimi doğrula", "app.py sözdizimi doğrula")
    handled_json, msg_json = ah._try_validate_file("sözdizimi doğrula", "data.json sözdizimi doğrula")

    assert handled_py is True and "✓" in msg_py
    assert handled_json is True and "✗" in msg_json


def test_package_info_npm_dict_author_and_peer_dependencies_branch():
    _require_runtime_imports()
    from managers.package_info import PackageInfoManager

    pkg = PackageInfoManager()

    async def mock_get_json(*args, **kwargs):
        return (
            True,
            {
                "version": "1.2.3",
                "author": {"name": "Test Author", "email": "test@test.com"},
                "peerDependencies": {"react": "^18", "next": "^15"},
            },
            "",
        )

    pkg._get_json = mock_get_json
    ok, msg = asyncio.run(pkg.npm_info("ui-pkg"))

    assert ok is True
    assert "Test Author" in msg
    assert "Peer deps" in msg


def test_tooling_missing_branches():
    _require_runtime_imports()
    from agent.tooling import parse_tool_argument

    res_pr = parse_tool_argument("github_list_prs", "closed ||| 25")
    assert res_pr.state == "closed"
    assert res_pr.limit == 25

    res_todo = parse_tool_argument("scan_project_todos", "src ||| .py, .js")
    assert res_todo.directory == "src"
    assert res_todo.extensions == [".py", ".js"]


def test_tooling_build_dispatch_maps_tools_to_agent_methods():
    _require_runtime_imports()
    from agent.tooling import build_tool_dispatch

    class _Agent:
        def __getattr__(self, _name):
            return lambda *_a, **_k: "ok"

    dispatch = build_tool_dispatch(_Agent())
    assert "github_close_issue" in dispatch
    assert callable(dispatch["github_close_issue"])
