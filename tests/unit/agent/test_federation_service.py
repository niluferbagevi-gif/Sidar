from __future__ import annotations

from agent.federation.service import build_trigger_prompt, trigger_to_prompt


def test_federation_service_builds_task_prompt() -> None:
    prompt = build_trigger_prompt(
        {"trigger_id": "trg-1", "source": "hub", "correlation_id": "corr-1"},
        {"kind": "federation_task", "task_id": "task-1", "goal": "Sync records"},
        None,
    )

    assert "Sync records" in prompt
    assert "corr-1" in prompt


def test_federation_service_prefers_preset_prompt() -> None:
    assert (
        build_trigger_prompt(
            {"trigger_id": "trg-1"},
            {"kind": "federation_task", "federation_prompt": "PRESET"},
            None,
        )
        == "PRESET"
    )


def test_federation_service_formats_generic_dict_trigger() -> None:
    prompt = trigger_to_prompt(
        {"event_name": "deploy", "source": "ci", "payload": {"status": "green"}}
    )

    assert "[EXTERNAL EVENT]" in prompt
    assert "source=ci" in prompt
    assert '"status": "green"' in prompt
