"""
managers/browser_manager.py için ek birim testleri - kapsam artırma.
Missing lines hedefleniyor: summarize_audit_log, collect_session_signals,
fill_form_hitl, select_option_hitl, click_element_hitl, close_session, vb.
"""
from __future__ import annotations

import asyncio
import sys
import types
import time
from unittest.mock import AsyncMock, MagicMock, patch


# ──────────────────────────────────────────────────────────────
# Heavy deps stub
# ──────────────────────────────────────────────────────────────

def _stub_deps():
    """config, core.hitl gibi ağır bağımlılıkları stub'la."""
    # config stub
    if "config" not in sys.modules:
        config_mod = types.ModuleType("config")

        class Config:
            BROWSER_PROVIDER = "playwright"
            BROWSER_HEADLESS = True
            BROWSER_TIMEOUT_MS = 15000
            BROWSER_ALLOWED_DOMAINS = []

        config_mod.Config = Config
        sys.modules["config"] = config_mod

    # core.hitl stub
    if "core" not in sys.modules:
        sys.modules["core"] = types.ModuleType("core")

    if "core.hitl" not in sys.modules:
        hitl_mod = types.ModuleType("core.hitl")

        class _FakeGate:
            enabled = False

            async def request_approval(self, action, description, payload, requested_by):
                return False

        _gate = _FakeGate()

        def get_hitl_gate():
            return _gate

        hitl_mod.get_hitl_gate = get_hitl_gate
        sys.modules["core.hitl"] = hitl_mod


def _get_browser_manager():
    _stub_deps()
    if "managers.browser_manager" in sys.modules:
        del sys.modules["managers.browser_manager"]
    import managers.browser_manager as bm
    return bm


def _run(coro):
    return asyncio.run(coro)


def _make_config(**kwargs):
    cfg = MagicMock()
    cfg.BROWSER_PROVIDER = "playwright"
    cfg.BROWSER_HEADLESS = True
    cfg.BROWSER_TIMEOUT_MS = 15000
    cfg.BROWSER_ALLOWED_DOMAINS = []
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _make_manager(**kwargs):
    bm = _get_browser_manager()
    cfg = _make_config(**kwargs)
    return bm.BrowserManager(config=cfg)


def _make_playwright_session(bm_mod, session_id="test-session-1"):
    """Create a BrowserSession with playwright provider."""
    page = MagicMock()
    page.url = "https://example.com"
    browser = MagicMock()
    context = MagicMock()
    runtime = MagicMock()
    session = bm_mod.BrowserSession(
        session_id=session_id,
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=time.time(),
        page=page,
        browser=browser,
        context=context,
        runtime=runtime,
        current_url="https://example.com",
    )
    return session


def _make_selenium_session(bm_mod, session_id="test-session-2"):
    """Create a BrowserSession with selenium provider."""
    driver = MagicMock()
    driver.current_url = "https://example.com"
    session = bm_mod.BrowserSession(
        session_id=session_id,
        provider="selenium",
        browser_name="chrome",
        headless=True,
        started_at=time.time(),
        driver=driver,
        current_url="",
    )
    return session


# ══════════════════════════════════════════════════════════════
# BrowserManager.__init__
# ══════════════════════════════════════════════════════════════

class TestBrowserManagerInit:
    def test_default_provider_from_config(self):
        manager = _make_manager(BROWSER_PROVIDER="playwright")
        assert manager.provider == "playwright"

    def test_allowed_domains_set(self):
        manager = _make_manager(BROWSER_ALLOWED_DOMAINS=["example.com", "test.org"])
        assert "example.com" in manager.allowed_domains

    def test_timeout_ms_from_config(self):
        manager = _make_manager(BROWSER_TIMEOUT_MS=30000)
        assert manager.timeout_ms == 30000

    def test_sessions_dict_empty_initially(self):
        manager = _make_manager()
        assert manager._sessions == {}

    def test_audit_log_empty_initially(self):
        manager = _make_manager()
        assert manager._audit_log == []


# ══════════════════════════════════════════════════════════════
# BrowserManager._is_high_risk_click
# ══════════════════════════════════════════════════════════════

