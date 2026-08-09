"""Contract tests for shared HTTP route serializers."""

from __future__ import annotations

from types import SimpleNamespace

from web.routes.serialization import serialize_prompt, serialize_swarm_result


def test_serialize_prompt_normalizes_values_and_preserves_legacy_id() -> None:
    record = SimpleNamespace(
        id="legacy-id",
        role_name=None,
        prompt_text="Review carefully",
        version=0,
        is_active=1,
    )

    payload = serialize_prompt(record)

    assert payload == {
        "id": "legacy-id",
        "role_name": "",
        "prompt_text": "Review carefully",
        "version": 1,
        "is_active": True,
        "created_at": "",
        "updated_at": "",
    }


def test_serialize_swarm_result_copies_mutable_collections() -> None:
    evidence = ["unit-test"]
    handoffs = ["reviewer"]
    graph = {"coder": ["reviewer"]}
    record = SimpleNamespace(
        task_id=42,
        agent_role="coder",
        status="completed",
        summary="Done",
        elapsed_ms="15",
        evidence=evidence,
        handoffs=handoffs,
        graph=graph,
    )

    payload = serialize_swarm_result(record)

    assert payload["task_id"] == "42"
    assert payload["elapsed_ms"] == 15
    assert payload["evidence"] == evidence and payload["evidence"] is not evidence
    assert payload["handoffs"] == handoffs and payload["handoffs"] is not handoffs
    assert payload["graph"] == graph and payload["graph"] is not graph
