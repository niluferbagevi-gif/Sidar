"""
plugins/aws_management_agent.py için birim testleri.
"""
from __future__ import annotations

import json
import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_aws_deps():
    # agent package stub
    if "agent" not in sys.modules:
        pkg = types.ModuleType("agent")
        pkg.__path__ = [str(_proj / "agent")]
        pkg.__package__ = "agent"
        sys.modules["agent"] = pkg

    # agent.core stub
    if "agent.core" not in sys.modules:
        core = types.ModuleType("agent.core")
        core.__path__ = [str(_proj / "agent" / "core")]
        core.__package__ = "agent.core"
        sys.modules["agent.core"] = core
    else:
        c = sys.modules["agent.core"]
        if not hasattr(c, "__path__"):
            c.__path__ = [str(_proj / "agent" / "core")]

    # agent.core.contracts stub
    if "agent.core.contracts" not in sys.modules:
        contracts = types.ModuleType("agent.core.contracts")
        contracts.is_delegation_request = lambda v: False
        contracts.DelegationRequest = type("DelegationRequest", (), {})
        contracts.TaskEnvelope = type("TaskEnvelope", (), {})
        contracts.TaskResult = type("TaskResult", (), {})
        sys.modules["agent.core.contracts"] = contracts

    # config stub
    if "config" not in sys.modules:
        cfg_mod = types.ModuleType("config")

        class _Config:
            AI_PROVIDER = "ollama"
            OLLAMA_MODEL = "qwen2.5-coder:7b"
            BASE_DIR = "/tmp/sidar_test"
            USE_GPU = False
            GPU_DEVICE = 0
            GPU_MIXED_PRECISION = False
            RAG_DIR = "/tmp/sidar_test/rag"
            RAG_TOP_K = 3
            RAG_CHUNK_SIZE = 1000
            RAG_CHUNK_OVERLAP = 200
            SLACK_WEBHOOK_URL = ""
            SLACK_DEFAULT_CHANNEL = "general"

        cfg_mod.Config = _Config
        sys.modules["config"] = cfg_mod

    # core stubs
    if "core" not in sys.modules:
        sys.modules["core"] = types.ModuleType("core")

    llm_stub = types.ModuleType("core.llm_client")
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value="llm yanıtı")
    llm_stub.LLMClient = MagicMock(return_value=mock_llm)
    sys.modules["core.llm_client"] = llm_stub

    # agent.base_agent stub
    if "agent.base_agent" not in sys.modules:
        ba_mod = types.ModuleType("agent.base_agent")

        class _BaseAgent:
            SYSTEM_PROMPT = "You are a specialist agent."

            def __init__(self, cfg=None, *, role_name="base", **kw):
                self.cfg = cfg or sys.modules["config"].Config()
                self.role_name = role_name
                self.llm = MagicMock()
                self.llm.chat = AsyncMock(return_value="llm yanıtı")
                self.tools = {}

            def register_tool(self, name, fn):
                self.tools[name] = fn

            async def call_tool(self, name, arg):
                if name not in self.tools:
                    return f"[HATA] '{name}' aracı bu ajan için tanımlı değil."
                return await self.tools[name](arg)

            async def call_llm(self, msgs, system_prompt=None, temperature=0.3, **kw):
                return "llm yanıtı"

        ba_mod.BaseAgent = _BaseAgent
        sys.modules["agent.base_agent"] = ba_mod

    # plugins package stub
    if "plugins" not in sys.modules:
        plugins_pkg = types.ModuleType("plugins")
        plugins_pkg.__path__ = [str(_proj / "plugins")]
        plugins_pkg.__package__ = "plugins"
        sys.modules["plugins"] = plugins_pkg


def _get_aws_agent():
    _stub_aws_deps()
    sys.modules.pop("plugins.aws_management_agent", None)
    import plugins.aws_management_agent as m
    return m


