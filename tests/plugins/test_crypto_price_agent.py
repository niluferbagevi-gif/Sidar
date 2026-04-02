import asyncio
import json
import sys
import types


class _FakeBaseAgent:
    def __init__(self, cfg=None, *, role_name="base"):
        self.cfg = cfg or types.SimpleNamespace()
        self.role_name = role_name


sys.modules.setdefault("agent.base_agent", types.SimpleNamespace(BaseAgent=_FakeBaseAgent))

from plugins.crypto_price_agent import CryptoPriceAgent


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_crypto_price_agent_unsupported_symbol():
    agent = CryptoPriceAgent()
    result = asyncio.run(agent.run_task("doge fiyatı"))
    assert result.startswith("Desteklenmeyen sembol")


def test_crypto_price_agent_success(monkeypatch):
    agent = CryptoPriceAgent()

    def _fake_urlopen(url, timeout=0):
        assert "ethereum" in url
        assert timeout == 8
        return _FakeResponse({"ethereum": {"usd": 3500}})

    monkeypatch.setattr("plugins.crypto_price_agent.urllib.request.urlopen", _fake_urlopen)
    result = asyncio.run(agent.run_task("eth kaç dolar"))
    assert result == "ETH güncel fiyatı: $3500"


def test_crypto_price_agent_missing_usd(monkeypatch):
    agent = CryptoPriceAgent()

    monkeypatch.setattr(
        "plugins.crypto_price_agent.urllib.request.urlopen",
        lambda *_args, **_kwargs: _FakeResponse({"bitcoin": {}}),
    )
    result = asyncio.run(agent.run_task("btc"))
    assert result == "BTC için fiyat verisi alınamadı."


def test_crypto_price_agent_exception(monkeypatch):
    agent = CryptoPriceAgent()

    def _raise(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("plugins.crypto_price_agent.urllib.request.urlopen", _raise)
    result = asyncio.run(agent.run_task("btc"))
    assert "BTC fiyatı alınamadı" in result


def test_extract_symbol_default_and_match():
    assert CryptoPriceAgent._extract_symbol("") == "btc"
    assert CryptoPriceAgent._extract_symbol("SOL fiyat") == "sol"
