from pathlib import Path


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
