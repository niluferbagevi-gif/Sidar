import asyncio
import sys
import types


class _FakeBaseAgent:
    def __init__(self, cfg=None, *, role_name="base"):
        self.cfg = cfg or types.SimpleNamespace()
        self.role_name = role_name


sys.modules.setdefault("agent.base_agent", types.SimpleNamespace(BaseAgent=_FakeBaseAgent))

from plugins.slack_notification_agent import SlackNotificationAgent


class _Cfg:
    SLACK_DEFAULT_CHANNEL = "genel"
    SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/T/X/Y"


class _FakeResponse:
    def __init__(self, body: str):
        self._body = body

    def read(self):
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_slack_notification_agent_requires_message():
    agent = SlackNotificationAgent(cfg=_Cfg())
    assert asyncio.run(agent.run_task("   ")) == "Slack bildirimi göndermek için mesaj gerekli."


def test_slack_notification_agent_missing_webhook():
    cfg = _Cfg()
    cfg.SLACK_WEBHOOK_URL = ""
    agent = SlackNotificationAgent(cfg=cfg)
    result = asyncio.run(agent.run_task("hello"))
    assert "SLACK_WEBHOOK_URL" in result


def test_slack_notification_agent_success(monkeypatch):
    agent = SlackNotificationAgent(cfg=_Cfg())

    def _fake_urlopen(req, timeout=0):
        assert req.method == "POST"
        assert timeout == 10
        return _FakeResponse("ok")

    async def _fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("plugins.slack_notification_agent.urllib.request.urlopen", _fake_urlopen)
    monkeypatch.setattr("plugins.slack_notification_agent.asyncio.to_thread", _fake_to_thread)

    result = asyncio.run(agent.run_task("#dev deploy tamam"))
    assert "#dev kanalına bildirim gönderildi" in result


def test_slack_notification_agent_error(monkeypatch):
    agent = SlackNotificationAgent(cfg=_Cfg())

    async def _fake_to_thread(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("plugins.slack_notification_agent.asyncio.to_thread", _fake_to_thread)
    result = asyncio.run(agent.run_task("hello"))
    assert "bildirim gönderilemedi" in result


def test_slack_notification_helpers():
    assert SlackNotificationAgent._extract_channel("#ops test") == "ops"
    assert SlackNotificationAgent._extract_channel("no channel") == ""
    assert SlackNotificationAgent._extract_message("#ops ") == "SİDAR tarafından tetiklenen Slack bildirimi."
