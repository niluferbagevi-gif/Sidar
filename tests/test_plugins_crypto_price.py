"""
plugins/crypto_price_agent.py için birim testleri.
"""
from __future__ import annotations

import json
import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock, patch, MagicMock
from io import BytesIO

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_crypto_deps():
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


def _get_crypto_agent():
    _stub_crypto_deps()
    sys.modules.pop("plugins.crypto_price_agent", None)
    import plugins.crypto_price_agent as m
    return m


class _MockResponse:
    """urllib.request.urlopen için basit mock context manager."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestCryptoPriceAgentInit:
    def test_instantiation(self):
        m = _get_crypto_agent()
        assert m.CryptoPriceAgent() is not None

    def test_symbol_map_contains_btc(self):
        m = _get_crypto_agent()
        assert "btc" in m.CryptoPriceAgent.SYMBOL_MAP
        assert m.CryptoPriceAgent.SYMBOL_MAP["btc"] == "bitcoin"

    def test_symbol_map_contains_eth(self):
        m = _get_crypto_agent()
        assert "eth" in m.CryptoPriceAgent.SYMBOL_MAP
        assert m.CryptoPriceAgent.SYMBOL_MAP["eth"] == "ethereum"

    def test_symbol_map_contains_sol(self):
        m = _get_crypto_agent()
        assert "sol" in m.CryptoPriceAgent.SYMBOL_MAP
        assert m.CryptoPriceAgent.SYMBOL_MAP["sol"] == "solana"

    def test_symbol_map_full_names(self):
        m = _get_crypto_agent()
        assert m.CryptoPriceAgent.SYMBOL_MAP.get("bitcoin") == "bitcoin"
        assert m.CryptoPriceAgent.SYMBOL_MAP.get("ethereum") == "ethereum"
        assert m.CryptoPriceAgent.SYMBOL_MAP.get("solana") == "solana"


class TestCryptoPriceAgentExtractSymbol:
    def test_extract_btc(self):
        m = _get_crypto_agent()
        assert m.CryptoPriceAgent._extract_symbol("BTC fiyatı nedir?") == "btc"

    def test_extract_eth(self):
        m = _get_crypto_agent()
        assert m.CryptoPriceAgent._extract_symbol("ethereum fiyatı") == "ethereum"

    def test_extract_first_match(self):
        m = _get_crypto_agent()
        result = m.CryptoPriceAgent._extract_symbol("bitcoin ve ethereum")
        assert result == "bitcoin"

    def test_empty_prompt_defaults_btc(self):
        m = _get_crypto_agent()
        assert m.CryptoPriceAgent._extract_symbol("") == "btc"

    def test_none_like_empty_string(self):
        m = _get_crypto_agent()
        # boş string BTC döndürmeli
        result = m.CryptoPriceAgent._extract_symbol("")
        assert result == "btc"

    def test_extracts_lowercase(self):
        m = _get_crypto_agent()
        result = m.CryptoPriceAgent._extract_symbol("SOL fiyatı nedir?")
        assert result == "sol"


class TestCryptoPriceAgentRunTask:
    @pytest.mark.asyncio
    async def test_unsupported_symbol_returns_message(self):
        m = _get_crypto_agent()
        agent = m.CryptoPriceAgent()
        result = await agent.run_task("doge fiyatı nedir?")
        assert "Desteklenmeyen" in result or "desteklenmeyen" in result.lower()

    @pytest.mark.asyncio
    async def test_btc_price_success(self):
        m = _get_crypto_agent()
        agent = m.CryptoPriceAgent()
        mock_payload = json.dumps({"bitcoin": {"usd": 65000}}).encode("utf-8")
        mock_resp = _MockResponse(mock_payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await agent.run_task("BTC fiyatı nedir?")
        assert "65000" in result
        assert "BTC" in result

    @pytest.mark.asyncio
    async def test_eth_price_success(self):
        m = _get_crypto_agent()
        agent = m.CryptoPriceAgent()
        mock_payload = json.dumps({"ethereum": {"usd": 3200}}).encode("utf-8")
        mock_resp = _MockResponse(mock_payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await agent.run_task("ethereum fiyatı nedir?")
        assert "3200" in result
        assert "ETH" in result or "ETHEREUM" in result

    @pytest.mark.asyncio
    async def test_sol_price_success(self):
        m = _get_crypto_agent()
        agent = m.CryptoPriceAgent()
        mock_payload = json.dumps({"solana": {"usd": 150}}).encode("utf-8")
        mock_resp = _MockResponse(mock_payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await agent.run_task("sol fiyatı")
        assert "150" in result

    @pytest.mark.asyncio
    async def test_missing_usd_field_returns_message(self):
        m = _get_crypto_agent()
        agent = m.CryptoPriceAgent()
        mock_payload = json.dumps({"bitcoin": {}}).encode("utf-8")
        mock_resp = _MockResponse(mock_payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await agent.run_task("bitcoin fiyatı")
        assert "alınamadı" in result

    @pytest.mark.asyncio
    async def test_network_error_returns_message(self):
        m = _get_crypto_agent()
        agent = m.CryptoPriceAgent()
        with patch("urllib.request.urlopen", side_effect=OSError("bağlantı hatası")):
            result = await agent.run_task("btc fiyatı")
        assert "alınamadı" in result

    @pytest.mark.asyncio
    async def test_supported_symbols_listed_on_error(self):
        m = _get_crypto_agent()
        agent = m.CryptoPriceAgent()
        result = await agent.run_task("xyz fiyatı nedir?")
        # Desteklenenlerin listesi dönmeli
        assert any(s in result for s in ("btc", "eth", "sol"))

    @pytest.mark.asyncio
    async def test_result_contains_dollar_sign(self):
        m = _get_crypto_agent()
        agent = m.CryptoPriceAgent()
        mock_payload = json.dumps({"bitcoin": {"usd": 70000}}).encode("utf-8")
        mock_resp = _MockResponse(mock_payload)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await agent.run_task("bitcoin fiyatı")
        assert "$" in result
