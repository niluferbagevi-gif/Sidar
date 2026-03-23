import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_browser_manager import BM_MOD, _Config
from tests.test_code_manager_runtime import CM_MOD, DummySecurity
from tests.test_github_manager_runtime import GM
from tests.test_slack_jira_teams import SlackManager, _run, _slack_mod
from tests.test_system_health_runtime import SystemHealthManager
from tests.test_web_search_runtime import _FakeResponse, _load_web_search_module


def test_browser_manager_capture_dom_propagates_missing_selector_from_playwright_page():
    manager = BM_MOD.BrowserManager(_Config())

    class _Page:
        def locator(self, selector):
            assert selector == "#missing"
            raise LookupError("selector not found")

    session = BM_MOD.BrowserSession(
        session_id="sess-missing-selector",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=_Page(),
    )
    manager._sessions[session.session_id] = session

    with pytest.raises(LookupError, match="selector not found"):
        manager.capture_dom(session.session_id, "#missing")


def test_code_manager_write_file_reports_invalid_directory_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    manager = CM_MOD.CodeManager(DummySecurity(tmp_path, can_write=True), tmp_path)

    def _broken_mkdir(self, parents=False, exist_ok=False):
        raise FileNotFoundError("invalid directory root")

    monkeypatch.setattr(CM_MOD.Path, "mkdir", _broken_mkdir)

    ok, message = manager.write_file(str(tmp_path / "ghost" / "file.txt"), "hello", validate=False)

    assert ok is False
    assert "Yazma hatası" in message
    assert "invalid directory root" in message


def test_github_manager_reports_invalid_token_and_repo_500_paths(monkeypatch):
    class _Auth:
        @staticmethod
        def Token(token):
            return token

    class _AuthError(Exception):
        status = 401

    class _GithubBadAuth:
        def __init__(self, auth):
            self.auth = auth

        def get_user(self):
            raise _AuthError("Unauthorized")

    github_mod = types.ModuleType("github")
    github_mod.Auth = _Auth
    github_mod.Github = _GithubBadAuth
    monkeypatch.setitem(sys.modules, "github", github_mod)

    mgr = GM.GitHubManager(token="bad-token")

    assert mgr.is_available() is False
    assert "Token geçersiz" in mgr.status()

    mgr._gh = SimpleNamespace(get_repo=lambda _name: (_ for _ in ()).throw(RuntimeError("500 Internal Server Error")))
    mgr._available = True
    assert mgr.set_repo("org/repo") == (False, "Depo bulunamadı veya erişim reddedildi: org/repo")


def test_slack_manager_webhook_returns_401_error(monkeypatch):
    manager = SlackManager.__new__(SlackManager)
    manager.token = ""
    manager.webhook_url = "https://hooks.slack.com/test"
    manager.default_channel = "#alerts"
    manager._client = None
    manager._available = True
    manager._webhook_only = True

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=401, text="unauthorized")

    monkeypatch.setattr(_slack_mod.httpx, "AsyncClient", lambda timeout: _Client())

    ok, err = _run(manager.send_webhook(text="Deploy failed"))

    assert ok is False
    assert err == "HTTP 401: unauthorized"


def test_system_health_manager_handles_missing_psutil_and_nvml_in_init(monkeypatch):
    monkeypatch.setattr(SystemHealthManager, "_check_import", lambda self, name: False if name in {"psutil", "pynvml"} else name == "torch")
    monkeypatch.setattr(SystemHealthManager, "_check_gpu", lambda self: False)

    mgr = SystemHealthManager(use_gpu=True, cfg=SimpleNamespace())

    assert mgr.get_cpu_usage() is None
    assert mgr.get_memory_info() == {}
    assert mgr.get_gpu_info()["available"] is False


def test_web_search_tavily_rate_limit_returns_error_without_disabling_key(monkeypatch):
    mod = _load_web_search_module(monkeypatch)
    cfg = SimpleNamespace(
        SEARCH_ENGINE="auto",
        TAVILY_API_KEY="t-key",
        GOOGLE_SEARCH_API_KEY="",
        GOOGLE_SEARCH_CX="",
        WEB_SEARCH_MAX_RESULTS=5,
        WEB_FETCH_TIMEOUT=15,
        WEB_SCRAPE_MAX_CHARS=12000,
    )
    manager = mod.WebSearchManager(cfg)

    class _RateLimitedClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _FakeResponse(status_code=429, json_data={"detail": "rate limit"})

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda timeout, headers: _RateLimitedClient())

    ok, message = asyncio.run(manager._search_tavily("sidar", 3))

    assert ok is False
    assert "[HATA] Tavily:" in message
    assert manager.tavily_key == "t-key"