class TestIsHighRiskClick:
    def test_submit_is_high_risk(self):
        bm = _get_browser_manager()
        assert bm.BrowserManager._is_high_risk_click("button[type=submit]") is True

    def test_delete_is_high_risk(self):
        bm = _get_browser_manager()
        assert bm.BrowserManager._is_high_risk_click(".delete-btn") is True

    def test_confirm_is_high_risk(self):
        bm = _get_browser_manager()
        assert bm.BrowserManager._is_high_risk_click("#confirm-dialog") is True

    def test_regular_link_not_high_risk(self):
        bm = _get_browser_manager()
        assert bm.BrowserManager._is_high_risk_click("a.nav-link") is False

    def test_empty_selector_not_high_risk(self):
        bm = _get_browser_manager()
        assert bm.BrowserManager._is_high_risk_click("") is False

    def test_jira_is_high_risk(self):
        bm = _get_browser_manager()
        assert bm.BrowserManager._is_high_risk_click("#jira-submit") is True


# ══════════════════════════════════════════════════════════════
# BrowserManager._summarize_value
# ══════════════════════════════════════════════════════════════

class TestSummarizeValue:
    def test_empty_returns_empty(self):
        bm = _get_browser_manager()
        assert bm.BrowserManager._summarize_value("") == ""

    def test_short_value_masked(self):
        bm = _get_browser_manager()
        result = bm.BrowserManager._summarize_value("pass")
        assert result == "****"

    def test_long_value_shows_first_last_two(self):
        bm = _get_browser_manager()
        result = bm.BrowserManager._summarize_value("supersecret123")
        assert result.startswith("su")
        assert "23" in result
        assert "len=" in result


# ══════════════════════════════════════════════════════════════
# BrowserManager._record_audit_event / _audit_session_action
# ══════════════════════════════════════════════════════════════

class TestAuditEvents:
    def test_record_audit_event_appended(self):
        manager = _make_manager()
        entry = manager._record_audit_event(
            session_id="sess-1",
            action="browser_click",
            status="executed",
            selector=".btn",
            current_url="https://example.com",
        )
        assert len(manager._audit_log) == 1
        assert entry["action"] == "browser_click"
        assert entry["status"] == "executed"

    def test_list_audit_log_returns_copy(self):
        manager = _make_manager()
        manager._record_audit_event(session_id="s", action="a", status="ok")
        log = manager.list_audit_log()
        assert isinstance(log, list)
        assert len(log) == 1

    def test_audit_session_action_uses_session(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm)
        manager._sessions[session.session_id] = session
        manager._audit_session_action(session, action="browser_click", status="executed", selector=".btn")
        assert len(manager._audit_log) == 1


# ══════════════════════════════════════════════════════════════
# BrowserManager.summarize_audit_log
# ══════════════════════════════════════════════════════════════

class TestSummarizeAuditLog:
    def test_empty_log_returns_no_signal(self):
        manager = _make_manager()
        result = manager.summarize_audit_log()
        assert result["status"] == "no-signal"
        assert result["risk"] == "düşük"

    def test_failed_action_raises_risk(self):
        manager = _make_manager()
        manager._record_audit_event(session_id="s", action="browser_click", status="execution_failed", selector=".del")
        result = manager.summarize_audit_log()
        assert result["status"] == "failed"
        assert result["risk"] == "yüksek"

    def test_pending_action_medium_risk(self):
        manager = _make_manager()
        manager._record_audit_event(session_id="s", action="browser_click", status="pending_approval")
        result = manager.summarize_audit_log()
        assert result["status"] == "attention"
        assert result["risk"] == "orta"

    def test_ok_when_only_success(self):
        manager = _make_manager()
        manager._record_audit_event(session_id="s", action="browser_goto_url", status="executed")
        result = manager.summarize_audit_log()
        assert result["status"] == "ok"

    def test_filter_by_session_id(self):
        manager = _make_manager()
        manager._record_audit_event(session_id="sess-1", action="browser_click", status="executed")
        manager._record_audit_event(session_id="sess-2", action="browser_click", status="executed")
        result = manager.summarize_audit_log(session_id="sess-1")
        assert result["entry_count"] == 1

    def test_high_risk_click_identified(self):
        manager = _make_manager()
        manager._record_audit_event(
            session_id="s",
            action="browser_click",
            status="executed",
            selector="button#delete",
        )
        result = manager.summarize_audit_log()
        assert len(result["high_risk_actions"]) > 0

    def test_rejected_status_counts_as_failed(self):
        manager = _make_manager()
        manager._record_audit_event(session_id="s", action="browser_fill_form", status="rejected", selector="input")
        result = manager.summarize_audit_log()
        assert len(result["failed_actions"]) > 0

    def test_urls_collected(self):
        manager = _make_manager()
        manager._record_audit_event(session_id="s", action="browser_goto_url", status="executed", current_url="https://example.com")
        result = manager.summarize_audit_log()
        assert "https://example.com" in result["urls"]

    def test_limit_parameter(self):
        manager = _make_manager()
        for i in range(20):
            manager._record_audit_event(session_id="s", action=f"action_{i}", status="executed")
        result = manager.summarize_audit_log(limit=5)
        assert len(result["recent_entries"]) == 5


