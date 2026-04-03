from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import managers.code_manager as code_mod
from managers.browser_manager import BrowserManager, BrowserSession
from managers.github_manager import GitHubManager


class _Cfg:
    BROWSER_PROVIDER = "auto"
    BROWSER_HEADLESS = True
    BROWSER_TIMEOUT_MS = 5000
    BROWSER_ALLOWED_DOMAINS = ["allowed.test"]


def test_code_manager_lsp_encode_decode_and_uri_roundtrip(monkeypatch, tmp_path: Path) -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    encoded = code_mod._encode_lsp_message(payload)
    decoded = code_mod._decode_lsp_stream(encoded)
    assert decoded == [payload]

    with_path = tmp_path / "demo.py"
    with_path.write_text("print('ok')")
    uri = code_mod._path_to_file_uri(with_path)
    back = code_mod._file_uri_to_path(uri)
    assert str(back).endswith("demo.py")

    monkeypatch.setattr(code_mod, "_OS_NAME", "nt")
    win = code_mod._file_uri_to_path("file:///C:/Temp/demo.py")
    assert str(win).lower().endswith("c:\\temp\\demo.py")


def test_code_manager_runtime_and_limits_validation(monkeypatch) -> None:
    mgr = code_mod.CodeManager.__new__(code_mod.CodeManager)
    mgr.docker_runtime = "unknown"
    mgr.docker_allowed_runtimes = ["", "runsc"]
    mgr.docker_microvm_mode = "off"
    mgr.docker_mem_limit = "256m"
    mgr.docker_exec_timeout = 10
    mgr.docker_nano_cpus = 1_000_000_000
    mgr.cfg = SimpleNamespace(SANDBOX_LIMITS={"cpus": "bad", "pids_limit": 0, "timeout": 0})

    assert mgr._resolve_runtime() == ""
    limits = mgr._resolve_sandbox_limits()
    assert limits["pids_limit"] == 64
    assert limits["timeout"] == 10


def test_browser_manager_url_validation_and_candidates() -> None:
    manager = BrowserManager(config=_Cfg())
    assert manager._provider_candidates() == ["playwright", "selenium"]

    manager.provider = "selenium"
    assert manager._provider_candidates() == ["selenium"]

    manager._validate_url("https://allowed.test/path")

    try:
        manager._validate_url("ftp://allowed.test")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_browser_manager_collect_session_signals_and_sync_guard(monkeypatch) -> None:
    manager = BrowserManager(config=_Cfg())
    session = BrowserSession(
        session_id="s1",
        provider="playwright",
        browser_name="chromium",
        headless=True,
        started_at=0.0,
        page=SimpleNamespace(url="https://allowed.test"),
    )
    manager._sessions["s1"] = session

    monkeypatch.setattr(manager, "capture_dom", lambda *_args, **_kwargs: (True, "<html></html>"))
    monkeypatch.setattr(manager, "capture_screenshot", lambda *_args, **_kwargs: (True, "/tmp/a.png"))

    signal = manager.collect_session_signals("s1", include_dom=True, include_screenshot=True)
    assert signal["dom_capture"]["ok"] is True
    assert signal["screenshot"]["ok"] is True

    gate = SimpleNamespace(enabled=True)
    monkeypatch.setattr("managers.browser_manager.get_hitl_gate", lambda: gate)
    assert manager._sync_hitl_guard("browser_click", "#safe") is None
    blocked = manager._sync_hitl_guard("browser_click", "#delete-submit")
    assert blocked and blocked[0] is False


def test_github_manager_read_remote_file_binary_and_directory_paths() -> None:
    manager = GitHubManager.__new__(GitHubManager)
    manager._repo = SimpleNamespace(
        get_contents=lambda path, **_kwargs: [SimpleNamespace(type="dir", name="src"), SimpleNamespace(type="file", name="README.md")]
        if path == "dir" else SimpleNamespace(name="image.png", decoded_content=b"x")
    )

    ok, listing = manager.read_remote_file("dir")
    assert ok is True and "📂 src" in listing

    ok, message = manager.read_remote_file("image.png")
    assert ok is False
    assert "binary" in message.lower() or "desteklenmeyen" in message.lower()
