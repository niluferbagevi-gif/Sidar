import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path


def _load_crypto_plugin(module_name: str = "crypto_plugin_under_test"):
    base_agent_mod = types.ModuleType("agent.base_agent")

    class _BaseAgent:
        pass

    base_agent_mod.BaseAgent = _BaseAgent

    prev = sys.modules.get("agent.base_agent")
    sys.modules["agent.base_agent"] = base_agent_mod
    try:
        spec = importlib.util.spec_from_file_location(module_name, Path("plugins/crypto_price_agent.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if prev is None:
            sys.modules.pop("agent.base_agent", None)
        else:
            sys.modules["agent.base_agent"] = prev


class _DummyResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_crypto_price_agent_run_task_success(monkeypatch):
    mod = _load_crypto_plugin("crypto_plugin_success")
    agent = object.__new__(mod.CryptoPriceAgent)

    def _fake_urlopen(url: str, timeout: int = 8):
        assert "ids=bitcoin" in url
        assert timeout == 8
        return _DummyResponse({"bitcoin": {"usd": 123456}})

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen)
    result = asyncio.run(agent.run_task("btc fiyatı nedir"))
    assert "BTC güncel fiyatı: $123456" in result


def test_crypto_price_agent_run_task_unsupported_symbol_and_network_error(monkeypatch):
    mod = _load_crypto_plugin("crypto_plugin_errors")
    agent = object.__new__(mod.CryptoPriceAgent)

    unsupported = asyncio.run(agent.run_task("doge kaç dolar"))
    assert "Desteklenmeyen sembol: doge" in unsupported

    def _broken_urlopen(_url: str, timeout: int = 8):
        raise RuntimeError("network down")

    monkeypatch.setattr(mod.urllib.request, "urlopen", _broken_urlopen)
    failed = asyncio.run(agent.run_task("eth kaç usd"))
    assert "ETH fiyatı alınamadı" in failed


def test_crypto_price_agent_missing_usd_and_symbol_extraction_default(monkeypatch):
    mod = _load_crypto_plugin("crypto_plugin_missing_usd")
    agent = object.__new__(mod.CryptoPriceAgent)

    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *_a, **_k: _DummyResponse({"bitcoin": {}}))
    no_price = asyncio.run(agent.run_task("bitcoin fiyat"))
    assert "BITCOIN için fiyat verisi alınamadı." in no_price

    assert mod.CryptoPriceAgent._extract_symbol("### ???") == "btc"
