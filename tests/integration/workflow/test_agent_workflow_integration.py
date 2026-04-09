import types

import pytest

from managers.web_search import WebSearchManager
from tests.helpers import collect_async_chunks as _collect_stream


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
    agent.llm = types.SimpleNamespace(chat=fake_llm_response)

    async def _fake_web_search(_self, query: str):
        return True, f"docs:ok:{query}"

    monkeypatch.setattr(WebSearchManager, "search", _fake_web_search)

    out = await _collect_stream(agent.respond("docs için araştırma yap"))
    history = await agent.memory.get_history()

    assert len(out) > 0
    assert any(turn.get("role") == "user" and "docs için araştırma yap" in turn.get("content", "") for turn in history)
    assert any(turn.get("role") == "assistant" for turn in history)


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
    agent.llm = types.SimpleNamespace(chat=fake_llm_response)

    async def _fake_web_search_fail(_self, query: str):
        return False, f"Arama sırasında hata oluştu: {query}"

    monkeypatch.setattr(WebSearchManager, "search", _fake_web_search_fail)

    out = await _collect_stream(agent.respond("docs için araştırma yap"))
    history = await agent.memory.get_history()

    assert len(out) > 0
    assert any("hata" in msg.lower() or "yapılamadı" in msg.lower() for msg in out)
    assert any(turn.get("role") == "user" and "docs için araştırma yap" in turn.get("content", "") for turn in history)
    assert any(turn.get("role") == "assistant" for turn in history)
    assert agent._supervisor is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_executes_tool_sequence(
    sidar_agent_factory,
    fake_llm_tool_sequence_response,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """LLM araç kararı + araç icrası + memory kaydını uçtan uca doğrular."""
    cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path), ENABLE_TRACING=False)
    agent = sidar_agent_factory(cfg=cfg)

    agent.llm = types.SimpleNamespace(chat=fake_llm_tool_sequence_response)
    search_queries: list[str] = []

    async def _fake_web_search(_self, query: str):
        search_queries.append(query)
        return True, f"bulunan sonuc: {query} harikadır"

    monkeypatch.setattr(WebSearchManager, "search", _fake_web_search)

    out = await _collect_stream(agent.respond("Pytest entegrasyonunu araştır"))
    history = await agent.memory.get_history()

    assert search_queries == ["pytest integration"]
    assert "Araştırma tamamlandı." in out[-1]
    assert any(
        turn.get("role") == "user" and "Pytest entegrasyonunu araştır" in turn.get("content", "")
        for turn in history
    )
    assert any(
        turn.get("role") == "assistant" and "Araştırma tamamlandı." in turn.get("content", "")
        for turn in history
    )
