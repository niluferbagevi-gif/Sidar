"""
managers/browser_manager.py için birim testleri.
BrowserManager: _is_high_risk_click, _summarize_value, _validate_url,
constructor, _record_audit_event, summarize_audit_log.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock


def _get_bm():
    # Stub config and core.hitl
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        BROWSER_PROVIDER = "auto"
        BROWSER_HEADLESS = True
        BROWSER_TIMEOUT_MS = 15000
        BROWSER_ALLOWED_DOMAINS = []

    cfg_stub.Config = _Cfg
    sys.modules["config"] = cfg_stub

    hitl_stub = types.ModuleType("core.hitl")
    hitl_stub.get_hitl_gate = lambda: None
    sys.modules["core.hitl"] = hitl_stub

    if "managers.browser_manager" in sys.modules:
        del sys.modules["managers.browser_manager"]
    import managers.browser_manager as bm
    return bm


# ══════════════════════════════════════════════════════════════
# _is_high_risk_click
# ══════════════════════════════════════════════════════════════

class TestIsHighRiskClick:
    def test_submit_is_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("submit") is True

    def test_delete_is_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("#delete-button") is True

    def test_confirm_is_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("btn-confirm") is True

    def test_normal_selector_not_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("#next") is False

    def test_empty_not_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("") is False

    def test_publish_is_high_risk(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("publish-post") is True

    def test_case_insensitive(self):
        bm = _get_bm()
        assert bm.BrowserManager._is_high_risk_click("SUBMIT") is True


# ══════════════════════════════════════════════════════════════
# _summarize_value
# ══════════════════════════════════════════════════════════════

class TestSummarizeValue:
    def test_empty_string_returns_empty(self):
        bm = _get_bm()
        assert bm.BrowserManager._summarize_value("") == ""

    def test_short_value_masked(self):
        bm = _get_bm()
        result = bm.BrowserManager._summarize_value("1234")
        assert result == "****"

    def test_long_value_shows_prefix_suffix(self):
        bm = _get_bm()
        result = bm.BrowserManager._summarize_value("supersecretpassword")
        assert "***" in result
        assert "len=" in result

    def test_none_like_empty_handled(self):
        bm = _get_bm()
        result = bm.BrowserManager._summarize_value(None)  # type: ignore
        assert result == ""


# ══════════════════════════════════════════════════════════════
# Constructor
# ══════════════════════════════════════════════════════════════

class TestBrowserManagerInit:
    def test_default_provider_auto(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        assert mgr.provider == "auto"

    def test_default_headless_true(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        assert mgr.default_headless is True

    def test_empty_sessions_on_init(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        assert mgr._sessions == {}

    def test_empty_audit_log_on_init(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        assert mgr._audit_log == []

    def test_artifact_dir_exists(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        assert mgr.artifact_dir.exists()


# ══════════════════════════════════════════════════════════════
# _record_audit_event / list_audit_log
# ══════════════════════════════════════════════════════════════

class TestAuditLog:
    def _mgr(self):
        bm = _get_bm()
        return bm.BrowserManager()

    def test_record_adds_entry(self):
        mgr = self._mgr()
        mgr._record_audit_event(
            session_id="s1",
            action="browser_click",
            status="ok",
            selector="#btn",
        )
        assert len(mgr._audit_log) == 1

    def test_record_has_correct_fields(self):
        mgr = self._mgr()
        mgr._record_audit_event(
            session_id="s1",
            action="browser_click",
            status="ok",
            selector="#btn",
        )
        entry = mgr._audit_log[0]
        assert entry["session_id"] == "s1"
        assert entry["action"] == "browser_click"
        assert entry["status"] == "ok"

    def test_list_audit_log_returns_copy(self):
        mgr = self._mgr()
        mgr._record_audit_event(session_id="s1", action="a", status="ok")
        log = mgr.list_audit_log()
        assert isinstance(log, list)
        assert len(log) == 1

    def test_summarize_empty_log(self):
        mgr = self._mgr()
        summary = mgr.summarize_audit_log()
        assert summary["entry_count"] == 0
        assert summary["status"] == "no-signal"

    def test_summarize_with_failed_actions(self):
        mgr = self._mgr()
        mgr._record_audit_event(session_id="s1", action="browser_click", status="failed", selector="#x")
        summary = mgr.summarize_audit_log()
        assert summary["status"] == "failed"
        assert summary["risk"] == "yüksek"

    def test_summarize_pending_approval_becomes_attention(self):
        mgr = self._mgr()
        mgr._record_audit_event(
            session_id="s2",
            action="browser_click",
            status="pending_approval",
            selector="#delete-account",
        )
        summary = mgr.summarize_audit_log(session_id="s2")
        assert summary["status"] == "attention"
        assert summary["risk"] == "orta"


class TestBrowserManagerUnhappyPaths:
    def test_start_session_returns_last_error_when_all_providers_fail(self, monkeypatch):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        monkeypatch.setattr(mgr, "_provider_candidates", lambda: ["playwright", "selenium"])
        monkeypatch.setattr(mgr, "_start_playwright_session", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("pw down")))
        monkeypatch.setattr(mgr, "_start_selenium_session", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("sel down")))

        ok, payload = mgr.start_session(browser_name="chromium")
        assert ok is False
        assert "sel down" in str(payload.get("error"))
        assert len(mgr._audit_log) >= 2

    def test_goto_url_records_execution_failed_audit_and_raises(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        session = types.SimpleNamespace(
            session_id="s1",
            provider="playwright",
            page=types.SimpleNamespace(
                goto=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network offline"))
            ),
            current_url="",
        )
        mgr._sessions["s1"] = session

        import pytest
        with pytest.raises(RuntimeError, match="network offline"):
            mgr.goto_url("s1", "https://example.com")

        assert mgr._audit_log[-1]["status"] == "execution_failed"

    def test_goto_url_timeout_records_failed_audit_and_raises(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        session = types.SimpleNamespace(
            session_id="s-timeout",
            provider="playwright",
            page=types.SimpleNamespace(
                goto=lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("page load timeout"))
            ),
            current_url="",
        )
        mgr._sessions["s-timeout"] = session

        import pytest
        with pytest.raises(TimeoutError, match="page load timeout"):
            mgr.goto_url("s-timeout", "https://example.com/slow")

        assert mgr._audit_log[-1]["action"] == "browser_goto_url"
        assert mgr._audit_log[-1]["status"] == "execution_failed"


class TestBrowserManagerAutomationMocking:
    def test_start_session_playwright_mock_success(self, monkeypatch):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        fake_session = bm.BrowserSession(
            session_id="pw-1",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=1.0,
            page=types.SimpleNamespace(url=""),
        )
        monkeypatch.setattr(mgr, "_provider_candidates", lambda: ["playwright"])
        monkeypatch.setattr(mgr, "_start_playwright_session", lambda *_a, **_k: fake_session)

        ok, payload = mgr.start_session(browser_name="chromium")
        assert ok is True
        assert payload["session_id"] == "pw-1"
        assert "pw-1" in mgr._sessions

    def test_click_fill_select_use_mocked_playwright_page(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        fake_page = types.SimpleNamespace(
            click=lambda *_a, **_k: None,
            fill=lambda *_a, **_k: None,
            select_option=lambda *_a, **_k: None,
            url="https://example.com",
            content=lambda: "<html></html>",
            screenshot=lambda path=None, full_page=True: Path(path).write_bytes(b"png"),
            locator=lambda selector: types.SimpleNamespace(inner_html=lambda timeout=None: "<div>dummy</div>"),
        )
        session = bm.BrowserSession(
            session_id="s1",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=1.0,
            page=fake_page,
        )
        mgr._sessions["s1"] = session

        ok_click, _ = mgr._click_element_impl("s1", "#safe-button")
        ok_fill, _ = mgr._fill_form_impl("s1", "#name", "alice")
        ok_select, _ = mgr._select_option_impl("s1", "#country", "TR")
        ok_dom, dom = mgr.capture_dom("s1")

        assert ok_click is True
        assert ok_fill is True
        assert ok_select is True
        assert ok_dom is True
        assert "<div>dummy</div>" in dom

    def test_selenium_mocked_session_actions(self, tmp_path):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        fake_driver = types.SimpleNamespace(
            current_url="https://example.com",
            get=lambda _url: None,
            page_source="<html>selenium</html>",
            save_screenshot=lambda path: Path(path).write_bytes(b"png"),
            quit=lambda: None,
        )
        session = bm.BrowserSession(
            session_id="sel-1",
            provider="selenium",
            browser_name="chrome",
            headless=True,
            started_at=1.0,
            driver=fake_driver,
        )
        mgr._sessions["sel-1"] = session
        mgr.artifact_dir = tmp_path

        ok_go, _ = mgr.goto_url("sel-1", "https://example.com")
        ok_shot, shot_path = mgr.capture_screenshot("sel-1", file_name="s.png")
        ok_close, _ = mgr.close_session("sel-1")

        assert ok_go is True
        assert ok_shot is True
        assert Path(shot_path).exists()
        assert ok_close is True

    def test_start_playwright_session_uses_fully_mocked_playwright_runtime(self, monkeypatch):
        bm = _get_bm()
        mgr = bm.BrowserManager()

        class _FakePage:
            def __init__(self):
                self.timeout = None

            def set_default_timeout(self, timeout):
                self.timeout = timeout

        fake_page = _FakePage()
        fake_context = types.SimpleNamespace(new_page=lambda: fake_page)
        fake_browser = types.SimpleNamespace(new_context=lambda: fake_context)
        fake_launcher = types.SimpleNamespace(launch=lambda headless=True: fake_browser)
        fake_runtime = types.SimpleNamespace(chromium=fake_launcher, stop=lambda: None)

        class _FakeSyncPlaywright:
            def start(self):
                return fake_runtime

        fake_sync_api = types.SimpleNamespace(sync_playwright=lambda: _FakeSyncPlaywright())
        monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

        session = mgr._start_playwright_session("chromium", headless=True)
        assert session.provider == "playwright"
        assert session.browser_name == "chromium"
        assert session.page is fake_page
        assert fake_page.timeout == mgr.timeout_ms

    def test_start_selenium_session_uses_mocked_webdriver_classes(self, monkeypatch):
        bm = _get_bm()
        mgr = bm.BrowserManager()

        class _FakeChromeOptions:
            def __init__(self):
                self.args = []

            def add_argument(self, arg):
                self.args.append(arg)

        class _FakeDriver:
            def __init__(self, options=None):
                self.options = options
                self.page_timeout = None

            def set_page_load_timeout(self, value):
                self.page_timeout = value

        fake_webdriver = types.SimpleNamespace(
            ChromeOptions=_FakeChromeOptions,
            Chrome=lambda options=None: _FakeDriver(options=options),
        )
        monkeypatch.setitem(sys.modules, "selenium", types.SimpleNamespace(webdriver=fake_webdriver))

        session = mgr._start_selenium_session("chrome", headless=True)
        assert session.provider == "selenium"
        assert session.driver.page_timeout == max(5, mgr.timeout_ms // 1000)
        assert "--headless=new" in session.driver.options.args


class TestBrowserManagerFailureEdges:
    def test_goto_url_timeout_records_execution_failed_audit(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        session = bm.BrowserSession(
            session_id="timeout-1",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=1.0,
            page=types.SimpleNamespace(
                goto=lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("page load timeout")),
                url="https://example.com",
            ),
            current_url="",
        )
        mgr._sessions["timeout-1"] = session

        import pytest
        with pytest.raises(TimeoutError, match="page load timeout"):
            mgr.goto_url("timeout-1", "https://example.com")

        assert mgr._audit_log[-1]["action"] == "browser_goto_url"

    def test_capture_dom_when_selector_not_found_returns_false(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        session = bm.BrowserSession(
            session_id="dom-missing-1",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=1.0,
            page=types.SimpleNamespace(
                locator=lambda _selector: types.SimpleNamespace(
                    inner_html=lambda timeout=None: (_ for _ in ()).throw(RuntimeError("No node found for selector"))
                ),
                url="https://example.com",
            ),
        )
        mgr._sessions["dom-missing-1"] = session

        ok, message = mgr.capture_dom("dom-missing-1", "#missing")
        assert ok is False
        assert "DOM yakalama hatası" in message
        assert "No node found" in message

    def test_click_element_captcha_challenge_is_recorded_as_execution_failed(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        session = bm.BrowserSession(
            session_id="captcha-1",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=1.0,
            page=types.SimpleNamespace(
                click=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("CAPTCHA challenge detected")),
                url="https://example.com/login",
            ),
        )
        mgr._sessions["captcha-1"] = session

        import pytest
        with pytest.raises(RuntimeError, match="CAPTCHA"):
            mgr.click_element("captcha-1", "#login-submit")

        assert mgr._audit_log[-1]["action"] == "browser_click"
        assert mgr._audit_log[-1]["status"] == "execution_failed"
        assert mgr._audit_log[-1]["status"] == "execution_failed"

    def test_click_element_records_execution_failed_when_dom_missing(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        fake_page = types.SimpleNamespace(
            click=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("element not found: #missing")),
            url="https://example.com",
        )
        session = bm.BrowserSession(
            session_id="missing-1",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=1.0,
            page=fake_page,
        )
        mgr._sessions["missing-1"] = session

        import pytest
        with pytest.raises(RuntimeError, match="element not found"):
            mgr.click_element("missing-1", "#missing")

        assert mgr._audit_log[-1]["action"] == "browser_click"
        assert mgr._audit_log[-1]["status"] == "execution_failed"

    def test_fill_form_blocked_by_sync_hitl_guard_records_blocked_audit(self, monkeypatch):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        session = bm.BrowserSession(
            session_id="blocked-1",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=1.0,
            page=types.SimpleNamespace(url="https://example.com"),
        )
        mgr._sessions["blocked-1"] = session
        monkeypatch.setattr(mgr, "_sync_hitl_guard", lambda *_a, **_k: (False, "blocked by policy"))

        ok, message = mgr.fill_form("blocked-1", "#password", "secret", clear=True)
        assert ok is False
        assert "blocked by policy" in message
        assert mgr._audit_log[-1]["action"] == "browser_fill_form"
        assert mgr._audit_log[-1]["status"] == "blocked_hitl"

    def test_capture_dom_returns_false_when_selector_missing(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        fake_page = types.SimpleNamespace(
            locator=lambda _selector: types.SimpleNamespace(
                inner_html=lambda timeout=None: (_ for _ in ()).throw(RuntimeError("No node found"))
            ),
            url="https://example.com",
        )
        session = bm.BrowserSession(
            session_id="dom-err-1",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=1.0,
            page=fake_page,
        )
        mgr._sessions["dom-err-1"] = session

        ok, message = mgr.capture_dom("dom-err-1", selector="#does-not-exist")
        assert ok is False
        assert "DOM yakalama hatası" in message
        assert mgr._audit_log[-1]["action"] == "browser_capture_dom"
        assert mgr._audit_log[-1]["status"] == "execution_failed"

    def test_click_element_hitl_rejected_returns_block_message(self, monkeypatch):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        session = bm.BrowserSession(
            session_id="hitl-1",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=1.0,
            page=types.SimpleNamespace(url="https://example.com"),
        )
        mgr._sessions["hitl-1"] = session
        monkeypatch.setattr(mgr, "_request_hitl_approval", AsyncMock(return_value=False))
        monkeypatch.setattr(mgr, "_click_element_impl", lambda *_a, **_k: (True, "ok"))

        import asyncio
        ok, message = asyncio.run(mgr.click_element_hitl("hitl-1", "#publish-button"))
        assert ok is False
        assert "reddedildi" in message


class TestBrowserManagerUrlAndSessionValidation:
    def test_validate_url_rejects_non_http_scheme(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()

        import pytest
        with pytest.raises(ValueError, match="http/https"):
            mgr._validate_url("file:///tmp/x.html")

    def test_validate_url_rejects_disallowed_domain(self):
        bm = _get_bm()
        cfg = types.SimpleNamespace(
            BROWSER_PROVIDER="auto",
            BROWSER_HEADLESS=True,
            BROWSER_TIMEOUT_MS=15000,
            BROWSER_ALLOWED_DOMAINS=["example.com"],
        )
        mgr = bm.BrowserManager(config=cfg)

        import pytest
        with pytest.raises(ValueError, match="allowlist dışında"):
            mgr._validate_url("https://forbidden.test/page")

    def test_close_session_returns_not_found_for_unknown_session(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        ok, message = mgr.close_session("missing-session")
        assert ok is False
        assert "bulunamadı" in message.lower()


class TestBrowserManagerHitlAndProviderEdges:
    def test_click_element_hitl_exception_records_failed_audit(self, monkeypatch):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        session = bm.BrowserSession(
            session_id="hitl-err-1",
            provider="playwright",
            browser_name="chromium",
            headless=True,
            started_at=1.0,
            page=types.SimpleNamespace(url="https://example.com"),
        )
        mgr._sessions["hitl-err-1"] = session
        monkeypatch.setattr(mgr, "_request_hitl_approval", AsyncMock(return_value=True))
        monkeypatch.setattr(
            mgr,
            "_click_element_impl",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("element detached")),
        )

        import asyncio
        import pytest

        with pytest.raises(RuntimeError, match="element detached"):
            asyncio.run(mgr.click_element_hitl("hitl-err-1", "#publish"))

        assert mgr._audit_log[-1]["action"] == "browser_click"
        assert mgr._audit_log[-1]["status"] == "execution_failed"


class TestBrowserSeleniumFailureEdges:
    def test_goto_url_selenium_page_load_failure_records_execution_failed(self):
        bm = _get_bm()
        mgr = bm.BrowserManager()
        fake_driver = types.SimpleNamespace(
            current_url="",
            get=lambda _url: (_ for _ in ()).throw(RuntimeError("page load failed")),
        )
        session = bm.BrowserSession(
            session_id="sel-fail-1",
            provider="selenium",
            browser_name="chrome",
            headless=True,
            started_at=1.0,
            driver=fake_driver,
        )
        mgr._sessions["sel-fail-1"] = session

        import pytest
        with pytest.raises(RuntimeError, match="page load failed"):
            mgr.goto_url("sel-fail-1", "https://unreachable.example")

        assert mgr._audit_log[-1]["action"] == "browser_goto_url"
        assert mgr._audit_log[-1]["status"] == "execution_failed"
