import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from tests.test_code_manager_runtime import CM_MOD, DummySecurity, FULL
from tests.test_slack_jira_teams import JiraManager, SlackManager, _jira_mod, _run, _slack_mod


def test_slack_init_sdk_construction_error_and_http_auth_failures(monkeypatch):
    slack_sdk = types.ModuleType("slack_sdk")
    slack_sdk.WebClient = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("sdk init boom"))
    monkeypatch.setitem(sys.modules, "slack_sdk", slack_sdk)

    mgr = SlackManager(token="xoxb-test", webhook_url="https://hooks.slack.com/test")
    assert mgr.is_available() is True
    assert mgr._webhook_only is True

    webhook_mgr = SlackManager.__new__(SlackManager)
    webhook_mgr.webhook_url = "https://hooks.slack.com/test"
    webhook_mgr._available = True
    webhook_mgr._webhook_only = True
    webhook_mgr._client = None

    for status_code, body in ((401, "unauthorized"), (429, "rate_limited")):
        mock_resp = MagicMock(status_code=status_code, text=body)
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch.object(_slack_mod, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            ok, err = _run(webhook_mgr.send_webhook(text="Deploy failed"))

        assert ok is False
        assert f"HTTP {status_code}" in err
        assert body in err


def test_jira_request_http_401_and_create_issue_optional_fields():
    mgr = JiraManager.__new__(JiraManager)
    mgr.url = "https://example.atlassian.net"
    mgr.token = "t"
    mgr.email = "u@example.com"
    mgr.default_project = "SID"
    mgr._available = True
    mgr._auth = ("u@example.com", "t")
    mgr._headers = {"Accept": "application/json", "Content-Type": "application/json"}

    mock_resp = MagicMock(status_code=401, text="Unauthorized", content=b"Unauthorized")
    mock_client = MagicMock()
    mock_client.request = AsyncMock(return_value=mock_resp)

    with patch.object(_jira_mod, "httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
        ok, data, err = _run(mgr._request("GET", "issue/SID-1"))

    assert ok is False
    assert data is None
    assert "HTTP 401" in err

    captured = {}

    async def _fake_request(method, endpoint, **kwargs):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["json"] = kwargs.get("json")
        return True, {"key": "SID-1"}, ""

    mgr._request = _fake_request
    ok, data, err = _run(
        mgr.create_issue(
            "Need auth hardening",
            description="401 and 429 branches",
            labels=["security", "coverage"],
            assignee_account_id="acct-123",
        )
    )

    assert ok is True
    assert data["key"] == "SID-1"
    assert err == ""
    fields = captured["json"]["fields"]
    assert fields["labels"] == ["security", "coverage"]
    assert fields["assignee"] == {"accountId": "acct-123"}


def test_code_manager_sandbox_rejects_outside_cwd_and_handles_runtime_and_missing_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(CM_MOD.CodeManager, "_init_docker", lambda self: None)
    sec = DummySecurity(tmp_path, can_execute=True, level=FULL)
    mgr = CM_MOD.CodeManager(sec, tmp_path)

    monkeypatch.setattr(CM_MOD.shutil, "which", lambda _name: "/usr/bin/docker")
    mgr.security.is_path_under = lambda path, base: False
    outside = tmp_path.parent
    ok, msg = mgr.run_shell_in_sandbox("echo hi", cwd=str(outside))
    assert ok is False
    assert "proje kökü dışında" in msg

    mgr.security.is_path_under = lambda path, base: True
    mgr._resolve_runtime = lambda: "runsc"
    seen = {}

    def _missing_binary(cmd, **kwargs):
        seen["cmd"] = cmd
        raise FileNotFoundError("docker missing")

    monkeypatch.setattr(CM_MOD.subprocess, "run", _missing_binary)
    ok, msg = mgr.run_shell_in_sandbox("pytest -q", cwd=str(tmp_path))
    assert ok is False
    assert "Docker CLI bulunamadı" in msg
    assert "--runtime" in seen["cmd"]
    assert "runsc" in seen["cmd"]