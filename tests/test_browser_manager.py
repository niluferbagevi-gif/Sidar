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

def test_browser_manager_summarize_audit_log_attention_and_no_signal():
    manager = BM_MOD.BrowserManager(_Config())

    no_signal = manager.summarize_audit_log()
    assert no_signal["status"] == "no-signal"
    assert no_signal["risk"] == "düşük"

    manager._record_audit_event(
        session_id="sess-attn",
        action="browser_click",
        status="pending_approval",
        selector="button.save",
        current_url="https://example.com/settings",
    )
    manager._record_audit_event(
        session_id="sess-attn",
        action="browser_click",
        status="approved",
        selector="button.save",
        current_url="https://example.com/settings",
    )

    attention = manager.summarize_audit_log("sess-attn")
    assert attention["status"] == "attention"
    assert attention["risk"] == "orta"
    assert attention["pending_actions"] == ["browser_click"]
    assert attention["high_risk_actions"] == ["browser_click:button.save"]


def test_browser_manager_start_playwright_session_uses_mocked_runtime(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    calls = []

    class _Page:
        def __init__(self):
            self.timeout = None

        def set_default_timeout(self, timeout):
            self.timeout = timeout
            calls.append(("set_default_timeout", timeout))

    class _Context:
        def __init__(self):
            self.page = _Page()

        def new_page(self):
            calls.append(("new_page",))
            return self.page

    class _Browser:
        def __init__(self):
            self.context = _Context()

        def new_context(self):
            calls.append(("new_context",))
            return self.context

    class _Launcher:
        def launch(self, *, headless):
            calls.append(("launch", headless))
            return _Browser()

    class _Runtime:
        chromium = _Launcher()

        def stop(self):
            calls.append(("stop",))

    class _PlaywrightHandle:
        def start(self):
            calls.append(("start",))
            return _Runtime()

    sync_api_mod = SimpleNamespace(sync_playwright=lambda: _PlaywrightHandle())
    monkeypatch.setitem(sys.modules, "playwright", SimpleNamespace(sync_api=sync_api_mod))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api_mod)

    session = manager._start_playwright_session("chromium", headless=False)

    assert session.provider == "playwright"
    assert session.browser_name == "chromium"
    assert session.headless is False
    assert session.page.timeout == 5000
    assert ("start",) in calls
    assert ("launch", False) in calls
    assert ("new_context",) in calls
    assert ("new_page",) in calls


def test_browser_manager_start_playwright_session_stops_runtime_for_unknown_browser(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    calls = []

    class _Runtime:
        def stop(self):
            calls.append("stop")

    class _PlaywrightHandle:
        def start(self):
            return _Runtime()

    sync_api_mod = SimpleNamespace(sync_playwright=lambda: _PlaywrightHandle())
    monkeypatch.setitem(sys.modules, "playwright", SimpleNamespace(sync_api=sync_api_mod))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api_mod)

    with pytest.raises(ValueError, match="desteklenmiyor"):
        manager._start_playwright_session("webkit", headless=True)

    assert calls == ["stop"]


def test_browser_manager_start_session_falls_back_from_playwright_to_selenium(monkeypatch):
    cfg = _Config()
    cfg.BROWSER_PROVIDER = "auto"
    manager = BM_MOD.BrowserManager(cfg)

    selenium_session = BM_MOD.BrowserSession(
        session_id="sess-fallback",
        provider="selenium",
        browser_name="chrome",
        headless=True,
        started_at=0.0,
        driver=SimpleNamespace(current_url="https://example.com"),
    )

    monkeypatch.setattr(
        manager,
        "_start_playwright_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ssl handshake failed")),
    )
    monkeypatch.setattr(manager, "_start_selenium_session", lambda *_args, **_kwargs: selenium_session)

    ok, payload = manager.start_session(browser_name="chrome")

    assert ok is True
    assert payload["session_id"] == "sess-fallback"
    audit = manager.list_audit_log()
    assert audit[0]["session_id"] == "startup:playwright"
    assert audit[0]["status"] == "failed"
    assert audit[0]["details"]["error"] == "ssl handshake failed"
    assert audit[-1]["action"] == "browser_start_session"
    assert audit[-1]["status"] == "started"


