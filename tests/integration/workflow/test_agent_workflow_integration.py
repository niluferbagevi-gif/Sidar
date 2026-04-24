import types

import pytest

from managers.web_search import WebSearchManager
from tests.helpers import collect_async_chunks as _collect_stream
from unittest.mock import AsyncMock


def _integration_cfg(tmp_path, **overrides):
    base = {
        "BASE_DIR": str(tmp_path),
        "ENABLE_TRACING": False,
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path}/integration_memory.db",
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_runs_research_pipeline_with_real_supervisor(
    sidar_agent_factory,
    fake_llm_response,
    fake_web_search_result,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Gerçek supervisor + researcher akışını, yalnızca dış web bağımlılığını izole ederek doğrular."""
    cfg = _integration_cfg(tmp_path)
    agent = sidar_agent_factory(cfg=cfg)

    # LLM bağımlılığını izole ederek testi deterministik hale getir.
    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=fake_llm_response))

    await agent.memory.set_active_user("integration-user", "Integration User")

    search_mock = fake_web_search_result(True, "docs:ok:docs için araştırma yap")
    monkeypatch.setattr(WebSearchManager, "search", search_mock)

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
    fake_web_search_result,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Arama başarısız olduğunda supervisor'ın çökmediğini ve durumu yönettiğini doğrular."""
    cfg = _integration_cfg(tmp_path)
    agent = sidar_agent_factory(cfg=cfg)

    # LLM bağımlılığını izole ederek testi deterministik hale getir.
    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=fake_llm_response))

    await agent.memory.set_active_user("integration-user", "Integration User")

    search_mock = fake_web_search_result(False, "Arama sırasında hata oluştu: docs için araştırma yap")
    monkeypatch.setattr(WebSearchManager, "search", search_mock)

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
    fake_llm_tool_sequence,
    fake_web_search_result,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """LLM araç kararı + araç icrası + memory kaydını uçtan uca doğrular."""
    cfg = _integration_cfg(tmp_path)
    agent = sidar_agent_factory(cfg=cfg)

    agent.llm = types.SimpleNamespace(
        chat=fake_llm_tool_sequence(
            [
                '{"thought": "Önce web araması yapmalıyım.", "tool": "web_search", "argument": "pytest integration"}',
                '{"thought": "Artık nihai yanıtı verebilirim.", "tool": "final_answer", "argument": "Araştırma tamamlandı."}',
            ]
        )
    )

    await agent.memory.set_active_user("integration-user", "Integration User")

    search_mock = fake_web_search_result(True, "bulunan sonuc: pytest harikadır")
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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_handles_docs_search_vector_failure(
    sidar_agent_factory,
    fake_llm_tool_sequence,
    fake_vector_store,
    tmp_path,
) -> None:
    """RAG/vector araması patladığında akışın zarifçe sürdüğünü doğrular."""
    cfg = _integration_cfg(tmp_path)
    agent = sidar_agent_factory(cfg=cfg)

    agent.llm = types.SimpleNamespace(
        chat=fake_llm_tool_sequence(
            [
                '{"thought":"Önce depoda arama yap.", "tool":"docs_search", "argument":"vektör araması"}',
                '{"thought":"Hata durumunu kullanıcıya açıkla.", "tool":"final_answer", "argument":"Doküman araması şu anda kullanılamıyor."}',
            ]
        )
    )

    await agent.memory.set_active_user("integration-user", "Integration User")

    fake_vector_store.set_db_error()
    agent.docs = types.SimpleNamespace(search=fake_vector_store.search)

    out = await _collect_stream(agent.respond("Depodaki dokümanları ara"))

    assert len(out) > 0
    assert any("kullanılamıyor" in msg.lower() or "hata" in msg.lower() for msg in out)
    assert fake_vector_store.search.called

    history = await agent.memory.get_history()
    assert any(msg.get("role") == "user" and "Depodaki dokümanları ara" in msg.get("content", "") for msg in history)
    assert any(msg.get("role") == "assistant" for msg in history)
