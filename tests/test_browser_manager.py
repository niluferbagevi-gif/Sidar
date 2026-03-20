import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_browser_manager_module():
    spec = importlib.util.spec_from_file_location(
        "browser_manager_test_mod",
        Path("managers/browser_manager.py"),
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BM_MOD = _load_browser_manager_module()


class _Config:
    BROWSER_PROVIDER = "playwright"
    BROWSER_HEADLESS = True
    BROWSER_TIMEOUT_MS = 5000
    BROWSER_ALLOWED_DOMAINS = ["example.com"]


def test_browser_manager_playwright_flow(monkeypatch, tmp_path):
    manager = BM_MOD.BrowserManager(_Config())
    manager.artifact_dir = tmp_path
    calls = []

    class _Locator:
        def inner_html(self, timeout):
            calls.append(("inner_html", timeout))
            return "<main>ok</main>"

    class _Page:
        def goto(self, url, wait_until, timeout):
            calls.append(("goto", url, wait_until, timeout))

        def click(self, selector, timeout):
            calls.append(("click", selector, timeout))

        def fill(self, selector, value, timeout):
            calls.append(("fill", selector, value, timeout))

        def select_option(self, selector, value, timeout):
            calls.append(("select", selector, value, timeout))

        def locator(self, selector):
            calls.append(("locator", selector))
            return _Locator()

        def screenshot(self, path, full_page):
            Path(path).write_bytes(b"png")
            calls.append(("screenshot", path, full_page))

    class _Closable:
        def __init__(self, label):
            self.label = label

        def close(self):
            calls.append(("close", self.label))

    runtime = SimpleNamespace(stop=lambda: calls.append(("stop", "runtime")))
    fake_session = BM_MOD.BrowserSession(
        session_id="sess-1",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
        browser=_Closable("browser"),
        context=_Closable("context"),
        runtime=runtime,
    )

    monkeypatch.setattr(manager, "_start_playwright_session", lambda *_args, **_kwargs: fake_session)

    ok, payload = manager.start_session()
    assert ok is True
    assert payload["session_id"] == "sess-1"

    assert manager.goto_url("sess-1", "https://example.com")[0] is True
    assert manager.click_element("sess-1", "#submit")[0] is True
    assert manager.fill_form("sess-1", "#name", "Sidar")[0] is True
    assert manager.select_option("sess-1", "#priority", "high")[0] is True

    ok, dom = manager.capture_dom("sess-1")
    assert ok is True
    assert "<main>ok</main>" == dom

    ok, screenshot_path = manager.capture_screenshot("sess-1", "page.png")
    assert ok is True
    assert Path(screenshot_path).exists()

    ok, message = manager.close_session("sess-1")
    assert ok is True
    assert "kapatıldı" in message
    audit_actions = [(entry["action"], entry["status"]) for entry in manager.list_audit_log()]
    assert ("browser_start_session", "started") in audit_actions
    assert ("browser_goto_url", "executed") in audit_actions
    assert ("browser_capture_screenshot", "executed") in audit_actions
    assert ("browser_close_session", "executed") in audit_actions
    assert ("goto", "https://example.com", "domcontentloaded", 5000) in calls
    assert ("close", "context") in calls
    assert ("close", "browser") in calls
    assert ("stop", "runtime") in calls


def test_browser_manager_rejects_urls_outside_allowlist():
    manager = BM_MOD.BrowserManager(_Config())

    with pytest.raises(ValueError):
        manager._validate_url("https://openai.com")


def test_browser_manager_high_risk_actions_require_hitl_and_write_audit(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    calls = []

    class _Page:
        def click(self, selector, timeout):
            calls.append(("click", selector, timeout))

        def fill(self, selector, value, timeout):
            calls.append(("fill", selector, value, timeout))

        def select_option(self, selector, value, timeout):
            calls.append(("select", selector, value, timeout))

    session = BM_MOD.BrowserSession(
        session_id="sess-hitl",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
        current_url="https://example.com/jira/issue/SID-1",
    )
    manager._sessions[session.session_id] = session

    approvals = []

    class _Gate:
        async def request_approval(self, **kwargs):
            approvals.append(kwargs)
            return True

    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: _Gate())

    ok_click, _ = asyncio.run(
        manager.click_element_hitl(session.session_id, "button[type='submit']", reason="Jira issue güncelle")
    )
    ok_fill, _ = asyncio.run(
        manager.fill_form_hitl(session.session_id, "#summary", "Yeni özet", reason="Issue alanı güncelle")
    )
    ok_select, _ = asyncio.run(
        manager.select_option_hitl(session.session_id, "#priority", "high", reason="Öncelik değiştir")
    )

    assert ok_click is True
    assert ok_fill is True
    assert ok_select is True
    assert len(approvals) == 3
    assert approvals[0]["action"] == "browser_click"
    assert approvals[1]["payload"]["value_preview"].endswith(f"(len={len('Yeni özet')})")
    assert ("click", "button[type='submit']", 5000) in calls
    assert ("fill", "#summary", "Yeni özet", 5000) in calls
    assert ("select", "#priority", "high", 5000) in calls

    audit_log = manager.list_audit_log()
    assert [entry["status"] for entry in audit_log] == [
        "pending_approval",
        "approved",
        "executed",
        "pending_approval",
        "approved",
        "executed",
        "pending_approval",
        "approved",
        "executed",
    ]


def test_browser_manager_collects_structured_session_signals(monkeypatch, tmp_path):
    manager = BM_MOD.BrowserManager(_Config())
    manager.artifact_dir = tmp_path

    class _Locator:
        def inner_html(self, timeout):
            assert timeout == 5000
            return "<main>browser state</main>"

    class _Page:
        def locator(self, selector):
            assert selector == "html"
            return _Locator()

        def screenshot(self, path, full_page):
            Path(path).write_bytes(b"png")

    session = BM_MOD.BrowserSession(
        session_id="sess-signals",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
        current_url="https://example.com/issues/1",
    )
    manager._sessions[session.session_id] = session
    manager._record_audit_event(
        session_id=session.session_id,
        action="browser_click",
        status="execution_failed",
        selector="button[type='submit']",
        current_url=session.current_url,
    )

    signal = manager.collect_session_signals(
        session.session_id,
        include_dom=True,
        include_screenshot=True,
    )

    assert signal["status"] == "failed"
    assert signal["risk"] == "yüksek"
    assert signal["current_url"] == "https://example.com/issues/1"
    assert signal["failed_actions"] == ["browser_click:button[type='submit']"]
    assert signal["dom_capture"]["preview"] == "<main>browser state</main>"
    assert Path(signal["screenshot"]["path"]).exists()


def test_browser_manager_hitl_rejection_blocks_execution(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    calls = []

    class _Page:
        def click(self, selector, timeout):
            calls.append(("click", selector, timeout))

    session = BM_MOD.BrowserSession(
        session_id="sess-reject",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
        current_url="https://example.com/jira/issue/SID-2",
    )
    manager._sessions[session.session_id] = session

    class _Gate:
        async def request_approval(self, **kwargs):
            return False

    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: _Gate())

    ok, msg = asyncio.run(manager.click_element_hitl(session.session_id, "button[type='submit']"))

    assert ok is False
    assert "reddedildi" in msg
    assert calls == []
    assert [entry["status"] for entry in manager.list_audit_log()] == ["pending_approval", "rejected"]


def test_browser_manager_blocks_sync_mutations_when_hitl_enabled(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    manager._sessions["sess-guard"] = BM_MOD.BrowserSession(
        session_id="sess-guard",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=SimpleNamespace(click=lambda *_a, **_k: None, fill=lambda *_a, **_k: None, select_option=lambda *_a, **_k: None),
    )

    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: SimpleNamespace(enabled=True))

    ok_click, msg_click = manager.click_element("sess-guard", "button[type='submit']")
    ok_fill, msg_fill = manager.fill_form("sess-guard", "#summary", "demo")
    ok_select, msg_select = manager.select_option("sess-guard", "#priority", "high")

    assert ok_click is False and "click_element_hitl" in msg_click
    assert ok_fill is False and "fill_form_hitl" in msg_fill
    assert ok_select is False and "select_option_hitl" in msg_select
    assert [entry["status"] for entry in manager.list_audit_log()] == [
        "blocked_hitl",
        "blocked_hitl",
        "blocked_hitl",
    ]


def test_browser_manager_helper_methods_cover_non_happy_paths(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())

    assert manager._is_high_risk_click("button.save") is True
    assert manager._is_high_risk_click("a.learn-more") is False
    assert manager._summarize_value("") == ""
    assert manager._summarize_value("short") == "*****"
    assert manager._summarize_value("abcdefghijkl") == "ab***kl (len=12)"

    session = BM_MOD.BrowserSession(
        session_id="selenium-1",
        provider="selenium",
        browser_name="chrome",
        headless=True,
        started_at=0.0,
        driver=SimpleNamespace(current_url="https://example.com/dashboard"),
    )
    assert manager._session_url(session) == "https://example.com/dashboard"

    with pytest.raises(KeyError):
        manager._require_session("missing")

    monkeypatch.setattr(manager, "is_available", lambda: True)
    status = manager.status()
    assert "available=yes" in status
    assert "active_sessions=0" in status


def test_browser_manager_click_hitl_can_skip_confirmation_for_low_risk(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    calls = []
    session = BM_MOD.BrowserSession(
        session_id="sess-low-risk",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=SimpleNamespace(click=lambda selector, timeout: calls.append((selector, timeout))),
        current_url="https://example.com/docs",
    )
    manager._sessions[session.session_id] = session

    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: SimpleNamespace(enabled=True))

    ok, message = asyncio.run(manager.click_element_hitl(session.session_id, "a.learn-more", require_confirmation=False))

    assert ok is True
    assert "Tıklandı" in message
    assert calls == [("a.learn-more", 5000)]


def test_browser_manager_close_session_returns_error_when_cleanup_fails():
    manager = BM_MOD.BrowserManager(_Config())

    class _BrokenContext:
        def close(self):
            raise RuntimeError("kapatılamadı")

    manager._sessions["sess-broken"] = BM_MOD.BrowserSession(
        session_id="sess-broken",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        context=_BrokenContext(),
        browser=SimpleNamespace(close=lambda: None),
        runtime=SimpleNamespace(stop=lambda: None),
    )

    ok, message = manager.close_session("sess-broken")

    assert ok is False
    assert "kapatılırken hata" in message
    assert manager.list_audit_log()[-1]["status"] == "execution_failed"
