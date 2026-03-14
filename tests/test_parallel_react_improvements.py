# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

import asyncio
from pathlib import Path

from tests.test_sidar_agent_runtime import _collect, _make_react_ready_agent


def test_react_loop_supports_json_array_toolcalls():
    src = Path("agent/sidar_agent.py").read_text(encoding="utf-8")
    assert "if isinstance(payload, list):" in src
    assert "action_list = [ToolCall.model_validate(item) for item in payload]" in src


def test_react_loop_runs_parallel_batch_with_gather():
    src = Path("agent/sidar_agent.py").read_text(encoding="utf-8")
    assert "if len(action_list) > 1:" in src
    assert "await asyncio.gather(" in src
    assert "parallel_batch" in src


def test_parallel_tool_removed_from_dispatch_registry():
    src = Path("agent/tooling.py").read_text(encoding="utf-8")
    assert '"parallel":' not in src


def test_react_loop_rejects_final_answer_inside_parallel_list():
    agent = _make_react_ready_agent(max_steps=2)

    class _Mem:
        def get_messages_for_llm(self):
            return []

        def add(self, *_args):
            return None

    class _LLM:
        def __init__(self):
            self.calls = []
            self.payloads = [
                '[{"thought":"t1","tool":"read_file","argument":"a.py"},{"thought":"t2","tool":"final_answer","argument":"x"}]',
                '{"thought":"t3","tool":"final_answer","argument":"done"}',
            ]
            self.idx = 0

        async def chat(self, **kwargs):
            self.calls.append(kwargs.get("messages", []))
            text = self.payloads[min(self.idx, len(self.payloads) - 1)]
            self.idx += 1

            async def _gen():
                yield text

            return _gen()

    agent.memory = _Mem()
    agent.llm = _LLM()
    out = asyncio.run(_collect(agent._react_loop("x")))

    assert out[-1] == "done"
    assert len(agent.llm.calls) >= 2
    assert "final_answer yalnızca tek başına" in str(agent.llm.calls[1])


def test_react_loop_rejects_unsafe_tool_inside_parallel_list():
    agent = _make_react_ready_agent(max_steps=2)
    agent._AUTO_PARALLEL_SAFE = {"read_file"}

    class _Mem:
        def get_messages_for_llm(self):
            return []

        def add(self, *_args):
            return None

    class _LLM:
        def __init__(self):
            self.calls = []
            self.payloads = [
                '[{"thought":"t1","tool":"read_file","argument":"a.py"},{"thought":"t2","tool":"write_file","argument":"x"}]',
                '{"thought":"t3","tool":"final_answer","argument":"done"}',
            ]
            self.idx = 0

        async def chat(self, **kwargs):
            self.calls.append(kwargs.get("messages", []))
            text = self.payloads[min(self.idx, len(self.payloads) - 1)]
            self.idx += 1

            async def _gen():
                yield text

            return _gen()

    agent.memory = _Mem()
    agent.llm = _LLM()
    out = asyncio.run(_collect(agent._react_loop("x")))

    assert out[-1] == "done"
    assert len(agent.llm.calls) >= 2
    assert "yalnızca okuma araçları desteklenir" in str(agent.llm.calls[1])