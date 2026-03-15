import asyncio
from pathlib import Path

from tests.test_sidar_agent_runtime import _collect, _make_agent_for_runtime


def test_supervisor_flow_no_parallel_react_loop_markers_in_agent_source():
    src = Path("agent/sidar_agent.py").read_text(encoding="utf-8")
    assert "_react_loop" not in src
    assert "_execute_tool" not in src
    assert "_try_direct_tool_route" not in src


def test_supervisor_entrypoint_exists_and_routes_through_run_task():
    agent = _make_agent_for_runtime()

    class _Supervisor:
        async def run_task(self, user_input):
            return f"ok:{user_input}"

    agent._supervisor = _Supervisor()
    out = asyncio.run(agent._try_multi_agent("plan"))
    assert out == "ok:plan"


def test_respond_uses_supervisor_result_as_single_stream_chunk():
    agent = _make_agent_for_runtime()

    async def _fake_multi(user_input):
        return f"done:{user_input}"

    agent._try_multi_agent = _fake_multi
    agent._initialized = True

    async def _memory_add(role, text):
        await agent.memory.add(role, text)

    agent._memory_add = _memory_add
    out = asyncio.run(_collect(agent.respond("görev")))
    assert out == ["done:görev"]