def test_browser_manager_start_selenium_session_supports_chrome_and_firefox(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    constructed = []

    class _ChromeOptions:
        def __init__(self):
            self.arguments = []

        def add_argument(self, value):
            self.arguments.append(value)

    class _FirefoxOptions:
        def __init__(self):
            self.arguments = []

        def add_argument(self, value):
            self.arguments.append(value)

    class _Driver:
        def __init__(self, label, options):
            self.label = label
            self.options = options
            self.page_timeout = None

        def set_page_load_timeout(self, value):
            self.page_timeout = value

    def _chrome(*, options):
        driver = _Driver("chrome", options)
        constructed.append(driver)
        return driver

    def _firefox(*, options):
        driver = _Driver("firefox", options)
        constructed.append(driver)
        return driver

    webdriver_mod = SimpleNamespace(
        ChromeOptions=_ChromeOptions,
        FirefoxOptions=_FirefoxOptions,
        Chrome=_chrome,
        Firefox=_firefox,
    )
    selenium_mod = SimpleNamespace(webdriver=webdriver_mod)
    monkeypatch.setitem(sys.modules, "selenium", selenium_mod)

    chrome_session = manager._start_selenium_session("chrome", headless=True)
    firefox_session = manager._start_selenium_session("firefox", headless=False)

    assert chrome_session.provider == "selenium"
    assert chrome_session.driver.page_timeout == 5
    assert constructed[0].options.arguments == ["--headless=new", "--disable-dev-shm-usage", "--no-sandbox"]
    assert firefox_session.browser_name == "firefox"
    assert constructed[1].options.arguments == []

    with pytest.raises(ValueError, match="desteklenmiyor"):
        manager._start_selenium_session("safari", headless=True)


def test_browser_manager_records_execution_failed_for_goto_and_sync_mutations(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())

    class _Page:
        def goto(self, *_args, **_kwargs):
            raise TimeoutError("goto timeout")

        def click(self, *_args, **_kwargs):
            raise RuntimeError("click failed")

        def fill(self, *_args, **_kwargs):
            raise RuntimeError("fill failed")

        def select_option(self, *_args, **_kwargs):
            raise RuntimeError("select failed")

    session = BM_MOD.BrowserSession(
        session_id="sess-errors",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
        current_url="https://example.com/dashboard",
    )
    manager._sessions[session.session_id] = session
    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: SimpleNamespace(enabled=False))

    with pytest.raises(TimeoutError, match="goto timeout"):
        manager.goto_url(session.session_id, "https://example.com")

    with pytest.raises(RuntimeError, match="click failed"):
        manager.click_element(session.session_id, "#missing")

    with pytest.raises(RuntimeError, match="fill failed"):
        manager.fill_form(session.session_id, "#name", "Sidar")

    with pytest.raises(RuntimeError, match="select failed"):
        manager.select_option(session.session_id, "#priority", "high")

    failed = [entry for entry in manager.list_audit_log() if entry["status"] == "execution_failed"]
    assert [entry["action"] for entry in failed] == [
        "browser_goto_url",
        "browser_click",
        "browser_fill_form",
        "browser_select_option",
    ]
    assert failed[0]["details"]["error"] == "goto timeout"
    assert failed[1]["selector"] == "#missing"
    assert failed[2]["details"]["value_preview"] == "*****"
    assert failed[3]["details"]["value_preview"] == "****"


