import builtins
import sys
import types
from types import SimpleNamespace

from tests.test_browser_manager import BM_MOD, _Config


def test_browser_manager_summarize_audit_log_ignores_entries_without_action_and_deduplicates_failures():
    manager = BM_MOD.BrowserManager(_Config())
    manager._record_audit_event(
        session_id="sess-summary-gaps",
        action="",
        status="failed",
        selector="#noop",
        current_url="https://example.com/noop",
    )
    manager._record_audit_event(
        session_id="sess-summary-gaps",
        action="browser_click",
        status="failed",
        selector="button.save",
        current_url="https://example.com/save",
    )
    manager._record_audit_event(
        session_id="sess-summary-gaps",
        action="browser_click",
        status="failed",
        selector="button.save",
        current_url="https://example.com/save",
    )

    summary = manager.summarize_audit_log("sess-summary-gaps")

    assert summary["action_counts"] == {"browser_click": 2}
    assert summary["failed_actions"] == ["browser_click:button.save"]


def test_browser_manager_start_selenium_session_for_chrome_without_headless_flag(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    constructed = []

    class _ChromeOptions:
        def __init__(self):
            self.arguments = []

        def add_argument(self, value):
            self.arguments.append(value)

    class _Driver:
        def __init__(self, options):
            self.options = options
            self.page_timeout = None

        def set_page_load_timeout(self, value):
            self.page_timeout = value

    def _chrome(*, options):
        driver = _Driver(options)
        constructed.append(driver)
        return driver

    webdriver_mod = SimpleNamespace(
        ChromeOptions=_ChromeOptions,
        FirefoxOptions=lambda: None,
        Chrome=_chrome,
        Firefox=lambda **_kwargs: None,
    )
    monkeypatch.setitem(sys.modules, "selenium", SimpleNamespace(webdriver=webdriver_mod))

    session = manager._start_selenium_session("chrome", headless=False)

    assert session.provider == "selenium"
    assert constructed[0].options.arguments == ["--disable-dev-shm-usage", "--no-sandbox"]


def test_browser_manager_is_available_falls_back_to_selenium_when_playwright_import_fails(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    manager.provider = "auto"

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api":
            raise ImportError("playwright missing")
        if name == "selenium":
            return types.SimpleNamespace()
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    assert manager.is_available() is True


def test_browser_manager_fill_form_selenium_skips_clear_when_requested(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    calls = []

    class _Element:
        def clear(self):
            calls.append("clear")

        def send_keys(self, value):
            calls.append(("send_keys", value))

    class _Driver:
        def find_element(self, by, selector):
            calls.append(("find", by, selector))
            return _Element()

    by_mod = SimpleNamespace(CSS_SELECTOR="css selector")
    monkeypatch.setitem(sys.modules, "selenium.webdriver.common.by", SimpleNamespace(By=by_mod))

    session = BM_MOD.BrowserSession(
        session_id="sess-selenium-fill",
        provider="selenium",
        browser_name="chrome",
        headless=True,
        started_at=0.0,
        driver=_Driver(),
    )
    manager._sessions[session.session_id] = session

    ok, message = manager._fill_form_impl(session.session_id, "#name", "Sidar", clear=False)

    assert ok is True
    assert "Form dolduruldu" in message
    assert "clear" not in calls
    assert ("send_keys", "Sidar") in calls


def test_browser_manager_close_session_playwright_only_stops_runtime_when_context_and_browser_are_missing():
    manager = BM_MOD.BrowserManager(_Config())
    calls = []

    session = BM_MOD.BrowserSession(
        session_id="sess-runtime-only",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        context=None,
        browser=None,
        runtime=SimpleNamespace(stop=lambda: calls.append("runtime.stop")),
    )
    manager._sessions[session.session_id] = session

    ok, message = manager.close_session(session.session_id)

    assert ok is True
    assert "kapatıldı" in message
    assert calls == ["runtime.stop"]


def test_browser_manager_close_session_uses_selenium_driver_quit_path():
    manager = BM_MOD.BrowserManager(_Config())
    calls = []

    session = BM_MOD.BrowserSession(
        session_id="sess-selenium-close",
        provider="selenium",
        browser_name="firefox",
        headless=True,
        started_at=0.0,
        driver=SimpleNamespace(quit=lambda: calls.append("driver.quit")),
    )
    manager._sessions[session.session_id] = session

    ok, message = manager.close_session(session.session_id)

    assert ok is True
    assert "kapatıldı" in message
    assert calls == ["driver.quit"]
    assert manager.list_audit_log()[-1]["status"] == "executed"
