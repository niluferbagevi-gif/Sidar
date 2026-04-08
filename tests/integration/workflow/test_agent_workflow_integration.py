import types

import pytest
from unittest.mock import AsyncMock

from tests.helpers import collect_async_chunks as _collect_stream


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sidar_agent_workflow_runs_search_code_and_final_response(sidar_agent_factory) -> None:
    """Görev -> arama -> kod adımı -> nihai yanıt akışını entegre olarak doğrular."""
    agent = sidar_agent_factory()
    agent._lock = None
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_args, **_kwargs: None

    timeline: list[tuple[str, str]] = []

    async def _memory_add(role: str, content: str) -> None:
        timeline.append((role, content))

    async def _search(query: str, *_args):
        return True, f"docs:{query}"

    class _Code:
        def run_shell(self, command: str):
            timeline.append(("code", command))
            return True, "lint:ok"

    async def _run_task(prompt: str) -> str:
        docs_result = await agent._tool_docs_search("workflow")
        _ok, shell_result = agent.code.run_shell("python -m compileall .")
        return f"{docs_result} | {shell_result} | final:{prompt}"

    agent._memory_add = _memory_add
    agent.docs = types.SimpleNamespace(search=AsyncMock(side_effect=_search))
    agent.code = _Code()
    agent._supervisor = types.SimpleNamespace(run_task=AsyncMock(side_effect=_run_task))

    out = await _collect_stream(agent.respond("Görevi tamamla"))

    assert out == ["docs:workflow | lint:ok | final:Görevi tamamla"]
    assert ("code", "python -m compileall .") in timeline
    assert ("user", "Görevi tamamla") in timeline
    assert ("assistant", "docs:workflow | lint:ok | final:Görevi tamamla") in timeline
