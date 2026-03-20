from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from tests.test_browser_manager import BM_MOD, _Config
from tests.test_code_manager_runtime import CM_MOD, DummySecurity, FULL


@pytest.fixture
def code_manager(tmp_path):
    with patch.object(CM_MOD.CodeManager, "_init_docker", lambda self: None):
        manager = CM_MOD.CodeManager(DummySecurity(tmp_path, level=FULL), tmp_path)
    manager.docker_available = False
    return manager


def test_code_manager_lsp_helper_branches_cover_uri_decode_and_command_resolution(code_manager):
    with pytest.raises(ValueError, match="Desteklenmeyen URI şeması"):
        CM_MOD._file_uri_to_path("https://example.com/demo.py")

    with patch.object(CM_MOD.os, "name", "nt"):
        win_path = CM_MOD._file_uri_to_path("file:///C:/repo/demo.py")
    assert str(win_path).startswith("C:/repo") or str(win_path).startswith("C:\\repo")

    assert CM_MOD._decode_lsp_stream(b"garbage without header") == []
    decoded = CM_MOD._decode_lsp_stream(
        b"Ignored-Header\r\nContent-Length: 17\r\n\r\n{\"jsonrpc\":\"2.0\"}"
    )
    assert decoded == [{"jsonrpc": "2.0"}]

    with patch.object(CM_MOD.shutil, "which", lambda binary: f"/mock/{binary}"):
        assert code_manager._resolve_lsp_command("typescript") == ["/mock/typescript-language-server", "--stdio"]
    with pytest.raises(ValueError, match="desteklenmeyen dil"):
        code_manager._resolve_lsp_command("rust")


def test_code_manager_lsp_workspace_diagnostics_returns_default_clean_summary(code_manager):
    with patch.object(code_manager, "lsp_semantic_audit", return_value=(True, {"issues": [], "summary": ""})):
        ok, message = code_manager.lsp_workspace_diagnostics(["demo.py"])

    assert ok is True
    assert message == "LSP diagnostics temiz."


def test_browser_manager_timeout_and_session_cleanup_branches_use_mocks(tmp_path):
    manager = BM_MOD.BrowserManager(_Config())
    manager.artifact_dir = tmp_path

    ok_session = BM_MOD.BrowserSession(
        session_id="sess-ok",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=SimpleNamespace(url="https://example.com/from-page"),
    )
    manager._sessions[ok_session.session_id] = ok_session
    manager._record_audit_event(
        session_id=ok_session.session_id,
        action="browser_capture_dom",
        status="executed",
        selector="main",
        current_url="https://example.com/from-page",
    )
    summary = manager.summarize_audit_log(ok_session.session_id)
    assert summary["status"] == "ok"
    assert summary["risk"] == "düşük"
    assert manager._session_url(ok_session) == "https://example.com/from-page"

    with pytest.raises(ValueError, match="http/https"):
        manager._validate_url("ftp://example.com/archive")

    quit_calls = []
    selenium_session = BM_MOD.BrowserSession(
        session_id="sess-selenium-close",
        provider="selenium",
        browser_name="chrome",
        headless=True,
        started_at=0.0,
        driver=SimpleNamespace(quit=lambda: quit_calls.append("quit")),
    )
    manager._sessions[selenium_session.session_id] = selenium_session
    ok, message = manager.close_session(selenium_session.session_id)
    assert ok is True
    assert "kapatıldı" in message
    assert quit_calls == ["quit"]

    broken_session = BM_MOD.BrowserSession(
        session_id="sess-selenium-broken",
        provider="selenium",
        browser_name="chrome",
        headless=True,
        started_at=0.0,
        driver=SimpleNamespace(quit=Mock(side_effect=TimeoutError("quit timeout"))),
    )
    manager._sessions[broken_session.session_id] = broken_session
    ok, message = manager.close_session(broken_session.session_id)
    assert ok is False
    assert "quit timeout" in message
    assert manager.list_audit_log()[-1]["status"] == "execution_failed"
