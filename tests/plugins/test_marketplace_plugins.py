from __future__ import annotations

import asyncio
import subprocess
import sys
from types import SimpleNamespace

import pytest


class _DummyHTTPX:
    class HTTPStatusError(Exception):
        pass

    class TimeoutException(Exception):
        pass

    class ConnectError(Exception):
        pass


sys.modules.setdefault("httpx", _DummyHTTPX())

from plugins.aws_management_agent import AWSManagementAgent
from plugins.crypto_price_agent import CryptoPriceAgent
from plugins.slack_notification_agent import SlackNotificationAgent
from plugins.upload_agent import UploadAgent


class _DummyHTTPResponse:
    def __init__(self, body: str) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body.encode("utf-8")


def test_upload_agent_handles_empty_and_valid_prompt() -> None:
    agent = UploadAgent()

    assert asyncio.run(agent.run_task("")) == "Boş görev alındı."
    assert asyncio.run(agent.run_task("test.txt dosyasını yükle")) == "UploadAgent: test.txt dosyasını yükle"


def test_crypto_price_agent_supported_symbol_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_urlopen(url: str, timeout: int = 0):
        assert "ids=bitcoin" in url
        assert timeout == 8
        return _DummyHTTPResponse('{"bitcoin": {"usd": 12345}}')

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    agent = CryptoPriceAgent()
    result = asyncio.run(agent.run_task("btc fiyatı nedir"))

    assert result == "BTC güncel fiyatı: $12345"


def test_crypto_price_agent_unsupported_symbol_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = CryptoPriceAgent()

    unsupported = asyncio.run(agent.run_task("doge fiyatı"))
    assert unsupported.startswith("Desteklenmeyen sembol: doge")

    def _failing_urlopen(url: str, timeout: int = 0):
        raise RuntimeError("ağ kapalı")

    monkeypatch.setattr("urllib.request.urlopen", _failing_urlopen)
    failed = asyncio.run(agent.run_task("eth fiyat"))

    assert failed == "ETH fiyatı alınamadı: ağ kapalı"


def test_slack_notification_agent_validates_prompt_and_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = SlackNotificationAgent()

    assert asyncio.run(agent.run_task("")) == "Slack bildirimi göndermek için mesaj gerekli."

    monkeypatch.setattr("config.Config.SLACK_WEBHOOK_URL", "", raising=False)
    assert (
        asyncio.run(agent.run_task("#devops deploy tamam"))
        == "SLACK_WEBHOOK_URL veya SLACK_TOKEN ayarlanmamış. Önce Slack bağlantısını yapılandırın."
    )


def test_slack_notification_agent_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.Config.SLACK_WEBHOOK_URL", "https://hooks.slack.test", raising=False)
    monkeypatch.setattr("config.Config.SLACK_DEFAULT_CHANNEL", "genel", raising=False)

    agent = SlackNotificationAgent()

    async def _ok_to_thread(func, *args, **kwargs):
        _ = func, args, kwargs
        return _DummyHTTPResponse("ok")

    monkeypatch.setattr("asyncio.to_thread", _ok_to_thread)
    ok_result = asyncio.run(agent.run_task("#alerts servis ayağa kalktı"))
    assert ok_result == "#alerts kanalına bildirim gönderildi: servis ayağa kalktı (ok)"

    async def _fail_to_thread(func, *args, **kwargs):
        _ = func, args, kwargs
        raise RuntimeError("webhook timeout")

    monkeypatch.setattr("asyncio.to_thread", _fail_to_thread)
    fail_result = asyncio.run(agent.run_task("yeniden dene"))
    assert fail_result == "#genel kanalına bildirim gönderilemedi: webhook timeout"


def test_aws_management_agent_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = AWSManagementAgent()

    assert asyncio.run(agent.run_task("")) == "AWS işlemi için görev açıklaması gerekli."

    monkeypatch.setattr("shutil.which", lambda _: None)
    missing_cli = asyncio.run(agent.run_task("ec2 instance listele"))
    assert "AWS CLI bulunamadı" in missing_cli

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/aws")
    unsupported = asyncio.run(agent.run_task("lambda fonksiyonlarını getir"))
    assert unsupported.startswith("Desteklenen AWS görevleri")

    async def _called_process(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "aws", stderr="forbidden")

    monkeypatch.setattr("asyncio.to_thread", _called_process)
    called_error = asyncio.run(agent.run_task("ec2 durum"))
    assert called_error == "AWS komutu başarısız oldu: forbidden"

    async def _exception_process(*args, **kwargs):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr("asyncio.to_thread", _exception_process)
    runtime_error = asyncio.run(agent.run_task("s3 bucket"))
    assert runtime_error == "AWS komutu çalıştırılamadı: spawn failed"

    async def _ok_process(*args, **kwargs):
        return SimpleNamespace(stdout='{"Buckets": [{"Name": "alpha"}, {"Name": "beta"}]}')

    monkeypatch.setattr("asyncio.to_thread", _ok_process)
    ok = asyncio.run(agent.run_task("s3 bucket"))
    assert ok == "S3 bucket envanteri: alpha, beta"


def test_aws_management_agent_summarize_output_variants() -> None:
    assert AWSManagementAgent._summarize_output("test", "not-json") == "AWS yanıtı (test): not-json"

    ec2_payload = '{"Reservations": [{"Instances": [{"InstanceId": "i-1", "State": {"Name": "running"}}]}]}'
    assert AWSManagementAgent._summarize_output("ec2", ec2_payload) == "EC2 instance envanteri: i-1 (running)"

    cloudwatch_payload = '{"MetricAlarms": [{"AlarmName": "cpu-high", "StateValue": "ALARM"}]}'
    assert AWSManagementAgent._summarize_output("cw", cloudwatch_payload) == "CloudWatch alarmları: cpu-high=ALARM"
