from types import SimpleNamespace

import pytest

from tests.test_browser_manager import BM_MOD, _Config


def test_browser_manager_start_session_returns_error_when_webdriver_cannot_connect(monkeypatch):
    cfg = SimpleNamespace(
        BROWSER_PROVIDER="selenium",
        BROWSER_HEADLESS=True,
        BROWSER_TIMEOUT_MS=5000,
        BROWSER_ALLOWED_DOMAINS=["example.com"],
    )
    manager = BM_MOD.BrowserManager(cfg)

    monkeypatch.setattr(manager, "_start_selenium_session", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("webdriver bağlantısı kurulamadı")))

    ok, payload = manager.start_session(browser_name="chrome", headless=True)

    assert ok is False
    assert payload == {"error": "webdriver bağlantısı kurulamadı"}
    assert manager.list_audit_log()[-1]["session_id"] == "startup:selenium"
    assert manager.list_audit_log()[-1]["status"] == "failed"


def test_browser_manager_click_element_audits_timeout_exception_from_missing_element():
    manager = BM_MOD.BrowserManager(_Config())
    class TimeoutException(Exception):
        pass

    class _Page:
        def click(self, selector, timeout):
            raise TimeoutException(f"element bulunamadı: {selector}")

    session = BM_MOD.BrowserSession(
        session_id="sess-timeout",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
    )
    manager._sessions[session.session_id] = session

    with pytest.raises(TimeoutException, match="#missing"):
        manager.click_element(session.session_id, "#missing")

    audit = manager.list_audit_log()
    assert audit[-1]["action"] == "browser_click"
    assert audit[-1]["status"] == "execution_failed"
    assert "element bulunamadı: #missing" == audit[-1]["details"]["error"]


def test_browser_manager_goto_url_audits_page_closed_before_load():
    manager = BM_MOD.BrowserManager(_Config())
    class _Page:
        def goto(self, url, wait_until, timeout):
            raise RuntimeError("sayfa yüklenmeden kapandı")

    session = BM_MOD.BrowserSession(
        session_id="sess-closed",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
    )
    manager._sessions[session.session_id] = session

    with pytest.raises(RuntimeError, match="sayfa yüklenmeden kapandı"):
        manager.goto_url(session.session_id, "https://example.com/closed")

    audit = manager.list_audit_log()
    assert audit[-1]["action"] == "browser_goto_url"
    assert audit[-1]["status"] == "execution_failed"
    assert audit[-1]["details"]["error"] == "sayfa yüklenmeden kapandı"
