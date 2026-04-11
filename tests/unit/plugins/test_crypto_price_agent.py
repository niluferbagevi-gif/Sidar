import asyncio
import importlib
import sys
import types

# Test ortamında ağır bağımlılıkları atlamak için minimal BaseAgent stub'ı.
if "agent.base_agent" not in sys.modules:
    fake_base_agent = types.ModuleType("agent.base_agent")

    class BaseAgent:  # pragma: no cover - test helper
        pass

    fake_base_agent.BaseAgent = BaseAgent
    sys.modules["agent.base_agent"] = fake_base_agent

from plugins.crypto_price_agent import CryptoPriceAgent


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _agent() -> CryptoPriceAgent:
    return CryptoPriceAgent.__new__(CryptoPriceAgent)


def test_extract_symbol_defaults_to_btc_when_no_token() -> None:
    assert CryptoPriceAgent._extract_symbol("?!") == "btc"


def test_extract_symbol_reads_first_alpha_token() -> None:
    assert CryptoPriceAgent._extract_symbol("ETH fiyatı nedir") == "eth"


def test_run_task_returns_error_for_unsupported_symbol() -> None:
    agent = _agent()

    result = asyncio.run(agent.run_task("doge"))

    assert "Desteklenmeyen sembol" in result
    assert "btc, eth, sol" in result


def test_run_task_returns_price_when_payload_has_usd(monkeypatch) -> None:
    agent = _agent()

    def _fake_urlopen(url: str, timeout: int = 0):
        assert "ethereum" in url
        assert timeout == 8
        return _FakeResponse(b'{"ethereum": {"usd": 3210}}')

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    result = asyncio.run(agent.run_task("ethereum"))

    assert result == "ETHEREUM güncel fiyatı: $3210"


def test_run_task_returns_missing_data_message_when_usd_missing(monkeypatch) -> None:
    agent = _agent()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda _url, timeout=0: _FakeResponse(b'{"solana": {}}'),
    )

    result = asyncio.run(agent.run_task("sol"))

    assert result == "SOL için fiyat verisi alınamadı."


def test_run_task_returns_exception_text_when_request_fails(monkeypatch) -> None:
    agent = _agent()

    def _boom(_url: str, timeout: int = 0):
        raise RuntimeError("network down")

    monkeypatch.setattr("urllib.request.urlopen", _boom)

    result = asyncio.run(agent.run_task("btc"))

    assert result == "BTC fiyatı alınamadı: network down"


def test_crypto_price_test_module_bootstrap_injects_stub_when_base_agent_missing():
    original_base_agent = sys.modules.pop("agent.base_agent", None)
    try:
        module = sys.modules[__name__]
        reloaded = importlib.reload(module)
        injected = sys.modules.get("agent.base_agent")
        assert isinstance(injected, types.ModuleType)
        assert hasattr(injected, "BaseAgent")
        assert reloaded.CryptoPriceAgent is not None
    finally:
        if original_base_agent is not None:
            sys.modules["agent.base_agent"] = original_base_agent
        else:
            sys.modules.pop("agent.base_agent", None)
        module = sys.modules[__name__]
        importlib.reload(module)


def test_crypto_price_test_module_bootstrap_restores_when_original_missing():
    pre_removed_base_agent = sys.modules.pop("agent.base_agent", None)
    original_base_agent = sys.modules.pop("agent.base_agent", None)
    try:
        module = sys.modules[__name__]
        reloaded = importlib.reload(module)
        injected = sys.modules.get("agent.base_agent")
        assert original_base_agent is None
        assert isinstance(injected, types.ModuleType)
        assert hasattr(injected, "BaseAgent")
        assert reloaded.CryptoPriceAgent is not None
    finally:
        sys.modules.pop("agent.base_agent", None)
        if pre_removed_base_agent is not None:
            sys.modules["agent.base_agent"] = pre_removed_base_agent
        module = sys.modules[__name__]
        importlib.reload(module)
