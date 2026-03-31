"""
plugins/slack_notification_agent.py için birim testleri.
"""
from __future__ import annotations

import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_proj = _pl.Path(__file__).parent.parent


def _make_config(webhook_url="", default_channel="general"):
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
        SLACK_WEBHOOK_URL = webhook_url
        SLACK_DEFAULT_CHANNEL = default_channel

    return _Config()


def _stub_slack_deps(webhook_url=""):
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
        SLACK_WEBHOOK_URL = webhook_url
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


def _get_slack_agent(webhook_url=""):
    _stub_slack_deps(webhook_url=webhook_url)
    sys.modules.pop("plugins.slack_notification_agent", None)
    sys.modules.pop("agent.base_agent", None)
    import plugins.slack_notification_agent as m
    return m


class TestSlackNotificationAgentInit:
    def test_instantiation(self):
        m = _get_slack_agent()
        assert m.SlackNotificationAgent() is not None

    def test_role_name(self):
        m = _get_slack_agent()
        agent = m.SlackNotificationAgent()
        assert agent.ROLE_NAME == "slack_notifications"


class TestSlackExtractChannel:
    def test_extract_channel_with_hash(self):
        m = _get_slack_agent()
        channel = m.SlackNotificationAgent._extract_channel("bunu #genel kanalına gönder")
        assert channel == "genel"

    def test_extract_channel_general(self):
        m = _get_slack_agent()
        channel = m.SlackNotificationAgent._extract_channel("#general bildirim")
        assert channel == "general"

    def test_extract_channel_missing(self):
        m = _get_slack_agent()
        channel = m.SlackNotificationAgent._extract_channel("kanal belirtilmemiş mesaj")
        assert channel == ""

    def test_extract_channel_with_numbers(self):
        m = _get_slack_agent()
        channel = m.SlackNotificationAgent._extract_channel("#dev-ops123 bildirimi")
        assert channel == "dev-ops123"

    def test_extract_channel_short_ignored(self):
        """2 karakterden kısa kanal adları eşleşmemeli."""
        m = _get_slack_agent()
        channel = m.SlackNotificationAgent._extract_channel("#a mesaj")
        assert channel == ""


class TestSlackExtractMessage:
    def test_removes_channel_from_message(self):
        m = _get_slack_agent()
        msg = m.SlackNotificationAgent._extract_message("#general sunucu çöktü!")
        assert "#general" not in msg
        assert "sunucu çöktü" in msg

    def test_empty_prompt_returns_default(self):
        m = _get_slack_agent()
        msg = m.SlackNotificationAgent._extract_message("")
        assert "SİDAR" in msg or len(msg) > 0

    def test_only_channel_returns_default(self):
        m = _get_slack_agent()
        msg = m.SlackNotificationAgent._extract_message("#general")
        assert "SİDAR" in msg or len(msg) > 0

    def test_plain_message_unchanged(self):
        m = _get_slack_agent()
        msg = m.SlackNotificationAgent._extract_message("deploy tamamlandı")
        assert "deploy tamamlandı" in msg


class TestSlackFormatResponse:
    def test_success_with_channel(self):
        m = _get_slack_agent()
        result = m.SlackNotificationAgent._format_response(True, "ok", "alerts", "test mesajı")
        assert "#alerts" in result
        assert "gönderildi" in result

    def test_failure_with_channel(self):
        m = _get_slack_agent()
        result = m.SlackNotificationAgent._format_response(False, "bağlantı hatası", "alerts", "test")
        assert "gönderilemedi" in result
        assert "bağlantı hatası" in result

    def test_success_without_channel(self):
        m = _get_slack_agent()
        result = m.SlackNotificationAgent._format_response(True, "ok", "", "mesaj")
        assert "varsayılan" in result
        assert "gönderildi" in result

    def test_failure_without_channel(self):
        m = _get_slack_agent()
        result = m.SlackNotificationAgent._format_response(False, "hata", "", "mesaj")
        assert "gönderilemedi" in result

    def test_message_truncated_to_140(self):
        m = _get_slack_agent()
        long_msg = "x" * 200
        result = m.SlackNotificationAgent._format_response(True, "ok", "ch", long_msg)
        # 140 karakter sınırı uygulanmış olmalı
        assert "x" * 141 not in result


class TestSlackNotificationAgentRunTask:
    def test_empty_prompt_returns_message(self):
        async def _run():
            m = _get_slack_agent()
            agent = m.SlackNotificationAgent()
            result = await agent.run_task("")
            assert "mesaj gerekli" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_whitespace_only_prompt(self):
        async def _run():
            m = _get_slack_agent()
            agent = m.SlackNotificationAgent()
            result = await agent.run_task("   ")
            assert "mesaj gerekli" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_no_webhook_returns_config_warning(self):
        async def _run():
            m = _get_slack_agent()
            agent = m.SlackNotificationAgent()
            agent.cfg.SLACK_WEBHOOK_URL = ""
            result = await agent.run_task("sunucu çöktü bildirimi gönder")
            assert "SLACK_WEBHOOK_URL" in result or "yapılandırın" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_send_success(self):
        async def _run():
            m = _get_slack_agent()
            agent = m.SlackNotificationAgent()
            agent.cfg.SLACK_WEBHOOK_URL = "https://hooks.slack.com/fake"

            class _MockResp:
                def read(self):
                    return b"ok"
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    pass

            with patch("asyncio.to_thread", new=AsyncMock(return_value=_MockResp())):
                result = await agent.run_task("deploy tamamlandı")
            assert "gönderildi" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_send_with_channel(self):
        async def _run():
            m = _get_slack_agent()
            agent = m.SlackNotificationAgent()
            agent.cfg.SLACK_WEBHOOK_URL = "https://hooks.slack.com/fake"

            class _MockResp:
                def read(self):
                    return b"ok"
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    pass

            with patch("asyncio.to_thread", new=AsyncMock(return_value=_MockResp())):
                result = await agent.run_task("#alerts sunucu uyarısı")
            assert "alerts" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_send_failure_returns_error(self):
        async def _run():
            m = _get_slack_agent()
            agent = m.SlackNotificationAgent()
            agent.cfg.SLACK_WEBHOOK_URL = "https://hooks.slack.com/fake"

            with patch("asyncio.to_thread", new=AsyncMock(side_effect=OSError("bağlantı reddedildi"))):
                result = await agent.run_task("test bildirimi")
            assert "gönderilemedi" in result or "bağlantı" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

