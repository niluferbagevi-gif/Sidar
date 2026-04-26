from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from managers.browser_manager import BaseBrowserProvider, BrowserManager, BrowserSession


class _Cfg:
    BROWSER_PROVIDER = "auto"
    BROWSER_HEADLESS = True
    BROWSER_TIMEOUT_MS = 1234
    BROWSER_ALLOWED_DOMAINS = ["example.com"]


@pytest.fixture
def manager(tmp_path: Path) -> BrowserManager:
    mgr = BrowserManager(config=_Cfg())
    mgr.artifact_dir = tmp_path
    return mgr


def _register_fake_selenium(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    mod_selenium = types.ModuleType("selenium")
    webdriver_mod = types.ModuleType("selenium.webdriver")
    common_mod = types.ModuleType("selenium.webdriver.common")
    by_mod = types.ModuleType("selenium.webdriver.common.by")
    support_mod = types.ModuleType("selenium.webdriver.support")
    select_mod = types.ModuleType("selenium.webdriver.support.select")

    class By:
        CSS_SELECTOR = "css"

    class _ChromeOptions:
        def __init__(self) -> None:
            self.args: list[str] = []

        def add_argument(self, arg: str) -> None:
            self.args.append(arg)

    class _FirefoxOptions:
        def __init__(self) -> None:
            self.args: list[str] = []

        def add_argument(self, arg: str) -> None:
            self.args.append(arg)

    class _Element:
        def __init__(self) -> None:
            self.clicked = False
            self.cleared = False
            self.typed: list[str] = []

        def click(self) -> None:
            self.clicked = True

        def clear(self) -> None:
            self.cleared = True

        def send_keys(self, value: str) -> None:
            self.typed.append(value)

    class _Driver:
        def __init__(self, options: object) -> None:
            self.options = options
            self.current_url = "https://driver.local"
            self.timeout = None
            self.source = "<html>selenium</html>"
            self.gotten: list[str] = []
            self.saved: list[str] = []
            self.quitted = False
            self.element = _Element()

        def set_page_load_timeout(self, timeout: int) -> None:
            self.timeout = timeout

        def get(self, url: str) -> None:
            self.gotten.append(url)

        def find_element(self, _by: str, _selector: str) -> _Element:
            return self.element

        @property
        def page_source(self) -> str:
            return self.source

        def save_screenshot(self, path: str) -> None:
            self.saved.append(path)

        def quit(self) -> None:
            self.quitted = True

    selected_values: list[str] = []

    class Select:
        def __init__(self, _element: _Element) -> None:
            self._element = _element

        def select_by_value(self, value: str) -> None:
            selected_values.append(value)

    webdriver_mod.ChromeOptions = _ChromeOptions
    webdriver_mod.FirefoxOptions = _FirefoxOptions
    webdriver_mod.Chrome = lambda options: _Driver(options)
    webdriver_mod.Firefox = lambda options: _Driver(options)
    by_mod.By = By
    select_mod.Select = Select

    monkeypatch.setitem(sys.modules, "selenium", mod_selenium)
    monkeypatch.setitem(sys.modules, "selenium.webdriver", webdriver_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.common", common_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.common.by", by_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.support", support_mod)
    monkeypatch.setitem(sys.modules, "selenium.webdriver.support.select", select_mod)

    return {"selected_values": selected_values}


def _register_fake_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")

    class _Page:
        def __init__(self) -> None:
            self.url = "https://p.local"
            self.clicked: list[str] = []
            self.filled: list[tuple[str, str]] = []
            self.typed: list[tuple[str, str]] = []
            self.selected: list[tuple[str, str]] = []
            self.goto_calls: list[str] = []
            self.screens: list[str] = []

        def set_default_timeout(self, _timeout: int) -> None:
            return None

        def goto(self, url: str, **_kwargs: object) -> None:
            self.goto_calls.append(url)

        def click(self, selector: str, **_kwargs: object) -> None:
            self.clicked.append(selector)

        def fill(self, selector: str, value: str, **_kwargs: object) -> None:
            self.filled.append((selector, value))

        def type(self, selector: str, value: str, **_kwargs: object) -> None:
            self.typed.append((selector, value))

        def select_option(self, selector: str, *, value: str, **_kwargs: object) -> None:
            self.selected.append((selector, value))

        def locator(self, _selector: str) -> SimpleNamespace:
            return SimpleNamespace(inner_html=lambda **_kwargs: "<html>playwright</html>")

        def screenshot(self, *, path: str, full_page: bool) -> None:
            self.screens.append(f"{path}|{full_page}")

    class _Context:
        def __init__(self) -> None:
            self.closed = False
            self.page = _Page()

        def new_page(self) -> _Page:
            return self.page

        def close(self) -> None:
            self.closed = True

    class _Browser:
        def __init__(self) -> None:
            self.closed = False
            self.context = _Context()

        def new_context(self) -> _Context:
            return self.context

        def close(self) -> None:
            self.closed = True

    class _Launcher:
        def launch(self, *, headless: bool) -> _Browser:
            assert isinstance(headless, bool)
            return _Browser()

    class _Runtime:
        def __init__(self) -> None:
            self.stopped = False
            self.chromium = _Launcher()

        def stop(self) -> None:
            self.stopped = True

    class _Driver:
        def __init__(self) -> None:
            self.runtime = _Runtime()

        def start(self) -> _Runtime:
            return self.runtime

    sync_api.sync_playwright = lambda: _Driver()
    monkeypatch.setitem(sys.modules, "playwright", pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


def _session(provider: str = "playwright") -> BrowserSession:
    return BrowserSession(
        session_id="s1",
        provider=provider,
        browser_name="chromium",
        headless=True,
        started_at=1.0,
        page=SimpleNamespace(url="https://p.now"),
        driver=SimpleNamespace(current_url="https://s.now"),
    )


def test_helpers_and_summary(manager: BrowserManager) -> None:
    assert manager._is_high_risk_click("button.submit") is True
    assert manager._is_high_risk_click("a.read-more") is False
    assert manager._summarize_value("") == ""
    assert manager._summarize_value("12345678") == "********"
    assert manager._summarize_value("123456789") == "12***89 (len=9)"

    manager._record_audit_event(session_id="s1", action="browser_click", status="execution_failed", selector="#x")
    manager._record_audit_event(session_id="s1", action="browser_fill_form", status="pending_approval", selector="#save")
    manager._record_audit_event(session_id="s1", action="browser_click", status="executed", selector="#delete")
    summary = manager.summarize_audit_log("s1", limit=2)
    assert summary["status"] == "failed"
    assert summary["risk"] == "yüksek"
    assert len(summary["recent_entries"]) == 2

    manager._audit_log.clear()
    assert manager.summarize_audit_log()["status"] == "no-signal"


def test_collect_signals_and_session_url(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _session("playwright")
    sess.current_url = "https://set.local"
    manager._sessions[sess.session_id] = sess

    monkeypatch.setattr(manager, "capture_dom", lambda *_a, **_k: (True, "x" * 1200))
    monkeypatch.setattr(manager, "capture_screenshot", lambda *_a, **_k: (True, "/tmp/a.png"))
    result = manager.collect_session_signals("s1", include_dom=True, include_screenshot=True)
    assert result["dom_capture"]["preview"].endswith("…")
    assert result["screenshot"]["ok"] is True

    sess.current_url = ""
    assert manager._session_url(sess) == "https://p.now"
    sess.provider = "selenium"
    assert manager._session_url(sess) == "https://s.now"
    sess.provider = "none"
    assert manager._session_url(sess) == ""


def test_hitl_request_and_sync_guard(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Gate:
        enabled = True

        async def request_approval(self, **_kwargs: object) -> bool:
            calls.append("asked")
            return True

    monkeypatch.setattr("managers.browser_manager.get_hitl_gate", lambda: _Gate())
    approved = asyncio.run(manager._request_hitl_approval(
        session=_session(),
        action="browser_click",
        description="d",
        payload={"x": 1},
        selector="#ok",
    ))
    assert approved is True and calls == ["asked"]

    assert manager._sync_hitl_guard("browser_click", "#view") is None
    blocked = manager._sync_hitl_guard("browser_click", "#submit")
    assert blocked and blocked[0] is False
    blocked2 = manager._sync_hitl_guard("browser_fill_form", "#field", force_block=True)
    assert blocked2 and "fill_form_hitl" in blocked2[1]

    class _OffGate:
        enabled = False

    monkeypatch.setattr("managers.browser_manager.get_hitl_gate", lambda: _OffGate())
    assert manager._sync_hitl_guard("browser_click", "#submit") is None


def test_validation_provider_and_require_session(manager: BrowserManager) -> None:
    assert manager._provider_candidates() == ["playwright", "selenium"]
    manager.provider = "selenium"
    assert manager._provider_candidates() == ["selenium"]

    manager.allowed_domains = {"example.com"}
    manager._validate_url("https://example.com/page")
    with pytest.raises(ValueError):
        manager._validate_url("ftp://example.com")
    with pytest.raises(ValueError):
        manager._validate_url("https:///no-host")
    with pytest.raises(ValueError):
        manager._validate_url("https://blocked.com")
    with pytest.raises(KeyError):
        manager._require_session("none")


def test_start_playwright_session(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake_playwright(monkeypatch)
    session = manager._start_playwright_session("chromium", True)
    assert session.provider == "playwright"

    with pytest.raises(ValueError):
        manager._start_playwright_session("firefox", True)


def test_start_selenium_session_and_impls(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = _register_fake_selenium(monkeypatch)
    session = manager._start_selenium_session("chrome", True)
    assert session.provider == "selenium"
    assert "--headless=new" in session.driver.options.args

    session_ff = manager._start_selenium_session("firefox", True)
    assert "-headless" in session_ff.driver.options.args

    with pytest.raises(ValueError):
        manager._start_selenium_session("safari", True)

    manager._sessions["s1"] = session
    ok, _ = manager._click_element_impl("s1", "#btn")
    assert ok is True and session.driver.element.clicked is True

    ok, _ = manager._fill_form_impl("s1", "#inp", "abc", clear=True)
    assert ok is True and session.driver.element.cleared is True

    ok, _ = manager._fill_form_impl("s1", "#inp", "xyz", clear=False)
    assert ok is True and session.driver.element.typed[-1] == "xyz"

    ok, _ = manager._select_option_impl("s1", "#sel", "v1")
    assert ok is True and reg["selected_values"][-1] == "v1"


def test_is_available_status_and_start_session(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake_playwright(monkeypatch)
    assert manager.is_available() is True

    for key in [k for k in list(sys.modules) if k.startswith("playwright")]:
        monkeypatch.delitem(sys.modules, key, raising=False)
    _register_fake_selenium(monkeypatch)
    manager.provider = "selenium"
    assert manager.is_available() is True

    original_import = __import__

    def _failing_import(name: str, *args: object, **kwargs: object):
        if name.startswith("playwright") or name.startswith("selenium"):
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _failing_import)
    manager.provider = "auto"
    assert manager.is_available() is False

    monkeypatch.setattr(manager, "is_available", lambda: True)
    assert "available=yes" in manager.status()

    test_session = _session("playwright")
    monkeypatch.setattr(manager, "_provider_candidates", lambda: ["playwright"])
    monkeypatch.setattr(manager._browser_providers["playwright"], "start_session", lambda *_a, **_k: test_session)
    ok, info = manager.start_session()
    assert ok is True and info["session_id"] == "s1"

    monkeypatch.setattr(manager, "_provider_candidates", lambda: ["unknown"])
    ok, info = manager.start_session()
    assert ok is False and "Desteklenmeyen" in info["error"]

    monkeypatch.setattr(manager, "_provider_candidates", lambda: ["playwright", "selenium"])
    monkeypatch.setattr(
        manager._browser_providers["playwright"],
        "start_session",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("pw")),
    )
    monkeypatch.setattr(
        manager._browser_providers["selenium"],
        "start_session",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("se")),
    )
    ok, info = manager.start_session()
    assert ok is False and info["error"] == "se"


def test_start_session_respects_selenium_provider_preference(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _SeleniumCfg(_Cfg):
        BROWSER_PROVIDER = "selenium"

    mgr = BrowserManager(config=_SeleniumCfg())
    mgr.artifact_dir = tmp_path

    calls = {"playwright": 0, "selenium": 0}
    expected = _session("selenium")
    expected.session_id = "se-only"

    def _playwright_start(*_a, **_k):
        calls["playwright"] += 1
        raise AssertionError("playwright should not be attempted when provider=selenium")

    def _selenium_start(*_a, **_k):
        calls["selenium"] += 1
        return expected

    monkeypatch.setattr(mgr._browser_providers["playwright"], "start_session", _playwright_start)
    monkeypatch.setattr(mgr._browser_providers["selenium"], "start_session", _selenium_start)

    ok, info = mgr.start_session(browser_name="chrome")
    assert ok is True
    assert info["provider"] == "selenium"
    assert calls["playwright"] == 0
    assert calls["selenium"] == 1


def test_navigation_and_sync_actions(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake_playwright(monkeypatch)
    pw = manager._start_playwright_session("chromium", True)
    pw.session_id = "pw"
    manager._sessions["pw"] = pw

    assert manager.goto_url("pw", "https://example.com")[0] is True
    monkeypatch.setattr(pw.page, "goto", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        manager.goto_url("pw", "https://example.com")

    assert manager.click_element("pw", "#read")[0] is True
    monkeypatch.setattr(manager, "_sync_hitl_guard", lambda *_a, **_k: (False, "blocked"))
    assert manager.click_element("pw", "#submit") == (False, "blocked")
    monkeypatch.setattr(manager, "_sync_hitl_guard", lambda *_a, **_k: None)
    monkeypatch.setattr(manager, "_click_element_impl", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        manager.click_element("pw", "#x")

    monkeypatch.setattr(manager, "_fill_form_impl", lambda *_a, **_k: (True, "ok"))
    assert manager.fill_form("pw", "#i", "value")[0] is True
    monkeypatch.setattr(manager, "_sync_hitl_guard", lambda *_a, **_k: (False, "blocked"))
    assert manager.fill_form("pw", "#i", "value") == (False, "blocked")
    monkeypatch.setattr(manager, "_sync_hitl_guard", lambda *_a, **_k: None)
    monkeypatch.setattr(manager, "_fill_form_impl", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("ff")))
    with pytest.raises(RuntimeError):
        manager.fill_form("pw", "#i", "value")

    monkeypatch.setattr(manager, "_select_option_impl", lambda *_a, **_k: (True, "ok"))
    assert manager.select_option("pw", "#s", "v")[0] is True
    monkeypatch.setattr(manager, "_sync_hitl_guard", lambda *_a, **_k: (False, "blocked"))
    assert manager.select_option("pw", "#s", "v") == (False, "blocked")
    monkeypatch.setattr(manager, "_sync_hitl_guard", lambda *_a, **_k: None)
    monkeypatch.setattr(manager, "_select_option_impl", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("so")))
    with pytest.raises(RuntimeError):
        manager.select_option("pw", "#s", "v")


def test_async_hitl_paths(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _session("playwright")
    manager._sessions["s1"] = sess

    monkeypatch.setattr(manager, "click_element", lambda *_a, **_k: (True, "sync"))
    assert asyncio.run(manager.click_element_hitl("s1", "#safe", require_confirmation=False)) == (True, "sync")

    async def _deny(**_k: object) -> bool:
        return False

    async def _allow(**_k: object) -> bool:
        return True

    monkeypatch.setattr(manager, "_request_hitl_approval", _deny)
    monkeypatch.setattr(manager, "_click_element_impl", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run")))
    ok, message = asyncio.run(manager.click_element_hitl("s1", "#submit", require_confirmation=True))
    assert ok is False
    assert "reddedildi" in message

    monkeypatch.setattr(manager, "_request_hitl_approval", _allow)
    monkeypatch.setattr(manager, "_click_element_impl", lambda *_a, **_k: (True, "ok"))
    assert (asyncio.run(manager.click_element_hitl("s1", "#submit", require_confirmation=True)))[0] is True

    monkeypatch.setattr(manager, "_click_element_impl", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("ce")))
    with pytest.raises(RuntimeError):
        asyncio.run(manager.click_element_hitl("s1", "#submit", require_confirmation=True))

    monkeypatch.setattr(manager, "_request_hitl_approval", _deny)
    monkeypatch.setattr(manager, "_fill_form_impl", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run")))
    deny_fill_ok, deny_fill_message = asyncio.run(manager.fill_form_hitl("s1", "#i", "secret"))
    assert deny_fill_ok is False
    assert "reddedildi" in deny_fill_message
    monkeypatch.setattr(manager, "_request_hitl_approval", _allow)
    monkeypatch.setattr(manager, "_fill_form_impl", lambda *_a, **_k: (True, "ok"))
    assert (asyncio.run(manager.fill_form_hitl("s1", "#i", "secret")))[0] is True
    monkeypatch.setattr(manager, "_fill_form_impl", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fe")))
    with pytest.raises(RuntimeError):
        asyncio.run(manager.fill_form_hitl("s1", "#i", "secret"))

    monkeypatch.setattr(manager, "_request_hitl_approval", _deny)
    monkeypatch.setattr(manager, "_select_option_impl", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run")))
    deny_select_ok, deny_select_message = asyncio.run(manager.select_option_hitl("s1", "#s", "v"))
    assert deny_select_ok is False
    assert "reddedildi" in deny_select_message
    monkeypatch.setattr(manager, "_request_hitl_approval", _allow)
    monkeypatch.setattr(manager, "_select_option_impl", lambda *_a, **_k: (True, "ok"))
    assert (asyncio.run(manager.select_option_hitl("s1", "#s", "v")))[0] is True
    monkeypatch.setattr(manager, "_select_option_impl", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("se")))
    with pytest.raises(RuntimeError):
        asyncio.run(manager.select_option_hitl("s1", "#s", "v"))


def test_capture_and_close(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _register_fake_playwright(monkeypatch)
    pw = manager._start_playwright_session("chromium", True)
    pw.session_id = "pw"
    manager._sessions["pw"] = pw

    ok, dom = manager.capture_dom("pw", "html")
    assert ok is True and "playwright" in dom
    monkeypatch.setattr(pw.page, "locator", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("dom")))
    assert manager.capture_dom("pw", "html")[0] is False

    manager.artifact_dir = tmp_path
    ok, path = manager.capture_screenshot("pw", "x.png", full_page=False)
    assert ok is True and path.endswith("x.png")

    ok, message = manager.close_session("pw")
    assert ok is True and "kapatıldı" in message
    assert manager.close_session("missing")[0] is False

    # Selenium capture/close branches
    reg = _register_fake_selenium(monkeypatch)
    _ = reg
    se = manager._start_selenium_session("chrome", True)
    se.session_id = "se"
    manager._sessions["se"] = se
    assert manager.capture_dom("se")[0] is True
    assert manager.capture_screenshot("se", "s.png")[0] is True
    assert manager.close_session("se")[0] is True

    fail = BrowserSession(
        session_id="f",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=1.0,
        context=SimpleNamespace(close=lambda: (_ for _ in ()).throw(RuntimeError("close"))),
        browser=SimpleNamespace(close=lambda: None),
        runtime=SimpleNamespace(stop=lambda: None),
    )
    manager._sessions["f"] = fail
    assert manager.close_session("f")[0] is False

def test_additional_summary_and_list(manager: BrowserManager) -> None:
    manager._record_audit_event(
        session_id="s2",
        action="browser_click",
        status="pending_approval",
        selector="#submit",
        current_url="https://u1",
    )
    manager._record_audit_event(
        session_id="s2",
        action="browser_click",
        status="pending_approval",
        selector="#submit",
        current_url="https://u1",
    )
    manager._record_audit_event(
        session_id="s2",
        action="browser_click",
        status="executed",
        selector="#submit",
        current_url="https://u2",
    )
    summary = manager.summarize_audit_log("s2")
    assert summary["status"] == "attention"
    assert summary["urls"] == ["https://u1", "https://u2"]
    logs = manager.list_audit_log()
    assert isinstance(logs, list) and len(logs) == 3

    manager._audit_log = [
        {"session_id": "ok1", "action": "browser_goto_url", "status": "executed", "selector": "", "url": ""}
    ]
    assert manager.summarize_audit_log("ok1")["status"] == "ok"


def test_summary_branch_gaps_and_collect_signal_defaults(manager: BrowserManager) -> None:
    # status/action boş olan kayıtlar branch fallback yollarını çalıştırmalı
    manager._record_audit_event(session_id="b1", action="", status="", selector="#noop")

    # Aynı başarısız aksiyon bir kez failed_actions listesine girmeli
    manager._record_audit_event(
        session_id="b1",
        action="browser_click",
        status="failed",
        selector="#dup",
    )
    manager._record_audit_event(
        session_id="b1",
        action="browser_click",
        status="failed",
        selector="#dup",
    )

    summary = manager.summarize_audit_log("b1")
    assert summary["status_counts"] == {"failed": 2}
    assert summary["action_counts"] == {"browser_click": 2}
    assert summary["failed_actions"] == ["browser_click:#dup"]

    sess = _session("playwright")
    sess.session_id = "b1"
    manager._sessions["b1"] = sess
    signal = manager.collect_session_signals("b1")
    assert "dom_capture" not in signal
    assert "screenshot" not in signal


def test_playwright_impl_and_goto_selenium(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake_playwright(monkeypatch)
    pw = manager._start_playwright_session("chromium", True)
    pw.session_id = "pw2"
    manager._sessions["pw2"] = pw
    assert manager._fill_form_impl("pw2", "#a", "v", clear=True)[0] is True
    assert manager._fill_form_impl("pw2", "#a", "v", clear=False)[0] is True
    assert manager._select_option_impl("pw2", "#s", "1")[0] is True

    _register_fake_selenium(monkeypatch)
    se = manager._start_selenium_session("chrome", False)
    se.session_id = "se2"
    manager._sessions["se2"] = se
    assert manager.goto_url("se2", "https://example.com")[0] is True


def test_strategy_provider_dispatch_custom_backend(manager: BrowserManager) -> None:
    class _CustomProvider(BaseBrowserProvider):
        provider_name = "custom"

        def start_session(self, manager: BrowserManager, browser_name: str, headless: bool) -> BrowserSession:
            return BrowserSession(
                session_id="c1",
                provider="custom",
                browser_name=browser_name,
                headless=headless,
                started_at=1.0,
            )

        def goto(self, manager: BrowserManager, session: BrowserSession, url: str) -> None:
            session.current_url = f"custom://{url}"

        def click(self, manager: BrowserManager, session: BrowserSession, selector: str) -> None:
            _ = (manager, session, selector)

        def fill(self, manager: BrowserManager, session: BrowserSession, selector: str, value: str, *, clear: bool) -> None:
            _ = (manager, session, selector, value, clear)

        def select(self, manager: BrowserManager, session: BrowserSession, selector: str, value: str) -> None:
            _ = (manager, session, selector, value)

        def capture_dom(self, manager: BrowserManager, session: BrowserSession, selector: str) -> str:
            _ = (manager, session, selector)
            return "<html>custom</html>"

        def capture_screenshot(self, manager: BrowserManager, session: BrowserSession, path: str, *, full_page: bool) -> None:
            _ = (manager, session, full_page)
            Path(path).write_bytes(b"x")

        def close(self, manager: BrowserManager, session: BrowserSession) -> None:
            _ = (manager, session)

        def current_url(self, session: BrowserSession) -> str:
            return session.current_url

    manager._browser_providers["custom"] = _CustomProvider()
    manager.provider = "custom"
    ok, info = manager.start_session(browser_name="chromium", headless=True)
    assert ok is True
    assert info["provider"] == "custom"
    assert manager.goto_url("c1", "https://example.com")[0] is True
    assert manager._sessions["c1"].current_url.startswith("custom://")


def test_start_selenium_non_headless_and_close_partial(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    _register_fake_selenium(monkeypatch)
    ch = manager._start_selenium_session("chrome", False)
    ff = manager._start_selenium_session("firefox", False)
    assert "--headless=new" not in ch.driver.options.args
    assert "-headless" not in ff.driver.options.args

    # close_session branch where context/browser/runtime are None
    blank = BrowserSession(
        session_id="blank",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=1.0,
    )
    manager._sessions["blank"] = blank
    assert manager.close_session("blank")[0] is True


@pytest.mark.parametrize(
    ("browser_name", "headless", "expected_arg"),
    [
        ("chrome", True, "--headless=new"),
        ("chrome", False, None),
        ("firefox", True, "-headless"),
        ("firefox", False, None),
    ],
)
def test_start_selenium_session_parametrized_headless_flags(
    manager: BrowserManager,
    monkeypatch: pytest.MonkeyPatch,
    browser_name: str,
    headless: bool,
    expected_arg: str | None,
) -> None:
    _register_fake_selenium(monkeypatch)
    session = manager._start_selenium_session(browser_name, headless)
    assert session.provider == "selenium"
    if expected_arg is None:
        assert expected_arg not in session.driver.options.args
    else:
        assert expected_arg in session.driver.options.args


@pytest.mark.parametrize("clear", [True, False])
def test_selenium_fill_form_impl_parametrized_clear_flag(
    manager: BrowserManager, monkeypatch: pytest.MonkeyPatch, clear: bool
) -> None:
    _register_fake_selenium(monkeypatch)
    session = manager._start_selenium_session("chrome", True)
    session.session_id = f"se-fill-{int(clear)}"
    manager._sessions[session.session_id] = session

    ok, _ = manager._fill_form_impl(session.session_id, "#inp", "abc", clear=clear)
    assert ok is True
    assert session.driver.element.typed[-1] == "abc"
    assert session.driver.element.cleared is clear


@pytest.mark.parametrize(
    ("action", "args"),
    [
        ("click", ("#btn",)),
        ("select", ("#sel", "v2")),
    ],
)
def test_selenium_interaction_impls_parametrized(
    manager: BrowserManager,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    args: tuple[str, ...],
) -> None:
    reg = _register_fake_selenium(monkeypatch)
    session = manager._start_selenium_session("chrome", True)
    session.session_id = f"se-{action}"
    manager._sessions[session.session_id] = session

    if action == "click":
        ok, _ = manager._click_element_impl(session.session_id, *args)
        assert ok is True
        assert session.driver.element.clicked is True
    else:
        ok, _ = manager._select_option_impl(session.session_id, *args)
        assert ok is True
        assert reg["selected_values"][-1] == "v2"


def test_analyze_visual_drift_reports_missing_baseline(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _session("playwright")
    sess.session_id = "v1"
    manager._sessions["v1"] = sess
    monkeypatch.setattr(manager, "capture_screenshot", lambda *_a, **_k: (True, str(manager.artifact_dir / "cur.png")))
    (manager.artifact_dir / "cur.png").write_bytes(b"same")

    result = asyncio.run(manager.analyze_visual_drift("v1"))
    assert result["ok"] is True
    assert result["reason"] == "baseline_missing"
    assert result["drift_detected"] is False


def test_analyze_visual_drift_with_hash_fallback_detects_change(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _session("playwright")
    sess.session_id = "v2"
    manager._sessions["v2"] = sess

    baseline = manager.artifact_dir / "baseline.png"
    current = manager.artifact_dir / "current.png"
    baseline.write_bytes(b"baseline-bytes")
    current.write_bytes(b"current-bytes")

    monkeypatch.setattr(manager, "capture_screenshot", lambda *_a, **_k: (True, str(current)))
    monkeypatch.setattr("managers.browser_manager.importlib.import_module", lambda name: (_ for _ in ()).throw(ImportError(name)))

    result = asyncio.run(manager.analyze_visual_drift("v2", baseline_path=str(baseline), run_multimodal_analysis=False))
    assert result["ok"] is True
    assert result["drift_detected"] is True
    assert result["reason"] == "hash_fallback"


def test_compute_visual_drift_uses_hash_fallback_when_pil_processing_fails(
    manager: BrowserManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = manager.artifact_dir / "baseline-broken.png"
    current = manager.artifact_dir / "current-broken.png"
    baseline.write_bytes(b"baseline-content")
    current.write_bytes(b"current-content")

    class _ImageModule:
        @staticmethod
        def open(_path: str):
            raise OSError("broken image")

    class _ImageChopsModule:
        @staticmethod
        def difference(_a, _b):
            raise AssertionError("difference should not run when image open fails")

    def _import_module(name: str):
        if name == "PIL.Image":
            return _ImageModule
        if name == "PIL.ImageChops":
            return _ImageChopsModule
        raise ImportError(name)

    monkeypatch.setattr("managers.browser_manager.importlib.import_module", _import_module)
    drift = manager._compute_visual_drift(baseline, current)

    assert drift["reason"] == "hash_fallback"
    assert drift["drift_detected"] is True
    assert drift["baseline_hash"] != drift["current_hash"]


def test_collect_signals_includes_visual_qa(manager: BrowserManager, monkeypatch: pytest.MonkeyPatch) -> None:
    sess = _session("playwright")
    sess.session_id = "v3"
    manager._sessions["v3"] = sess

    async def _fake_visual(*_a, **_k):
        return {"ok": True, "drift_detected": False, "drift_score": 0.0}

    monkeypatch.setattr(manager, "analyze_visual_drift", _fake_visual)
    signal = manager.collect_session_signals("v3", include_visual_qa=True)
    assert signal["visual_qa"]["ok"] is True


def test_analyze_visual_drift_runs_multimodal_only_in_uncertainty_band(
    manager: BrowserManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    sess = _session("playwright")
    sess.session_id = "v4"
    manager._sessions["v4"] = sess

    baseline = manager.artifact_dir / "baseline-v4.png"
    current = manager.artifact_dir / "current-v4.png"
    baseline.write_bytes(b"baseline")
    current.write_bytes(b"current")

    monkeypatch.setattr(manager, "capture_screenshot", lambda *_a, **_k: (True, str(current)))
    monkeypatch.setattr(manager, "_compute_visual_drift", lambda *_a, **_k: {"drift_detected": True, "drift_score": 0.016})

    calls = {"mm": 0}

    async def _mm(*_a, **_k):
        calls["mm"] += 1
        return {"success": True}

    monkeypatch.setattr(manager, "_analyze_screenshot_with_multimodal", _mm)
    result = asyncio.run(manager.analyze_visual_drift("v4", baseline_path=str(baseline), run_multimodal_analysis=True))

    assert calls["mm"] == 1
    assert result["multimodal_check"]["triggered"] is True
    assert result["multimodal_analysis"]["success"] is True


def test_analyze_visual_drift_skips_multimodal_when_far_from_threshold(
    manager: BrowserManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    sess = _session("playwright")
    sess.session_id = "v5"
    manager._sessions["v5"] = sess

    baseline = manager.artifact_dir / "baseline-v5.png"
    current = manager.artifact_dir / "current-v5.png"
    baseline.write_bytes(b"baseline")
    current.write_bytes(b"current")

    monkeypatch.setattr(manager, "capture_screenshot", lambda *_a, **_k: (True, str(current)))
    monkeypatch.setattr(manager, "_compute_visual_drift", lambda *_a, **_k: {"drift_detected": True, "drift_score": 0.9})

    async def _mm(*_a, **_k):
        raise AssertionError("multimodal should not be called when drift score is far from threshold")

    monkeypatch.setattr(manager, "_analyze_screenshot_with_multimodal", _mm)
    result = asyncio.run(manager.analyze_visual_drift("v5", baseline_path=str(baseline), run_multimodal_analysis=True))

    assert result["multimodal_check"]["triggered"] is False
    assert "multimodal_analysis" not in result