def test_browser_manager_hitl_rejections_and_failures_are_audited(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())

    class _Page:
        def fill(self, *_args, **_kwargs):
            raise RuntimeError("cannot fill")

        def select_option(self, *_args, **_kwargs):
            raise RuntimeError("cannot select")

    session = BM_MOD.BrowserSession(
        session_id="sess-hitl-errors",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
        current_url="https://example.com/admin",
    )
    manager._sessions[session.session_id] = session

    class _RejectGate:
        async def request_approval(self, **kwargs):
            return False

    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: _RejectGate())
    fill_ok, fill_msg = asyncio.run(manager.fill_form_hitl(session.session_id, "#summary", "Yeni değer"))
    select_ok, select_msg = asyncio.run(manager.select_option_hitl(session.session_id, "#priority", "high"))

    assert fill_ok is False and "reddedildi" in fill_msg
    assert select_ok is False and "reddedildi" in select_msg
    assert [entry["status"] for entry in manager.list_audit_log()] == [
        "pending_approval",
        "rejected",
        "pending_approval",
        "rejected",
    ]

    class _ApproveGate:
        async def request_approval(self, **kwargs):
            return True

    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: _ApproveGate())

    with pytest.raises(RuntimeError, match="cannot fill"):
        asyncio.run(manager.fill_form_hitl(session.session_id, "#summary", "Yeni değer"))

    with pytest.raises(RuntimeError, match="cannot select"):
        asyncio.run(manager.select_option_hitl(session.session_id, "#priority", "high"))

    failed = [entry for entry in manager.list_audit_log() if entry["status"] == "execution_failed"]
    assert [entry["action"] for entry in failed] == ["browser_fill_form", "browser_select_option"]
    assert failed[0]["details"]["error"] == "cannot fill"
    assert failed[1]["details"]["error"] == "cannot select"


def test_browser_manager_uses_selenium_capture_paths(tmp_path):
    manager = BM_MOD.BrowserManager(_Config())
    manager.artifact_dir = tmp_path

    class _Driver:
        current_url = "https://example.com/selenium"
        page_source = "<html>selenium</html>"

        def save_screenshot(self, path):
            Path(path).write_bytes(b"png")

    session = BM_MOD.BrowserSession(
        session_id="sess-selenium-capture",
        provider="selenium",
        browser_name="chrome",
        headless=True,
        started_at=0.0,
        driver=_Driver(),
    )
    manager._sessions[session.session_id] = session

    ok_dom, dom = manager.capture_dom(session.session_id)
    ok_shot, shot_path = manager.capture_screenshot(session.session_id, full_page=False)

    assert ok_dom is True and dom == "<html>selenium</html>"
    assert ok_shot is True and Path(shot_path).exists()
    assert manager.list_audit_log()[-1]["details"]["full_page"] is False


def test_browser_manager_capture_dom_raises_timeout_for_playwright_page():
    manager = BM_MOD.BrowserManager(_Config())

    class _Locator:
        def inner_html(self, timeout):
            assert timeout == 5000
            raise TimeoutError("dom timeout")

    class _Page:
        def locator(self, selector):
            assert selector == "#content"
            return _Locator()

    session = BM_MOD.BrowserSession(
        session_id="sess-dom-timeout",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
    )
    manager._sessions[session.session_id] = session

    with pytest.raises(TimeoutError, match="dom timeout"):
        manager.capture_dom(session.session_id, "#content")


def test_browser_manager_capture_screenshot_raises_ioerror_for_playwright_page(tmp_path):
    manager = BM_MOD.BrowserManager(_Config())
    manager.artifact_dir = tmp_path

    class _Page:
        def screenshot(self, path, full_page):
            assert path.endswith("broken.png")
            assert full_page is True
            raise IOError("disk write failed")

    session = BM_MOD.BrowserSession(
        session_id="sess-shot-ioerror",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
    )
    manager._sessions[session.session_id] = session

    with pytest.raises(OSError, match="disk write failed"):
        manager.capture_screenshot(session.session_id, "broken.png")


