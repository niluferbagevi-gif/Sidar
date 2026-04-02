from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from managers.browser_manager import BrowserManager, BrowserSession
from managers.code_manager import CodeManager


def _build_code_manager(tmp_path: Path) -> CodeManager:
    manager = CodeManager.__new__(CodeManager)
    manager.base_dir = tmp_path
    manager._lock = threading.RLock()
    manager._files_read = 0
    manager._files_written = 0
    manager._syntax_checks = 0
    manager.max_output_chars = 10_000
    manager._post_process_written_file = lambda _target: None
    return manager


def test_code_manager_read_file_denies_unauthorized_path(tmp_path: Path) -> None:
    manager = _build_code_manager(tmp_path)
    manager.security = SimpleNamespace(can_read=lambda _path: False)

    ok, msg = manager.read_file(str(tmp_path / "secret.txt"))

    assert ok is False
    assert "Okuma yetkisi yok" in msg


def test_code_manager_write_file_denies_and_suggests_safe_path(tmp_path: Path) -> None:
    manager = _build_code_manager(tmp_path)
    manager.security = SimpleNamespace(
        can_write=lambda _path: False,
        get_safe_write_path=lambda _name: tmp_path / "safe" / "fallback.txt",
    )

    ok, msg = manager.write_file(str(tmp_path / "unsafe.py"), "print('x')")

    assert ok is False
    assert "Yazma yetkisi yok" in msg
    assert "Güvenli alternatif" in msg


def test_code_manager_write_file_rejects_invalid_python_syntax(tmp_path: Path) -> None:
    manager = _build_code_manager(tmp_path)
    manager.security = SimpleNamespace(can_write=lambda _path: True)
    manager.validate_python_syntax = CodeManager.validate_python_syntax.__get__(manager, CodeManager)

    ok, msg = manager.write_file(str(tmp_path / "broken.py"), "def broken(:\n    pass")

    assert ok is False
    assert "Sözdizimi hatası" in msg


def test_code_manager_read_file_with_line_numbers(tmp_path: Path) -> None:
    manager = _build_code_manager(tmp_path)
    manager.security = SimpleNamespace(can_read=lambda _path: True)
    sample = tmp_path / "notes.txt"
    sample.write_text("ilk satır\nikinci satır", encoding="utf-8")

    ok, content = manager.read_file(str(sample), line_numbers=True)

    assert ok is True
    assert "1\tilk satır" in content
    assert "2\tikinci satır" in content


class _Cfg:
    BROWSER_PROVIDER = "auto"
    BROWSER_HEADLESS = True
    BROWSER_TIMEOUT_MS = 3000
    BROWSER_ALLOWED_DOMAINS = ["example.com"]


def _build_browser_manager() -> BrowserManager:
    return BrowserManager(config=_Cfg())


def test_browser_validate_url_enforces_allowlist() -> None:
    manager = _build_browser_manager()

    with pytest.raises(ValueError):
        manager._validate_url("ftp://example.com/file")
    with pytest.raises(ValueError):
        manager._validate_url("https://forbidden.test")

    manager._validate_url("https://example.com/path")


def test_browser_goto_url_records_failure_in_audit_log() -> None:
    manager = _build_browser_manager()

    class _Page:
        def goto(self, *_args, **_kwargs):
            raise RuntimeError("navigation failed")

    session = BrowserSession(
        session_id="s-nav",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
    )
    manager._sessions[session.session_id] = session

    with pytest.raises(RuntimeError):
        manager.goto_url(session.session_id, "https://example.com")

    summary = manager.summarize_audit_log("s-nav")
    assert summary["status"] == "failed"
    assert summary["status_counts"]["execution_failed"] >= 1


def test_browser_click_element_blocked_by_hitl_guard_is_audited() -> None:
    manager = _build_browser_manager()
    session = BrowserSession(
        session_id="s-click",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=SimpleNamespace(),
    )
    manager._sessions[session.session_id] = session
    manager._sync_hitl_guard = lambda *_args, **_kwargs: (False, "HITL required")

    ok, msg = manager.click_element(session.session_id, "#delete-btn")

    assert ok is False
    assert "HITL" in msg
    assert manager.list_audit_log()[-1]["status"] == "blocked_hitl"


def test_browser_capture_dom_returns_error_when_dom_lookup_fails() -> None:
    manager = _build_browser_manager()

    class _Locator:
        def inner_html(self, **_kwargs):
            raise RuntimeError("dom error")

    class _Page:
        def locator(self, _selector: str):
            return _Locator()

    session = BrowserSession(
        session_id="s-dom",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
    )
    manager._sessions[session.session_id] = session

    ok, msg = manager.capture_dom(session.session_id, "main")

    assert ok is False
    assert "DOM yakalama hatası" in msg
