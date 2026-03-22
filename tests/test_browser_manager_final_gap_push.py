from pathlib import Path

import pytest

from tests.test_browser_manager import BM_MOD, _Config

def test_browser_manager_summarize_audit_log_skips_low_risk_click_from_high_risk_bucket():
    manager = BM_MOD.BrowserManager(_Config())
    manager._record_audit_event(
        session_id="sess-low-risk",
        action="browser_click",
        status="executed",
        selector="a.help-link",
        current_url="https://example.com/help",
    )

    summary = manager.summarize_audit_log("sess-low-risk")

    assert summary["status"] == "ok"
    assert summary["high_risk_actions"] == []
    assert summary["urls"] == ["https://example.com/help"]

def test_browser_manager_collect_session_signals_can_capture_only_screenshot(tmp_path):
    manager = BM_MOD.BrowserManager(_Config())
    manager.artifact_dir = tmp_path

    class _Page:
        def screenshot(self, path, full_page):
            Path(path).write_bytes(b"png")

    session = BM_MOD.BrowserSession(
        session_id="sess-screenshot-only",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
        current_url="https://example.com/dashboard",
    )
    manager._sessions[session.session_id] = session

    signal = manager.collect_session_signals(
        session.session_id,
        include_dom=False,
        include_screenshot=True,
    )

    assert "dom_capture" not in signal
    assert signal["screenshot"]["ok"] is True
    assert Path(signal["screenshot"]["path"]).exists()

def test_browser_manager_goto_url_records_navigation_failure_for_playwright_page():
    manager = BM_MOD.BrowserManager(_Config())

    class _Page:
        def goto(self, *_args, **_kwargs):
            raise RuntimeError("page crashed before load")

    session = BM_MOD.BrowserSession(
        session_id="sess-goto-fail",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
    )
    manager._sessions[session.session_id] = session

    with pytest.raises(RuntimeError, match="page crashed before load"):
        manager.goto_url(session.session_id, "https://example.com/reports")

    audit = [entry for entry in manager.list_audit_log() if entry["session_id"] == session.session_id]
    assert audit[-1]["action"] == "browser_goto_url"
    assert audit[-1]["status"] == "execution_failed"
    assert audit[-1]["details"]["error"] == "page crashed before load"

def test_browser_manager_capture_dom_raises_when_selector_is_missing():
    manager = BM_MOD.BrowserManager(_Config())

    class _Locator:
        def inner_html(self, timeout):
            assert timeout == 5000
            raise LookupError("selector not found")

    class _Page:
        def locator(self, selector):
            assert selector == "#missing"
            return _Locator()

    session = BM_MOD.BrowserSession(
        session_id="sess-missing-dom",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
    )
    manager._sessions[session.session_id] = session

    with pytest.raises(LookupError, match="selector not found"):
        manager.capture_dom(session.session_id, selector="#missing")

def test_browser_manager_close_session_succeeds_when_playwright_runtime_is_absent():
    manager = BM_MOD.BrowserManager(_Config())
    calls = []

    class _Closable:
        def __init__(self, label):
            self.label = label

        def close(self):
            calls.append(self.label)

    session = BM_MOD.BrowserSession(
        session_id="sess-no-runtime",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        context=_Closable("context"),
        browser=_Closable("browser"),
        runtime=None,
    )
    manager._sessions[session.session_id] = session

    ok, message = manager.close_session(session.session_id)

    assert ok is True
    assert "kapatıldı" in message
    assert calls == ["context", "browser"]
    assert manager.list_audit_log()[-1]["status"] == "executed"