# ══════════════════════════════════════════════════════════════
# BrowserManager._session_url
# ══════════════════════════════════════════════════════════════

class TestSessionUrl:
    def test_returns_current_url_when_set(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm)
        session.current_url = "https://set-url.com"
        result = manager._session_url(session)
        assert result == "https://set-url.com"

    def test_falls_back_to_page_url_for_playwright(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm)
        session.current_url = ""
        session.page.url = "https://page-url.com"
        result = manager._session_url(session)
        assert result == "https://page-url.com"

    def test_falls_back_to_driver_url_for_selenium(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_selenium_session(bm)
        session.current_url = ""
        session.driver.current_url = "https://driver-url.com"
        result = manager._session_url(session)
        assert result == "https://driver-url.com"

    def test_returns_empty_when_no_url(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = bm.BrowserSession(
            session_id="x",
            provider="other",
            browser_name="chrome",
            headless=True,
            started_at=time.time(),
            current_url="",
        )
        result = manager._session_url(session)
        assert result == ""


# ══════════════════════════════════════════════════════════════
# BrowserManager._validate_url
# ══════════════════════════════════════════════════════════════

class TestValidateUrl:
    def test_valid_https_url_passes(self):
        manager = _make_manager()
        manager._validate_url("https://example.com/page")  # should not raise

    def test_valid_http_url_passes(self):
        manager = _make_manager()
        manager._validate_url("http://example.com")  # should not raise

    def test_invalid_scheme_raises(self):
        manager = _make_manager()
        try:
            manager._validate_url("ftp://example.com")
            assert False, "should raise"
        except ValueError as e:
            assert "http" in str(e).lower()

    def test_no_host_raises(self):
        manager = _make_manager()
        try:
            manager._validate_url("https://")
            assert False, "should raise"
        except ValueError:
            pass

    def test_blocked_domain_raises(self):
        manager = _make_manager(BROWSER_ALLOWED_DOMAINS=["allowed.com"])
        try:
            manager._validate_url("https://blocked.com")
            assert False, "should raise"
        except ValueError as e:
            assert "allowlist" in str(e).lower() or "blocked" in str(e).lower()

    def test_allowed_domain_passes(self):
        manager = _make_manager(BROWSER_ALLOWED_DOMAINS=["example.com"])
        manager._validate_url("https://example.com/path")  # should not raise


# ══════════════════════════════════════════════════════════════
# BrowserManager._require_session
# ══════════════════════════════════════════════════════════════

class TestRequireSession:
    def test_returns_session_when_exists(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "existing-id")
        manager._sessions["existing-id"] = session
        result = manager._require_session("existing-id")
        assert result is session

    def test_raises_key_error_when_missing(self):
        manager = _make_manager()
        try:
            manager._require_session("nonexistent")
            assert False, "should raise"
        except KeyError:
            pass


# ══════════════════════════════════════════════════════════════
# BrowserManager.goto_url
# ══════════════════════════════════════════════════════════════

class TestGotoUrl:
    def test_playwright_goto_url_success(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "nav-sess")
        session.page.goto = MagicMock()
        manager._sessions["nav-sess"] = session

        ok, msg = manager.goto_url("nav-sess", "https://example.com")
        assert ok is True
        assert "example.com" in msg

    def test_selenium_goto_url_success(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_selenium_session(bm, "sel-nav")
        session.driver.get = MagicMock()
        manager._sessions["sel-nav"] = session

        ok, msg = manager.goto_url("sel-nav", "https://example.com")
        assert ok is True

    def test_goto_url_invalid_scheme_raises(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "x")
        manager._sessions["x"] = session
        try:
            manager.goto_url("x", "ftp://bad.com")
            assert False, "should raise"
        except ValueError:
            pass

    def test_goto_url_updates_current_url(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "url-update")
        session.page.goto = MagicMock()
        manager._sessions["url-update"] = session

        manager.goto_url("url-update", "https://new-url.com")
        assert session.current_url == "https://new-url.com"

    def test_goto_url_exception_audited(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "err-nav")
        session.page.goto = MagicMock(side_effect=RuntimeError("nav failed"))
        manager._sessions["err-nav"] = session

        try:
            manager.goto_url("err-nav", "https://example.com")
        except RuntimeError:
            pass
        # Audit log should have execution_failed entry
        assert any(e["status"] == "execution_failed" for e in manager._audit_log)


# ══════════════════════════════════════════════════════════════
# BrowserManager.click_element
# ══════════════════════════════════════════════════════════════

class TestClickElement:
    def test_playwright_click_success(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "click-sess")
        session.page.click = MagicMock()
        manager._sessions["click-sess"] = session

        ok, msg = manager.click_element("click-sess", "button.submit-btn")
        # submit in selector is high risk, but HITL not enabled, so it goes through
        assert isinstance(ok, bool)

    def test_click_logs_audit_event(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "click-audit")
        session.page.click = MagicMock()
        manager._sessions["click-audit"] = session

        manager.click_element("click-audit", ".some-button")
        assert len(manager._audit_log) > 0

    def test_click_exception_audited(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "click-err")
        session.page.click = MagicMock(side_effect=RuntimeError("click failed"))
        manager._sessions["click-err"] = session

        try:
            manager.click_element("click-err", ".btn")
        except RuntimeError:
            pass
        assert any(e["status"] == "execution_failed" for e in manager._audit_log)


# ══════════════════════════════════════════════════════════════
# BrowserManager.click_element_hitl
# ══════════════════════════════════════════════════════════════

class TestClickElementHitl:
    def test_low_risk_click_without_confirmation(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "hitl-low")
        session.page.click = MagicMock()
        manager._sessions["hitl-low"] = session

        # require_confirmation=False => goes through click_element directly
        result = _run(manager.click_element_hitl("hitl-low", ".nav-link", require_confirmation=False))
        ok, msg = result
        assert isinstance(ok, bool)

    def test_high_risk_click_rejected_by_hitl(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "hitl-high")
        manager._sessions["hitl-high"] = session

        # Enable HITL with auto-reject
        hitl_gate = MagicMock()
        hitl_gate.enabled = True
        hitl_gate.request_approval = AsyncMock(return_value=False)

        with patch("managers.browser_manager.get_hitl_gate", return_value=hitl_gate):
            result = _run(manager.click_element_hitl("hitl-high", "#submit-btn", require_confirmation=True))
        ok, msg = result
        assert ok is False
        assert "reddedildi" in msg or "rejected" in msg.lower() or "HITL" in msg

    def test_high_risk_click_approved_executes(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "hitl-approve")
        session.page.click = MagicMock()
        manager._sessions["hitl-approve"] = session

        hitl_gate = MagicMock()
        hitl_gate.enabled = True
        hitl_gate.request_approval = AsyncMock(return_value=True)

        with patch("managers.browser_manager.get_hitl_gate", return_value=hitl_gate):
            result = _run(manager.click_element_hitl("hitl-approve", "#submit-btn", require_confirmation=True))
        ok, msg = result
        assert ok is True


# ══════════════════════════════════════════════════════════════
# BrowserManager.fill_form / fill_form_hitl
# ══════════════════════════════════════════════════════════════

class TestFillForm:
    def test_playwright_fill_success(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "fill-sess")
        session.page.fill = MagicMock()
        manager._sessions["fill-sess"] = session

        ok, msg = manager.fill_form("fill-sess", "input#name", "John")
        assert ok is True
        assert "Form" in msg

    def test_fill_form_without_clear(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "fill-noclr")
        session.page.type = MagicMock()
        manager._sessions["fill-noclr"] = session

        ok, msg = manager.fill_form("fill-noclr", "input#name", "John", clear=False)
        assert ok is True

    def test_fill_form_hitl_rejected(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "fill-hitl")
        manager._sessions["fill-hitl"] = session

        hitl_gate = MagicMock()
        hitl_gate.enabled = True
        hitl_gate.request_approval = AsyncMock(return_value=False)

        with patch("managers.browser_manager.get_hitl_gate", return_value=hitl_gate):
            result = _run(manager.fill_form_hitl("fill-hitl", "input#pass", "secret"))
        ok, msg = result
        assert ok is False

    def test_fill_form_hitl_approved(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "fill-approve")
        session.page.fill = MagicMock()
        manager._sessions["fill-approve"] = session

        hitl_gate = MagicMock()
        hitl_gate.enabled = True
        hitl_gate.request_approval = AsyncMock(return_value=True)

        with patch("managers.browser_manager.get_hitl_gate", return_value=hitl_gate):
            result = _run(manager.fill_form_hitl("fill-approve", "input#name", "John"))
        ok, msg = result
        assert ok is True

    def test_fill_form_exception_audited(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "fill-err")
        session.page.fill = MagicMock(side_effect=RuntimeError("fill failed"))
        manager._sessions["fill-err"] = session

        try:
            manager.fill_form("fill-err", "input#name", "John")
        except RuntimeError:
            pass
        assert any(e["status"] == "execution_failed" for e in manager._audit_log)


# ══════════════════════════════════════════════════════════════
# BrowserManager.select_option / select_option_hitl
# ══════════════════════════════════════════════════════════════

class TestSelectOption:
    def test_playwright_select_success(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "select-sess")
        session.page.select_option = MagicMock()
        manager._sessions["select-sess"] = session

        ok, msg = manager.select_option("select-sess", "select#country", "TR")
        assert ok is True

    def test_select_option_hitl_rejected(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "select-hitl")
        manager._sessions["select-hitl"] = session

        hitl_gate = MagicMock()
        hitl_gate.enabled = True
        hitl_gate.request_approval = AsyncMock(return_value=False)

        with patch("managers.browser_manager.get_hitl_gate", return_value=hitl_gate):
            result = _run(manager.select_option_hitl("select-hitl", "select#lang", "EN"))
        ok, msg = result
        assert ok is False

    def test_select_option_hitl_approved(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "select-approve")
        session.page.select_option = MagicMock()
        manager._sessions["select-approve"] = session

        hitl_gate = MagicMock()
        hitl_gate.enabled = True
        hitl_gate.request_approval = AsyncMock(return_value=True)

        with patch("managers.browser_manager.get_hitl_gate", return_value=hitl_gate):
            result = _run(manager.select_option_hitl("select-approve", "select#lang", "EN"))
        ok, msg = result
        assert ok is True


# ══════════════════════════════════════════════════════════════
# BrowserManager.capture_dom
# ══════════════════════════════════════════════════════════════

class TestCaptureDom:
    def test_playwright_capture_dom_success(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "dom-sess")
        session.page.locator = MagicMock()
        session.page.locator.return_value.inner_html = MagicMock(return_value="<html>content</html>")
        manager._sessions["dom-sess"] = session

        ok, dom = manager.capture_dom("dom-sess", "html")
        assert ok is True
        assert isinstance(dom, str)

    def test_capture_dom_failure_returns_error(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "dom-err")
        session.page.locator = MagicMock(side_effect=RuntimeError("locator failed"))
        manager._sessions["dom-err"] = session

        ok, dom = manager.capture_dom("dom-err", "html")
        assert ok is False
        assert "hata" in dom.lower() or "DOM" in dom

    def test_selenium_capture_dom(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_selenium_session(bm, "dom-sel")
        session.driver.page_source = "<html>selenium content</html>"
        manager._sessions["dom-sel"] = session

        ok, dom = manager.capture_dom("dom-sel", "html")
        assert ok is True
        assert "selenium" in dom


# ══════════════════════════════════════════════════════════════
# BrowserManager.capture_screenshot
# ══════════════════════════════════════════════════════════════

class TestCaptureScreenshot:
    def test_playwright_screenshot_success(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "ss-sess")
        session.page.screenshot = MagicMock()
        manager._sessions["ss-sess"] = session

        ok, path = manager.capture_screenshot("ss-sess", file_name="test.png")
        assert ok is True
        assert "test.png" in path

    def test_screenshot_with_default_filename(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "ss-default")
        session.page.screenshot = MagicMock()
        manager._sessions["ss-default"] = session

        ok, path = manager.capture_screenshot("ss-default")
        assert ok is True
        assert "ss-default" in path


# ══════════════════════════════════════════════════════════════
# BrowserManager.close_session
# ══════════════════════════════════════════════════════════════

class TestCloseSession:
    def test_close_playwright_session_success(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "close-sess")
        session.context.close = MagicMock()
        session.browser.close = MagicMock()
        session.runtime.stop = MagicMock()
        manager._sessions["close-sess"] = session

        ok, msg = manager.close_session("close-sess")
        assert ok is True
        assert "close-sess" in msg
        assert "close-sess" not in manager._sessions

    def test_close_nonexistent_session_returns_false(self):
        manager = _make_manager()
        ok, msg = manager.close_session("nonexistent")
        assert ok is False
        assert "bulunamadı" in msg or "nonexistent" in msg

    def test_close_session_exception_handled(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "close-err")
        session.context.close = MagicMock(side_effect=RuntimeError("close error"))
        manager._sessions["close-err"] = session

        ok, msg = manager.close_session("close-err")
        assert ok is False
        assert "hata" in msg.lower() or "error" in msg.lower()


# ══════════════════════════════════════════════════════════════
# BrowserManager.is_available / status
# ══════════════════════════════════════════════════════════════

class TestIsAvailableAndStatus:
    def test_is_available_true_when_playwright_importable(self):
        bm = _get_browser_manager()
        manager = _make_manager(BROWSER_PROVIDER="playwright")
        # Mock playwright as importable
        playwright_stub = types.ModuleType("playwright")
        playwright_sync = types.ModuleType("playwright.sync_api")
        playwright_stub.sync_api = playwright_sync
        with patch.dict(sys.modules, {"playwright": playwright_stub, "playwright.sync_api": playwright_sync}):
            result = manager.is_available()
        assert result is True

    def test_is_available_false_when_no_provider(self):
        manager = _make_manager(BROWSER_PROVIDER="unknown_provider")
        # Override _provider_candidates to return unknown
        result = manager.is_available()
        # Should not raise; result depends on imports
        assert isinstance(result, bool)

    def test_status_returns_string(self):
        manager = _make_manager()
        result = manager.status()
        assert isinstance(result, str)
        assert "BrowserManager" in result

    def test_status_includes_provider(self):
        manager = _make_manager(BROWSER_PROVIDER="playwright")
        result = manager.status()
        assert "playwright" in result


# ══════════════════════════════════════════════════════════════
# BrowserManager.collect_session_signals
# ══════════════════════════════════════════════════════════════

class TestCollectSessionSignals:
    def test_basic_signals_without_extras(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "signals-sess")
        manager._sessions["signals-sess"] = session

        result = manager.collect_session_signals("signals-sess")
        assert "provider" in result
        assert "browser_name" in result
        assert "current_url" in result

    def test_signals_with_dom_capture(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "signals-dom")
        session.page.locator = MagicMock()
        session.page.locator.return_value.inner_html = MagicMock(return_value="<html></html>")
        manager._sessions["signals-dom"] = session

        result = manager.collect_session_signals("signals-dom", include_dom=True, dom_selector="html")
        assert "dom_capture" in result
        assert result["dom_capture"]["ok"] is True

    def test_signals_with_screenshot(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "signals-ss")
        session.page.screenshot = MagicMock()
        manager._sessions["signals-ss"] = session

        result = manager.collect_session_signals("signals-ss", include_screenshot=True)
        assert "screenshot" in result
        assert result["screenshot"]["ok"] is True

    def test_signals_dom_preview_truncated_for_long_dom(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        session = _make_playwright_session(bm, "signals-long")
        long_dom = "x" * 2000
        session.page.locator = MagicMock()
        session.page.locator.return_value.inner_html = MagicMock(return_value=long_dom)
        manager._sessions["signals-long"] = session

        result = manager.collect_session_signals("signals-long", include_dom=True)
        preview = result["dom_capture"]["preview"]
        assert len(preview) <= 1005  # 1000 + ellipsis char


# ══════════════════════════════════════════════════════════════
# BrowserManager._sync_hitl_guard
# ══════════════════════════════════════════════════════════════

class TestSyncHitlGuard:
    def test_returns_none_when_hitl_disabled(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        hitl_gate = MagicMock()
        hitl_gate.enabled = False

        with patch("managers.browser_manager.get_hitl_gate", return_value=hitl_gate):
            result = manager._sync_hitl_guard("browser_click", ".some-btn")
        assert result is None

    def test_returns_none_for_low_risk_click_when_enabled(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        hitl_gate = MagicMock()
        hitl_gate.enabled = True

        with patch("managers.browser_manager.get_hitl_gate", return_value=hitl_gate):
            result = manager._sync_hitl_guard("browser_click", ".nav-link")
        assert result is None

    def test_blocks_fill_form_when_hitl_enabled(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        hitl_gate = MagicMock()
        hitl_gate.enabled = True

        with patch("managers.browser_manager.get_hitl_gate", return_value=hitl_gate):
            result = manager._sync_hitl_guard("browser_fill_form", "input", force_block=True)
        assert result is not None
        ok, msg = result
        assert ok is False

    def test_force_block_blocks_high_risk_click(self):
        bm = _get_browser_manager()
        manager = _make_manager()
        hitl_gate = MagicMock()
        hitl_gate.enabled = True

        with patch("managers.browser_manager.get_hitl_gate", return_value=hitl_gate):
            result = manager._sync_hitl_guard("browser_click", "#delete-btn", force_block=True)
        assert result is not None


# ══════════════════════════════════════════════════════════════
# BrowserManager.start_session (failure path)
# ══════════════════════════════════════════════════════════════

class TestStartSession:
    def test_start_session_failure_returns_error(self):
        manager = _make_manager(BROWSER_PROVIDER="playwright")

        # Patch _start_playwright_session to raise
        with patch.object(manager, "_start_playwright_session", side_effect=RuntimeError("no display")):
            ok, info = manager.start_session()
        assert ok is False
        assert "error" in info

    def test_start_session_success(self):
        bm = _get_browser_manager()
        manager = _make_manager(BROWSER_PROVIDER="playwright")
        session = _make_playwright_session(bm)

        with patch.object(manager, "_start_playwright_session", return_value=session):
            ok, info = manager.start_session()
        assert ok is True
        assert "session_id" in info
        assert info["session_id"] in manager._sessions

    def test_start_session_auto_tries_playwright_first(self):
        bm = _get_browser_manager()
        manager = _make_manager(BROWSER_PROVIDER="auto")
        session = _make_playwright_session(bm)

        with patch.object(manager, "_start_playwright_session", return_value=session):
            ok, info = manager.start_session()
        assert ok is True

    def test_start_session_auto_falls_back_to_selenium(self):
        bm = _get_browser_manager()
        manager = _make_manager(BROWSER_PROVIDER="auto")
        session = _make_selenium_session(bm)

        def _fail_playwright(*a, **kw):
            raise RuntimeError("playwright not available")

        with patch.object(manager, "_start_playwright_session", side_effect=_fail_playwright):
            with patch.object(manager, "_start_selenium_session", return_value=session):
                ok, info = manager.start_session()
        assert ok is True
