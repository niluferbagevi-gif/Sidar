"""Contract tests for the isolated plugin RPC worker."""

from __future__ import annotations

import io
import json

import pytest

from web.plugins import worker
from web.plugins.sandbox import PLUGIN_RPC_VERSION
from web.plugins.worker import handle_request

SOURCE = """
from agent.base_agent import BaseAgent

class EchoAgent(BaseAgent):
    \"\"\"Echo plugin.\"\"\"
    async def run_task(self, task_prompt: str) -> str:
        return f\"isolated:{task_prompt}\"
"""

SOURCE_WITHOUT_AGENT = "RESULT = 1\n"

SOURCE_NON_STRING_RESULT = """
from agent.base_agent import BaseAgent

class WeirdAgent(BaseAgent):
    \"\"\"Returns a non-string result.\"\"\"
    async def run_task(self, task_prompt: str):
        return 42
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


def test_worker_rejects_non_string_plugin_source() -> None:
    with pytest.raises(ValueError, match="metin olmalıdır"):
        handle_request({"rpc_version": PLUGIN_RPC_VERSION, "action": "describe", "source": 123})


def test_agent_class_raises_when_requested_name_is_not_a_baseagent_subclass() -> None:
    with pytest.raises(ValueError, match="Belirtilen BaseAgent sınıfı bulunamadı: GhostAgent"):
        handle_request(
            {
                "rpc_version": PLUGIN_RPC_VERSION,
                "action": "describe",
                "source": SOURCE,
                "class_name": "GhostAgent",
            }
        )


def test_agent_class_defaults_to_the_only_candidate_when_none_is_requested() -> None:
    described = handle_request(
        {"rpc_version": PLUGIN_RPC_VERSION, "action": "describe", "source": SOURCE}
    )

    assert described["class_name"] == "EchoAgent"


def test_agent_class_raises_when_no_baseagent_subclass_is_defined() -> None:
    with pytest.raises(ValueError, match="BaseAgent türevi bir sınıf bulunamadı"):
        handle_request(
            {
                "rpc_version": PLUGIN_RPC_VERSION,
                "action": "describe",
                "source": SOURCE_WITHOUT_AGENT,
            }
        )


def test_worker_rejects_non_string_task_prompt() -> None:
    with pytest.raises(ValueError, match="görev girdisi metin olmalıdır"):
        handle_request(
            {
                "rpc_version": PLUGIN_RPC_VERSION,
                "action": "run_task",
                "source": SOURCE,
                "class_name": "EchoAgent",
                "task_prompt": 123,
            }
        )


def test_worker_rejects_agent_returning_non_string_task_result() -> None:
    with pytest.raises(ValueError, match="görev çıktısı metin olmalıdır"):
        handle_request(
            {
                "rpc_version": PLUGIN_RPC_VERSION,
                "action": "run_task",
                "source": SOURCE_NON_STRING_RESULT,
                "class_name": "WeirdAgent",
                "task_prompt": "hello",
            }
        )


def test_main_reads_one_envelope_from_stdin_and_writes_ok_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = {
        "rpc_version": PLUGIN_RPC_VERSION,
        "action": "describe",
        "source": SOURCE,
        "class_name": "EchoAgent",
        "module_label": "echo",
    }
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(json.dumps(request)))
    out = io.StringIO()
    monkeypatch.setattr(worker.sys, "stdout", out)

    assert worker.main() == 0

    response = json.loads(out.getvalue())
    assert response["ok"] is True
    assert response["class_name"] == "EchoAgent"


def test_main_serializes_any_failure_into_a_bounded_ok_false_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO("not-json"))
    out = io.StringIO()
    monkeypatch.setattr(worker.sys, "stdout", out)

    assert worker.main() == 0

    response = json.loads(out.getvalue())
    assert response == {
        "rpc_version": PLUGIN_RPC_VERSION,
        "ok": False,
        "error": response["error"],
    }
    assert response["error"]


def test_main_rejects_non_dict_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(json.dumps(["not", "a", "dict"])))
    out = io.StringIO()
    monkeypatch.setattr(worker.sys, "stdout", out)

    assert worker.main() == 0

    response = json.loads(out.getvalue())
    assert response["ok"] is False
    assert "zarfı nesne olmalıdır" in response["error"]
