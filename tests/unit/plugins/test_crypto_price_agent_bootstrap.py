import importlib
import sys
import types

import tests.unit.plugins.test_crypto_price_agent as crypto_price_tests


def test_crypto_price_test_module_bootstrap_injects_stub_when_base_agent_missing():
    original_base_agent = sys.modules.pop("agent.base_agent", None)
    try:
        reloaded = importlib.reload(crypto_price_tests)
        injected = sys.modules.get("agent.base_agent")
        assert isinstance(injected, types.ModuleType)
        assert hasattr(injected, "BaseAgent")
        assert reloaded.CryptoPriceAgent is not None
    finally:
        if original_base_agent is not None:
            sys.modules["agent.base_agent"] = original_base_agent
        else:
            sys.modules.pop("agent.base_agent", None)
        importlib.reload(crypto_price_tests)
