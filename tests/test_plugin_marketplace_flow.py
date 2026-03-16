import asyncio
from pathlib import Path

from agent.registry import AgentRegistry
from tests.test_web_server_runtime import _load_web_server


class _Upload:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data
        self.closed = False

    async def read(self):
        return self._data

    async def close(self):
        self.closed = True


def test_register_file_plugin_and_execute_task():
    mod = _load_web_server()
    plugin_path = Path("plugins/crypto_price_agent.py")
    upload = _Upload(plugin_path.name, plugin_path.read_bytes())

    response = asyncio.run(
        mod.register_agent_plugin_file(
            file=upload,
            role_name="",
            class_name="CryptoPriceAgent",
            capabilities="crypto_price,market_data",
            description="Marketplace demo crypto agent",
            version="1.0.0",
            _user=object(),
        )
    )

    assert response.content["success"] is True
    agent_meta = response.content["agent"]
    assert agent_meta["role_name"] == "crypto_price_agent"
    assert "crypto_price" in agent_meta["capabilities"]
    assert agent_meta["is_builtin"] is False

    instance = AgentRegistry.create("crypto_price_agent")
    result = asyncio.run(instance.run_task("btc fiyatı nedir?"))
    assert "BTC" in result

    AgentRegistry.unregister("crypto_price_agent")