def test_browser_manager_validate_url_rejects_missing_hostname():
    manager = BM_MOD.BrowserManager(_Config())

    with pytest.raises(ValueError, match="Geçersiz URL"):
        manager._validate_url("https:///missing-host")


def test_browser_manager_is_available_checks_fallbacks_and_false(monkeypatch):
    cfg = _Config()
    cfg.BROWSER_PROVIDER = "auto"
    manager = BM_MOD.BrowserManager(cfg)
    real_import = __import__
    attempted = []

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        attempted.append(name)
        if name.startswith("playwright"):
            raise ImportError("playwright missing")
        if name == "selenium":
            return SimpleNamespace()
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    assert manager.is_available() is True
    assert "playwright.sync_api" in attempted
    assert "selenium" in attempted

    attempted.clear()

    def _all_missing(name, globals=None, locals=None, fromlist=(), level=0):
        attempted.append(name)
        if name.startswith("playwright") or name == "selenium":
            raise ImportError("missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _all_missing)
    assert manager.is_available() is False
    assert "playwright.sync_api" in attempted
    assert "selenium" in attempted


def test_browser_manager_start_session_reports_unknown_provider():
    cfg = _Config()
    cfg.BROWSER_PROVIDER = "mystery"
    manager = BM_MOD.BrowserManager(cfg)

    ok, payload = manager.start_session()

    assert ok is False
    assert payload["error"] == "Desteklenmeyen browser provider: mystery"


def test_browser_manager_supports_selenium_navigation_click_fill_select_and_missing_close(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    calls = []

    class _Element:
        def click(self):
            calls.append(("click",))

        def clear(self):
            calls.append(("clear",))

        def send_keys(self, value):
            calls.append(("send_keys", value))

    element = _Element()

    class _Driver:
        current_url = ""

        def get(self, url):
            self.current_url = url
            calls.append(("get", url))

        def find_element(self, by, selector):
            calls.append(("find_element", by, selector))
            return element

        def quit(self):
            calls.append(("quit",))

    by_mod = SimpleNamespace(CSS_SELECTOR="css selector")
    selected = []

    class _Select:
        def __init__(self, value):
            selected.append(("init", value))

        def select_by_value(self, value):
            selected.append(("select_by_value", value))

    monkeypatch.setitem(sys.modules, "selenium", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "selenium.webdriver", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "selenium.webdriver.common", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "selenium.webdriver.common.by", SimpleNamespace(By=by_mod))
    monkeypatch.setitem(sys.modules, "selenium.webdriver.support", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "selenium.webdriver.support.select", SimpleNamespace(Select=_Select))

    session = BM_MOD.BrowserSession(
        session_id="sess-selenium-full",
        provider="selenium",
        browser_name="chrome",
        headless=True,
        started_at=0.0,
        driver=_Driver(),
    )
    manager._sessions[session.session_id] = session
    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: SimpleNamespace(enabled=False))

    ok_goto, goto_msg = manager.goto_url(session.session_id, "https://example.com/path")
    ok_click, click_msg = manager.click_element(session.session_id, "#submit")
    ok_fill, fill_msg = manager.fill_form(session.session_id, "#name", "Sidar", clear=True)
    ok_select, select_msg = manager.select_option(session.session_id, "#priority", "high")
    ok_close, close_msg = manager.close_session(session.session_id)
    missing_close = manager.close_session("missing-selenium")

    assert (ok_goto, goto_msg) == (True, "Açıldı: https://example.com/path")
    assert (ok_click, click_msg) == (True, "Tıklandı: #submit")
    assert (ok_fill, fill_msg) == (True, "Form dolduruldu: #name")
    assert (ok_select, select_msg) == (True, "Seçim yapıldı: #priority=high")
    assert (ok_close, close_msg) == (True, "Tarayıcı oturumu kapatıldı: sess-selenium-full")
    assert missing_close == (False, "Tarayıcı oturumu bulunamadı: missing-selenium")
    assert ("get", "https://example.com/path") in calls
    assert ("find_element", "css selector", "#submit") in calls
    assert ("clear",) in calls
    assert ("send_keys", "Sidar") in calls
    assert selected[-1] == ("select_by_value", "high")
    assert ("quit",) in calls


def test_browser_manager_fill_form_uses_playwright_type_when_clear_false(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    calls = []
    session = BM_MOD.BrowserSession(
        session_id="sess-type",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=SimpleNamespace(type=lambda selector, value, timeout: calls.append((selector, value, timeout))),
    )
    manager._sessions[session.session_id] = session
    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: SimpleNamespace(enabled=False))

    ok, message = manager.fill_form(session.session_id, "#notes", "append", clear=False)

    assert ok is True
    assert message == "Form dolduruldu: #notes"
    assert calls == [("#notes", "append", 5000)]
    assert manager.list_audit_log()[-1]["details"]["clear"] is False


def test_browser_manager_click_hitl_records_execution_failed_after_approval(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())

    class _Page:
        def click(self, *_args, **_kwargs):
            raise RuntimeError("approved click still failed")

    session = BM_MOD.BrowserSession(
        session_id="sess-hitl-click-error",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
        current_url="https://example.com/jira/SID-3",
    )
    manager._sessions[session.session_id] = session

    class _ApproveGate:
        async def request_approval(self, **kwargs):
            return True

    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: _ApproveGate())

    with pytest.raises(RuntimeError, match="approved click still failed"):
        asyncio.run(manager.click_element_hitl(session.session_id, "button[type='submit']"))

    statuses = [entry["status"] for entry in manager.list_audit_log()]
    assert statuses == ["pending_approval", "approved", "execution_failed"]
    assert manager.list_audit_log()[-1]["details"]["error"] == "approved click still failed"


