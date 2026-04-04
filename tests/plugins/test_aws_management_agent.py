import asyncio
import subprocess
import sys
import types


class _FakeBaseAgent:
    def __init__(self, cfg=None, *, role_name="base"):
        self.cfg = cfg or types.SimpleNamespace()
        self.role_name = role_name


sys.modules.setdefault("agent.base_agent", types.SimpleNamespace(BaseAgent=_FakeBaseAgent))

from plugins.aws_management_agent import AWSManagementAgent


def test_aws_management_agent_requires_prompt():
    agent = AWSManagementAgent()
    assert asyncio.run(agent.run_task("")) == "AWS işlemi için görev açıklaması gerekli."


def test_aws_management_agent_missing_cli(monkeypatch):
    agent = AWSManagementAgent()
    monkeypatch.setattr("plugins.aws_management_agent.shutil.which", lambda *_: None)
    result = asyncio.run(agent.run_task("ec2 listele"))
    assert "AWS CLI bulunamadı" in result


def test_aws_management_agent_unsupported_command(monkeypatch):
    agent = AWSManagementAgent()
    monkeypatch.setattr("plugins.aws_management_agent.shutil.which", lambda *_: "/usr/bin/aws")
    result = asyncio.run(agent.run_task("unknown task"))
    assert "Desteklenen AWS görevleri" in result


def test_aws_management_agent_subprocess_error(monkeypatch):
    agent = AWSManagementAgent()
    monkeypatch.setattr("plugins.aws_management_agent.shutil.which", lambda *_: "/usr/bin/aws")

    def _raise(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["aws"], stderr="failed")

    async def _fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("plugins.aws_management_agent.subprocess.run", _raise)
    monkeypatch.setattr("plugins.aws_management_agent.asyncio.to_thread", _fake_to_thread)
    result = asyncio.run(agent.run_task("s3 listele"))
    assert result == "AWS komutu başarısız oldu: failed"


def test_aws_management_agent_unexpected_error(monkeypatch):
    agent = AWSManagementAgent()
    monkeypatch.setattr("plugins.aws_management_agent.shutil.which", lambda *_: "/usr/bin/aws")

    def _raise_runtime(*_args, **_kwargs):
        raise RuntimeError("boom")

    async def _fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("plugins.aws_management_agent.subprocess.run", _raise_runtime)
    monkeypatch.setattr("plugins.aws_management_agent.asyncio.to_thread", _fake_to_thread)
    result = asyncio.run(agent.run_task("ec2 listele"))
    assert result == "AWS komutu çalıştırılamadı: boom"


def test_aws_management_agent_success_path(monkeypatch):
    agent = AWSManagementAgent()
    monkeypatch.setattr("plugins.aws_management_agent.shutil.which", lambda *_: "/usr/bin/aws")

    class _Done:
        stdout = '{"Buckets":[{"Name":"one"}]}'

    async def _fake_to_thread(_fn, *_args, **_kwargs):
        return _Done()

    monkeypatch.setattr("plugins.aws_management_agent.asyncio.to_thread", _fake_to_thread)
    result = asyncio.run(agent.run_task("s3 bucket"))
    assert result == "S3 bucket envanteri: one"


def test_aws_select_command_and_summarize():
    agent = AWSManagementAgent()
    assert agent._select_command("ec2 instance") is not None
    assert agent._select_command("cloudwatch alarm") is not None
    assert agent._select_command("?") is None
    assert "EC2 instance envanteri" in agent._summarize_output(
        "ec2",
        '{"Reservations":[{"Instances":[{"InstanceId":"i-1","State":{"Name":"running"}}]}]}',
    )
    assert "CloudWatch alarmları" in agent._summarize_output(
        "cw",
        '{"MetricAlarms":[{"AlarmName":"high-cpu","StateValue":"ALARM"}]}',
    )
    assert "AWS yanıtı" in agent._summarize_output("raw", "not-json")
    assert 'AWS yanıtı (raw): {"Other": "value"}' == agent._summarize_output("raw", '{"Other":"value"}')
