"""Contract tests for the isolated plugin RPC worker."""

from __future__ import annotations

import pytest

from web.plugins.sandbox import PLUGIN_RPC_VERSION
from web.plugins.worker import handle_request

SOURCE = """
from agent.base_agent import BaseAgent

class EchoAgent(BaseAgent):
    \"\"\"Echo plugin.\"\"\"
    async def run_task(self, task_prompt: str) -> str:
        return f\"isolated:{task_prompt}\"
"""


def test_worker_describes_and_runs_versioned_agent_rpc() -> None:
    base = {
        "rpc_version": PLUGIN_RPC_VERSION,
        "source": SOURCE,
        "class_name": "EchoAgent",
        "module_label": "echo",
    }
    described = handle_request({**base, "action": "describe"})
    executed = handle_request({**base, "action": "run_task", "task_prompt": "hello"})

    assert described == {
        "rpc_version": PLUGIN_RPC_VERSION,
        "ok": True,
        "class_name": "EchoAgent",
        "description": "Echo plugin.",
    }
    assert executed["result"] == "isolated:hello"


def test_worker_rejects_protocol_mismatch_and_unknown_action() -> None:
    with pytest.raises(ValueError, match="RPC sürümü"):
        handle_request({"rpc_version": "0", "action": "describe", "source": SOURCE})
    with pytest.raises(ValueError, match="Desteklenmeyen"):
        handle_request({"rpc_version": PLUGIN_RPC_VERSION, "action": "shell", "source": SOURCE})