def test_browser_manager_select_option_records_execution_failed_when_impl_raises(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    session = BM_MOD.BrowserSession(
        session_id="sess-select-error",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=SimpleNamespace(),
        current_url="https://example.com/form",
    )
    manager._sessions[session.session_id] = session
    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: SimpleNamespace(enabled=False))

    def _boom(_session_id, _selector, _value):
        raise RuntimeError("select impl exploded")

    monkeypatch.setattr(manager, "_select_option_impl", _boom)

    with pytest.raises(RuntimeError, match="select impl exploded"):
        manager.select_option(session.session_id, "#priority", "high")

    failed = manager.list_audit_log()[-1]
    assert failed["action"] == "browser_select_option"
    assert failed["status"] == "execution_failed"
    assert failed["details"]["error"] == "select impl exploded"
    assert failed["details"]["value_preview"] == "****"


def test_browser_manager_select_option_hitl_records_timeout_after_approval(monkeypatch):
    manager = BM_MOD.BrowserManager(_Config())
    session = BM_MOD.BrowserSession(
        session_id="sess-select-timeout",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=SimpleNamespace(),
        current_url="https://example.com/form",
    )
    manager._sessions[session.session_id] = session

    class _ApproveGate:
        async def request_approval(self, **_kwargs):
            return True

    monkeypatch.setattr(BM_MOD, "get_hitl_gate", lambda: _ApproveGate())

    def _timeout(_session_id, _selector, _value):
        raise TimeoutError("select timeout")

    monkeypatch.setattr(manager, "_select_option_impl", _timeout)

    with pytest.raises(TimeoutError, match="select timeout"):
        asyncio.run(manager.select_option_hitl(session.session_id, "#priority", "high", reason="Öncelik güncelle"))

    failed = manager.list_audit_log()[-1]
    assert failed["action"] == "browser_select_option"
    assert failed["status"] == "execution_failed"
    assert failed["details"]["error"] == "select timeout"
    assert failed["details"]["reason"] == "Öncelik güncelle"
