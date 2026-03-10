import asyncio
import json
from types import SimpleNamespace

from tests.test_llm_client_runtime import _load_llm_client_module


def test_anthropic_chat_without_key_returns_error_json():
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(ANTHROPIC_API_KEY="", ANTHROPIC_TIMEOUT=60, ANTHROPIC_MODEL="claude-3-5-sonnet-latest")

    client = llm_mod.AnthropicClient(cfg)
    out = asyncio.run(client.chat(messages=[{"role": "user", "content": "merhaba"}], stream=False, json_mode=True))
    payload = json.loads(out)

    assert payload["tool"] == "final_answer"
    assert "ANTHROPIC_API_KEY" in payload["argument"]


def test_llm_client_factory_supports_anthropic():
    llm_mod = _load_llm_client_module()
    cfg = SimpleNamespace(
        ANTHROPIC_API_KEY="x",
        ANTHROPIC_TIMEOUT=60,
        ANTHROPIC_MODEL="claude-3-5-sonnet-latest",
        OLLAMA_URL="http://localhost:11434/api",
        OLLAMA_TIMEOUT=30,
    )

    fac = llm_mod.LLMClient("anthropic", cfg)
    assert fac.provider == "anthropic"
    assert fac._client.__class__.__name__ == "AnthropicClient"