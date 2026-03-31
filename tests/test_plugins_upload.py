"""
plugins/upload_agent.py için birim testleri.
"""
from __future__ import annotations

import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_upload_deps():
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


def _get_upload_agent():
    _stub_upload_deps()
    sys.modules.pop("plugins.upload_agent", None)
    import plugins.upload_agent as m
    return m


class TestUploadAgentInit:
    def test_instantiation(self):
        m = _get_upload_agent()
        assert m.UploadAgent() is not None

    def test_is_base_agent_subclass(self):
        m = _get_upload_agent()
        base_agent_cls = sys.modules["agent.base_agent"].BaseAgent
        assert issubclass(m.UploadAgent, base_agent_cls)

    def test_has_run_task_method(self):
        m = _get_upload_agent()
        assert callable(getattr(m.UploadAgent, "run_task", None))


class TestUploadAgentRunTask:
    def test_empty_prompt_returns_message(self):
        async def _run():
            m = _get_upload_agent()
            agent = m.UploadAgent()
            result = await agent.run_task("")
            assert "Boş görev" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_whitespace_only_prompt(self):
        async def _run():
            m = _get_upload_agent()
            agent = m.UploadAgent()
            result = await agent.run_task("   ")
            assert "Boş görev" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_valid_prompt_echoed_back(self):
        async def _run():
            m = _get_upload_agent()
            agent = m.UploadAgent()
            result = await agent.run_task("dosya yükle")
            assert "dosya yükle" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_result_contains_agent_prefix(self):
        async def _run():
            m = _get_upload_agent()
            agent = m.UploadAgent()
            result = await agent.run_task("test görevi")
            assert "UploadAgent" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_prompt_preserved_in_result(self):
        async def _run():
            m = _get_upload_agent()
            agent = m.UploadAgent()
            prompt = "plugin yükleme işlemi başlat"
            result = await agent.run_task(prompt)
            assert prompt in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_strips_whitespace_from_prompt(self):
        async def _run():
            m = _get_upload_agent()
            agent = m.UploadAgent()
            result = await agent.run_task("  temizlenmiş görev  ")
            assert "temizlenmiş görev" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_returns_string(self):
        async def _run():
            m = _get_upload_agent()
            agent = m.UploadAgent()
            result = await agent.run_task("herhangi bir görev")
            assert isinstance(result, str)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_non_empty_result_for_valid_task(self):
        async def _run():
            m = _get_upload_agent()
            agent = m.UploadAgent()
            result = await agent.run_task("yükleme görevi")
            assert len(result) > 0
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_multiple_calls_independent(self):
        async def _run():
            m = _get_upload_agent()
            agent = m.UploadAgent()
            r1 = await agent.run_task("görev 1")
            r2 = await agent.run_task("görev 2")
            assert "görev 1" in r1
            assert "görev 2" in r2
            assert r1 != r2
        import asyncio as _asyncio
        _asyncio.run(_run())

