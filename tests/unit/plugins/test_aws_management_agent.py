import asyncio
import subprocess
import sys
import types

# Test ortamında ağır bağımlılıkları atlamak için minimal BaseAgent stub'ı.
if "agent.base_agent" not in sys.modules:
    fake_base_agent = types.ModuleType("agent.base_agent")

    class BaseAgent:  # pragma: no cover - test helper
        pass

    fake_base_agent.BaseAgent = BaseAgent
    sys.modules["agent.base_agent"] = fake_base_agent

from plugins.aws_management_agent import AWSManagementAgent


def _agent() -> AWSManagementAgent:
    return AWSManagementAgent.__new__(AWSManagementAgent)


def test_select_command_detects_supported_keywords() -> None:
    agent = _agent()

    assert agent._select_command("ec2 instance list") == agent._COMMAND_MAP["ec2"]
    assert agent._select_command("show s3 buckets") == agent._COMMAND_MAP["s3"]
    assert agent._select_command("cloudwatch alarm status") == agent._COMMAND_MAP["cloudwatch"]
    assert agent._select_command("unknown") is None


def test_summarize_output_for_s3_ec2_cloudwatch_json_and_fallbacks() -> None:
    s3 = AWSManagementAgent._summarize_output("s3", '{"Buckets":[{"Name":"a"},{"Name":"b"}]}')
    ec2 = AWSManagementAgent._summarize_output(
        "ec2",
        '{"Reservations":[{"Instances":[{"InstanceId":"i-1","State":{"Name":"running"}}]}]}',
    )
    cw = AWSManagementAgent._summarize_output(
        "cloudwatch",
        '{"MetricAlarms":[{"AlarmName":"HighCPU","StateValue":"ALARM"}]}',
    )
    invalid = AWSManagementAgent._summarize_output("raw", " not-json output ")

    assert s3 == "S3 bucket envanteri: a, b"
    assert ec2 == "EC2 instance envanteri: i-1 (running)"
    assert cw == "CloudWatch alarmları: HighCPU=ALARM"
    assert invalid.startswith("AWS yanıtı (raw):")


def test_run_task_requires_prompt() -> None:
    agent = _agent()

    assert asyncio.run(agent.run_task("  ")) == "AWS işlemi için görev açıklaması gerekli."


def test_run_task_requires_aws_cli(monkeypatch) -> None:
    agent = _agent()
    monkeypatch.setattr("plugins.aws_management_agent.shutil.which", lambda _name: None)

    result = asyncio.run(agent.run_task("ec2 list"))

    assert "AWS CLI bulunamadı" in result


def test_run_task_returns_supported_message_for_unknown_command(monkeypatch) -> None:
    agent = _agent()
    monkeypatch.setattr("plugins.aws_management_agent.shutil.which", lambda _name: "/usr/bin/aws")

    result = asyncio.run(agent.run_task("lambda invoke"))

    assert "Desteklenen AWS görevleri" in result


def test_run_task_executes_command_and_summarizes(monkeypatch) -> None:
    agent = _agent()
    monkeypatch.setattr("plugins.aws_management_agent.shutil.which", lambda _name: "/usr/bin/aws")

    def _fake_run(command, check, capture_output, text, timeout, env):
        assert command == agent._COMMAND_MAP["ec2"]
        assert check is True
        assert capture_output is True
        assert text is True
        assert timeout == 20
        assert env["AWS_PAGER"] == ""
        return subprocess.CompletedProcess(command, 0, stdout='{"Reservations": []}', stderr="")

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("plugins.aws_management_agent.asyncio.to_thread", _fake_to_thread)
    monkeypatch.setattr("plugins.aws_management_agent.subprocess.run", _fake_run)

    result = asyncio.run(agent.run_task("ec2 list"))

    assert result.startswith("AWS yanıtı (ec2 list):")


def test_run_task_handles_called_process_error(monkeypatch) -> None:
    agent = _agent()
    monkeypatch.setattr("plugins.aws_management_agent.shutil.which", lambda _name: "/usr/bin/aws")

    def _raise_called_process_error(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["aws"], stderr="boom")

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("plugins.aws_management_agent.asyncio.to_thread", _fake_to_thread)
    monkeypatch.setattr("plugins.aws_management_agent.subprocess.run", _raise_called_process_error)

    result = asyncio.run(agent.run_task("s3 list"))

    assert result == "AWS komutu başarısız oldu: boom"


def test_run_task_handles_unexpected_error(monkeypatch) -> None:
    agent = _agent()
    monkeypatch.setattr("plugins.aws_management_agent.shutil.which", lambda _name: "/usr/bin/aws")

    async def _raise_runtime_error(_func, *_args, **_kwargs):
        raise RuntimeError("executor issue")

    monkeypatch.setattr("plugins.aws_management_agent.asyncio.to_thread", _raise_runtime_error)

    result = asyncio.run(agent.run_task("cloudwatch alarms"))

    assert result == "AWS komutu çalıştırılamadı: executor issue"