class TestAWSManagementAgentInit:
    def test_instantiation(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        assert agent is not None

    def test_role_name(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        assert agent.ROLE_NAME == "aws_management"

    def test_command_map_keys(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        assert "ec2" in agent._COMMAND_MAP
        assert "s3" in agent._COMMAND_MAP
        assert "cloudwatch" in agent._COMMAND_MAP


class TestAWSManagementAgentSelectCommand:
    def test_select_ec2_by_ec2_keyword(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("EC2 instance listele")
        assert cmd is not None
        assert "ec2" in cmd

    def test_select_ec2_by_instance_keyword(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("tüm instance'ları göster")
        assert cmd is not None
        assert "ec2" in cmd

    def test_select_ec2_by_sunucu_keyword(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("sunucu listesi")
        assert cmd is not None

    def test_select_s3_by_s3_keyword(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("s3 bucket'larını listele")
        assert cmd is not None
        assert "s3api" in cmd

    def test_select_s3_by_bucket_keyword(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("bucket listesi")
        assert cmd is not None

    def test_select_s3_by_storage_keyword(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("storage nedir")
        assert cmd is not None

    def test_select_cloudwatch_by_alarm_keyword(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("alarm durumları")
        assert cmd is not None
        assert "cloudwatch" in cmd

    def test_select_cloudwatch_by_metric_keyword(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("metric sorgula")
        assert cmd is not None

    def test_select_none_for_unknown(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        cmd = agent._select_command("bilinmeyen görev")
        assert cmd is None

    def test_command_is_copy_not_original(self):
        """_select_command orijinal listeyi değil kopya döndürmeli."""
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        cmd1 = agent._select_command("ec2")
        cmd2 = agent._select_command("ec2")
        assert cmd1 is not cmd2


class TestAWSManagementAgentSummarizeOutput:
    def test_s3_buckets(self):
        m = _get_aws_agent()
        payload = json.dumps({"Buckets": [{"Name": "my-bucket"}, {"Name": "logs-bucket"}]})
        result = m.AWSManagementAgent._summarize_output("s3", payload)
        assert "my-bucket" in result
        assert "S3" in result

    def test_s3_empty_buckets(self):
        m = _get_aws_agent()
        payload = json.dumps({"Buckets": []})
        result = m.AWSManagementAgent._summarize_output("s3", payload)
        assert "bucket bulunamadı" in result

    def test_ec2_instances(self):
        m = _get_aws_agent()
        payload = json.dumps({
            "Reservations": [{
                "Instances": [{"InstanceId": "i-123456", "State": {"Name": "running"}}]
            }]
        })
        result = m.AWSManagementAgent._summarize_output("ec2", payload)
        assert "i-123456" in result
        assert "running" in result

    def test_cloudwatch_alarms(self):
        m = _get_aws_agent()
        payload = json.dumps({
            "MetricAlarms": [{"AlarmName": "cpu-alarm", "StateValue": "OK"}]
        })
        result = m.AWSManagementAgent._summarize_output("cloudwatch", payload)
        assert "cpu-alarm" in result
        assert "CloudWatch" in result

    def test_invalid_json_fallback(self):
        m = _get_aws_agent()
        result = m.AWSManagementAgent._summarize_output("test", "bu json değil!!!")
        assert "AWS yanıtı" in result

    def test_unknown_payload_fallback(self):
        m = _get_aws_agent()
        payload = json.dumps({"UnknownKey": "value"})
        result = m.AWSManagementAgent._summarize_output("test", payload)
        assert "AWS yanıtı" in result


class TestAWSManagementAgentRunTask:
    @pytest.mark.asyncio
    async def test_empty_prompt_returns_message(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        result = await agent.run_task("")
        assert "gerekli" in result

    @pytest.mark.asyncio
    async def test_whitespace_only_prompt(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        result = await agent.run_task("   ")
        assert "gerekli" in result

    @pytest.mark.asyncio
    async def test_no_aws_cli_returns_message(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        with patch("shutil.which", return_value=None):
            result = await agent.run_task("ec2 instance listele")
        assert "AWS CLI" in result

    @pytest.mark.asyncio
    async def test_unknown_task_returns_supported_list(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        with patch("shutil.which", return_value="/usr/bin/aws"):
            result = await agent.run_task("bilinmeyen görev yap")
        assert "Desteklenen" in result or "desteklenen" in result.lower()

    @pytest.mark.asyncio
    async def test_ec2_command_success(self):
        m = _get_aws_agent()
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

    @pytest.mark.asyncio
    async def test_s3_command_success(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        payload = json.dumps({"Buckets": [{"Name": "test-bucket"}]})
        mock_result = MagicMock()
        mock_result.stdout = payload
        with patch("shutil.which", return_value="/usr/bin/aws"), \
             patch("asyncio.to_thread", new=AsyncMock(return_value=mock_result)):
            result = await agent.run_task("s3 bucket listele")
        assert "test-bucket" in result

    @pytest.mark.asyncio
    async def test_command_failure_returns_error(self):
        import subprocess
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        exc = subprocess.CalledProcessError(1, "aws", stderr="AccessDenied")
        with patch("shutil.which", return_value="/usr/bin/aws"), \
             patch("asyncio.to_thread", new=AsyncMock(side_effect=exc)):
            result = await agent.run_task("ec2 instance listele")
        assert "başarısız" in result or "AWS" in result

    @pytest.mark.asyncio
    async def test_generic_exception_returns_error(self):
        m = _get_aws_agent()
        agent = m.AWSManagementAgent()
        with patch("shutil.which", return_value="/usr/bin/aws"), \
             patch("asyncio.to_thread", new=AsyncMock(side_effect=OSError("bağlantı yok"))):
            result = await agent.run_task("cloudwatch alarm listele")
        assert "çalıştırılamadı" in result or "AWS" in result
