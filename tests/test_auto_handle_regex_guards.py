from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

for _mod_name, _class_name in [
    ("managers.web_search", "WebSearchManager"),
    ("managers.package_info", "PackageInfoManager"),
    ("core.rag", "DocumentStore"),
    ("core.memory", "ConversationMemory"),
]:
    _mod = types.ModuleType(_mod_name)
    _mod.__dict__[_class_name] = type(_class_name, (), {})
    sys.modules.setdefault(_mod_name, _mod)

from agent.auto_handle import AutoHandle


class _Code:
    def list_directory(self, path):
        return True, path


def _build_handler() -> AutoHandle:
    return AutoHandle(
        code=_Code(),
        health=SimpleNamespace(full_report=lambda: "ok"),
        github=SimpleNamespace(),
        memory=SimpleNamespace(get_last_file=lambda: None),
        web=SimpleNamespace(),
        pkg=SimpleNamespace(),
        docs=SimpleNamespace(),
        cfg=SimpleNamespace(AUTO_HANDLE_TIMEOUT=1),
    )


def test_multi_step_regex_detects_chained_requests():
    text = "Önce testleri çalıştır ardından raporu hazırla"
    assert AutoHandle._MULTI_STEP_RE.search(text)


def test_multi_step_regex_ignores_single_step_command():
    text = "Sadece health durumunu göster"
    assert AutoHandle._MULTI_STEP_RE.search(text) is None


def test_dot_command_regex_rejects_non_commands():
    assert AutoHandle._DOT_CMD_RE.match("status") is None
    assert AutoHandle._DOT_CMD_RE.match(".unknown") is None


def test_handle_skips_auto_mode_for_multi_step_input():
    handler = _build_handler()

    handled, response = asyncio.run(handler.handle("1) health kontrol et 2) sonra deploy et"))

    assert handled is False
    assert response == ""
