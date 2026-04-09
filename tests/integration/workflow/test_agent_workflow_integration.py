import types

import pytest

from managers.web_search import WebSearchManager
from tests.helpers import collect_async_chunks as _collect_stream
from unittest.mock import AsyncMock


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_runs_research_pipeline_with_real_supervisor(
    sidar_agent_factory,
    fake_llm_response,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Gerçek supervisor + researcher akışını, yalnızca dış web bağımlılığını izole ederek doğrular."""
    cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path), ENABLE_TRACING=False)
    agent = sidar_agent_factory(cfg=cfg)

    # LLM bağımlılığını izole ederek testi deterministik hale getir.
    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=fake_llm_response))

    await agent.memory.set_active_user("integration-user", "Integration User")

    async def _fake_web_search(_self, query: str):
        return True, f"docs:ok:{query}"

    monkeypatch.setattr(WebSearchManager, "search", _fake_web_search)

    out = await _collect_stream(agent.respond("docs için araştırma yap"))

    assert len(out) > 0
    history = await agent.memory.get_history()
    assert any(msg.get("role") == "user" and "docs için araştırma yap" in msg.get("content", "") for msg in history)
    assert any(msg.get("role") == "assistant" for msg in history)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_handles_search_failure(
    sidar_agent_factory,
    fake_llm_response,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Arama başarısız olduğunda supervisor'ın çökmediğini ve durumu yönettiğini doğrular."""
    cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path), ENABLE_TRACING=False)
    agent = sidar_agent_factory(cfg=cfg)

    # LLM bağımlılığını izole ederek testi deterministik hale getir.
    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=fake_llm_response))

    await agent.memory.set_active_user("integration-user", "Integration User")

    async def _fake_web_search_fail(_self, query: str):
        return False, f"Arama sırasında hata oluştu: {query}"

    monkeypatch.setattr(WebSearchManager, "search", _fake_web_search_fail)

    out = await _collect_stream(agent.respond("docs için araştırma yap"))

    assert len(out) > 0
    assert any("hata" in msg.lower() or "yapılamadı" in msg.lower() for msg in out)
    history = await agent.memory.get_history()
    assert any(msg.get("role") == "user" and "docs için araştırma yap" in msg.get("content", "") for msg in history)
    assert any(msg.get("role") == "assistant" for msg in history)
    assert agent._supervisor is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_executes_tool_sequence(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """LLM araç kararı + araç icrası + memory kaydını uçtan uca doğrular."""
    cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path), ENABLE_TRACING=False)
    agent = sidar_agent_factory(cfg=cfg)

    call_count = 0

    async def mock_llm_chat(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return '{"thought": "Önce web araması yapmalıyım.", "tool": "web_search", "argument": "pytest integration"}'
        return '{"thought": "Artık nihai yanıtı verebilirim.", "tool": "final_answer", "argument": "Araştırma tamamlandı."}'

    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=mock_llm_chat))

    await agent.memory.set_active_user("integration-user", "Integration User")

    search_mock = AsyncMock(return_value=(True, "bulunan sonuc: pytest harikadır"))
    monkeypatch.setattr(WebSearchManager, "search", search_mock)

    out = await _collect_stream(agent.respond("Pytest entegrasyonunu araştır"))

    search_mock.assert_awaited_once_with(agent.web, "pytest integration")
    assert any("Araştırma tamamlandı." in msg for msg in out)
    history = await agent.memory.get_history()
    assert any(msg.get("role") == "user" and "Pytest entegrasyonunu araştır" in msg.get("content", "") for msg in history)
    assert any(
        msg.get("role") == "assistant" and "Araştırma tamamlandı." in msg.get("content", "")
        for msg in history
    )
