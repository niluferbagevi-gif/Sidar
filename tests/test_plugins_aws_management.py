"""
plugins/aws_management_agent.py için birim testleri.
"""
from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

def _get_aws_agent(stub_aws_plugin_dependencies):
    del stub_aws_plugin_dependencies
    sys.modules.pop("plugins.aws_management_agent", None)
    import plugins.aws_management_agent as m
    return m


class TestAWSManagementAgentInit:
    def test_instantiation(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        assert agent is not None

    def test_role_name(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        assert agent.ROLE_NAME == "aws_management"

    def test_command_map_keys(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        assert "ec2" in agent._COMMAND_MAP
        assert "s3" in agent._COMMAND_MAP
        assert "cloudwatch" in agent._COMMAND_MAP


class TestAWSManagementAgentSelectCommand:
    def test_select_ec2_by_ec2_keyword(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("EC2 instance listele")
        assert cmd is not None
        assert "ec2" in cmd

    def test_select_ec2_by_instance_keyword(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("tüm instance'ları göster")
        assert cmd is not None
        assert "ec2" in cmd

    def test_select_ec2_by_sunucu_keyword(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("sunucu listesi")
        assert cmd is not None

    def test_select_s3_by_s3_keyword(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("s3 bucket'larını listele")
        assert cmd is not None
        assert "s3api" in cmd

    def test_select_s3_by_bucket_keyword(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("bucket listesi")
        assert cmd is not None

    def test_select_s3_by_storage_keyword(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("storage nedir")
        assert cmd is not None

    def test_select_cloudwatch_by_alarm_keyword(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("alarm durumları")
        assert cmd is not None
        assert "cloudwatch" in cmd

    def test_select_cloudwatch_by_metric_keyword(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("metric sorgula")
        assert cmd is not None

    def test_select_none_for_unknown(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("bilinmeyen görev")
        assert cmd is None

    def test_command_is_copy_not_original(self, stub_aws_plugin_dependencies):
        """_select_command orijinal listeyi değil kopya döndürmeli."""
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        agent = m.AWSManagementAgent()
        cmd1 = agent._select_command("ec2")
        cmd2 = agent._select_command("ec2")
        assert cmd1 is not cmd2


class TestAWSManagementAgentSummarizeOutput:
    def test_s3_buckets(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        payload = json.dumps({"Buckets": [{"Name": "my-bucket"}, {"Name": "logs-bucket"}]})
        result = m.AWSManagementAgent._summarize_output("s3", payload)
        assert "my-bucket" in result
        assert "S3" in result

    def test_s3_empty_buckets(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        payload = json.dumps({"Buckets": []})
        result = m.AWSManagementAgent._summarize_output("s3", payload)
        assert "bucket bulunamadı" in result

    def test_ec2_instances(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        payload = json.dumps({
            "Reservations": [{
                "Instances": [{"InstanceId": "i-123456", "State": {"Name": "running"}}]
            }]
        })
        result = m.AWSManagementAgent._summarize_output("ec2", payload)
        assert "i-123456" in result
        assert "running" in result

    def test_cloudwatch_alarms(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        payload = json.dumps({
            "MetricAlarms": [{"AlarmName": "cpu-alarm", "StateValue": "OK"}]
        })
        result = m.AWSManagementAgent._summarize_output("cloudwatch", payload)
        assert "cpu-alarm" in result
        assert "CloudWatch" in result

    def test_invalid_json_fallback(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        result = m.AWSManagementAgent._summarize_output("test", "bu json değil!!!")
        assert "AWS yanıtı" in result

    def test_unknown_payload_fallback(self, stub_aws_plugin_dependencies):
        m = _get_aws_agent(stub_aws_plugin_dependencies)
        payload = json.dumps({"UnknownKey": "value"})
        result = m.AWSManagementAgent._summarize_output("test", payload)
        assert "AWS yanıtı" in result


class TestAWSManagementAgentRunTask:
    def test_empty_prompt_returns_message(self, stub_aws_plugin_dependencies):
        async def _run():
            m = _get_aws_agent(stub_aws_plugin_dependencies)
            agent = m.AWSManagementAgent()
            result = await agent.run_task("")
            assert "gerekli" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_whitespace_only_prompt(self, stub_aws_plugin_dependencies):
        async def _run():
            m = _get_aws_agent(stub_aws_plugin_dependencies)
            agent = m.AWSManagementAgent()
            result = await agent.run_task("   ")
            assert "gerekli" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_no_aws_cli_returns_message(self, stub_aws_plugin_dependencies):
        async def _run():
            m = _get_aws_agent(stub_aws_plugin_dependencies)
            agent = m.AWSManagementAgent()
            with patch("shutil.which", return_value=None):
                result = await agent.run_task("ec2 instance listele")
            assert "AWS CLI" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_unknown_task_returns_supported_list(self, stub_aws_plugin_dependencies):
        async def _run():
            m = _get_aws_agent(stub_aws_plugin_dependencies)
            agent = m.AWSManagementAgent()
            with patch("shutil.which", return_value="/usr/bin/aws"):
                result = await agent.run_task("bilinmeyen görev yap")
            assert "Desteklenen" in result or "desteklenen" in result.lower()
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_ec2_command_success(self, stub_aws_plugin_dependencies):
        async def _run():
            m = _get_aws_agent(stub_aws_plugin_dependencies)
            agent = m.AWSManagementAgent()
            payload = json.dumps({
                "Reservations": [{"Instances": [{"InstanceId": "i-abc", "State": {"Name": "running"}}]}]
            })
            mock_result = MagicMock()
            mock_result.stdout = payload
            with patch("shutil.which", return_value="/usr/bin/aws"), \
                 patch("asyncio.to_thread", new=AsyncMock(return_value=mock_result)):
                result = await agent.run_task("ec2 instance listele")
            assert "i-abc" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_s3_command_success(self, stub_aws_plugin_dependencies):
        async def _run():
            m = _get_aws_agent(stub_aws_plugin_dependencies)
            agent = m.AWSManagementAgent()
            payload = json.dumps({"Buckets": [{"Name": "test-bucket"}]})
            mock_result = MagicMock()
            mock_result.stdout = payload
            with patch("shutil.which", return_value="/usr/bin/aws"), \
                 patch("asyncio.to_thread", new=AsyncMock(return_value=mock_result)):
                result = await agent.run_task("s3 bucket listele")
            assert "test-bucket" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_command_failure_returns_error(self, stub_aws_plugin_dependencies):
        async def _run():
            import subprocess
            m = _get_aws_agent(stub_aws_plugin_dependencies)
            agent = m.AWSManagementAgent()
            exc = subprocess.CalledProcessError(1, "aws", stderr="AccessDenied")
            with patch("shutil.which", return_value="/usr/bin/aws"), \
                 patch("asyncio.to_thread", new=AsyncMock(side_effect=exc)):
                result = await agent.run_task("ec2 instance listele")
            assert "başarısız" in result or "AWS" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_generic_exception_returns_error(self, stub_aws_plugin_dependencies):
        async def _run():
            m = _get_aws_agent(stub_aws_plugin_dependencies)
            agent = m.AWSManagementAgent()
            with patch("shutil.which", return_value="/usr/bin/aws"), \
                 patch("asyncio.to_thread", new=AsyncMock(side_effect=OSError("bağlantı yok"))):
                result = await agent.run_task("cloudwatch alarm listele")
            assert "çalıştırılamadı" in result or "AWS" in result
        import asyncio as _asyncio
        _asyncio.run(_run())
