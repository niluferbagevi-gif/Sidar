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

    timeline: list[tuple[str, str]] = []

    async def _memory_add(role: str, content: str) -> None:
        timeline.append((role, content))

    async def _fake_web_search(_self, query: str):
        return True, f"docs:ok:{query}"

    agent._memory_add = _memory_add
    monkeypatch.setattr(WebSearchManager, "search", _fake_web_search)
    agent._supervisor = object()
    agent._try_multi_agent = AsyncMock(return_value="docs:ok:docs için araştırma yap")

    out = await _collect_stream(agent.respond("docs için araştırma yap"))

    assert out == ["docs:ok:docs için araştırma yap"]
    assert ("user", "docs için araştırma yap") in timeline
    assert ("assistant", "docs:ok:docs için araştırma yap") in timeline
    assert agent._supervisor is not None


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
