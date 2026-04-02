from types import SimpleNamespace

from managers.browser_manager import BrowserManager, BrowserSession


class _Cfg:
    BROWSER_PROVIDER = "auto"
    BROWSER_HEADLESS = True
    BROWSER_TIMEOUT_MS = 5000
    BROWSER_ALLOWED_DOMAINS = []


def _build_manager() -> BrowserManager:
    return BrowserManager(config=_Cfg())


def test_audit_summary_reports_failed_and_risk_level() -> None:
    manager = _build_manager()
    manager._record_audit_event(
        session_id="s1",
        action="browser_click",
        status="failed",
        selector="#delete-btn",
        current_url="https://example.test",
    )

    summary = manager.summarize_audit_log("s1")

    assert summary["status"] == "failed"
    assert summary["risk"] == "yüksek"
    assert "browser_click:#delete-btn" in summary["failed_actions"]


def test_session_url_prefers_provider_specific_sources() -> None:
    manager = _build_manager()
    playwright_session = BrowserSession(
        session_id="1",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0,
        page=SimpleNamespace(url="https://playwright.local"),
    )
    selenium_session = BrowserSession(
        session_id="2",
        provider="selenium",
        browser_name="firefox",
        headless=True,
        started_at=0,
        driver=SimpleNamespace(current_url="https://selenium.local"),
    )

    assert manager._session_url(playwright_session) == "https://playwright.local"
    assert manager._session_url(selenium_session) == "https://selenium.local"


def test_summarize_value_masks_text_length() -> None:
    assert BrowserManager._summarize_value("1234") == "****"
    assert BrowserManager._summarize_value("abcdefghij") == "ab***ij (len=10)"
