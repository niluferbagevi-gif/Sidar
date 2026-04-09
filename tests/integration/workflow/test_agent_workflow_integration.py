import types

import pytest

from managers.web_search import WebSearchManager
from tests.helpers import collect_async_chunks as _collect_stream
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_runs_research_pipeline_with_real_supervisor(
    sidar_agent_factory,
    fake_llm_client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Gerçek supervisor + researcher akışını, yalnızca dış web bağımlılığını izole ederek doğrular."""
    cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path), ENABLE_TRACING=False)
    agent = sidar_agent_factory(cfg=cfg)

    # Dış bağımlılık: LLM servisi conftest.fake_llm_client ile izole edildi.
    agent.llm = fake_llm_client

    timeline: list[tuple[str, str]] = []

    async def _memory_add(role: str, content: str) -> None:
        timeline.append((role, content))

    async def _fake_web_search(_self, query: str):
        return True, f"docs:ok:{query}"

    agent._memory_add = _memory_add
    monkeypatch.setattr(WebSearchManager, "search", _fake_web_search)

    out = await _collect_stream(agent.respond("docs için araştırma yap"))

    assert len(out) > 0
    assert ("user", "docs için araştırma yap") in timeline
    assert any(role == "assistant" for role, _ in timeline)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_handles_search_failure(
    sidar_agent_factory,
    fake_llm_client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Arama başarısız olduğunda supervisor'ın çökmediğini ve durumu yönettiğini doğrular."""
    cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path), ENABLE_TRACING=False)
    agent = sidar_agent_factory(cfg=cfg)

    # Dış bağımlılık: LLM servisi conftest.fake_llm_client ile izole edildi.
    agent.llm = fake_llm_client

    timeline: list[tuple[str, str]] = []

    async def _memory_add(role: str, content: str) -> None:
        timeline.append((role, content))

    async def _fake_web_search_fail(_self, query: str):
        return False, f"Arama sırasında hata oluştu: {query}"

    agent._memory_add = _memory_add
    monkeypatch.setattr(WebSearchManager, "search", _fake_web_search_fail)

    out = await _collect_stream(agent.respond("docs için araştırma yap"))

    assert len(out) > 0
    assert any("hata" in msg.lower() or "yapılamadı" in msg.lower() for msg in out)
    assert ("user", "docs için araştırma yap") in timeline
    assert any(role == "assistant" for role, _ in timeline)
    assert agent._supervisor is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_executes_tool_sequence(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """_tool_subtask ReAct döngüsü: LLM araç kararı → docs_search icrası → final_answer zincirini doğrular.

    Sadece dış bağımlılıklar (LLM servisi + vektör DB) izole edilir; iç dispatch
    mekanizması (_execute_tool) gerçekte çalıştırılır.
    """
    cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path), ENABLE_TRACING=False)
    agent = sidar_agent_factory(cfg=cfg)

    call_count = 0

    async def mock_llm_chat(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return '{"thought": "Önce doküman araması yapmalıyım.", "tool": "docs_search", "argument": "pytest entegrasyon"}'
        return '{"thought": "Artık nihai yanıtı verebilirim.", "tool": "final_answer", "argument": "Araştırma tamamlandı."}'

    # Dış bağımlılık: LLM servisi izole edildi.
    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=mock_llm_chat))

    # Dış bağımlılık: vektör veritabanı (DocumentStore) izole edildi.
    docs_search_mock = MagicMock(return_value=(True, "pytest entegrasyon harikadır"))
    monkeypatch.setattr(agent.docs, "search", docs_search_mock)

    result = await agent._tool_subtask("Pytest entegrasyonunu araştır")

    # LLM iki kez çağrıldı: araç kararı (1) + nihai yanıt (2).
    assert call_count == 2
    # Gerçek _execute_tool dispatch'i docs_search'ü çalıştırdı — iç metot ezilmedi.
    docs_search_mock.assert_called_once()
    assert docs_search_mock.call_args[0][0] == "pytest entegrasyon"
    # ReAct döngüsü final_answer ile tamamlandı.
    assert "Araştırma tamamlandı." in result
