"""Unit tests for ``agent.federation.service``."""

from __future__ import annotations

from agent.federation.service import (
    _MAX_TRIGGER_PROMPT_CHARS,
    build_trigger_prompt,
    trigger_to_prompt,
)


def test_federation_service_builds_task_prompt() -> None:
    """Federation service builds task prompt."""
    prompt = build_trigger_prompt(
        {"trigger_id": "trg-1", "source": "hub", "correlation_id": "corr-1"},
        {"kind": "federation_task", "task_id": "task-1", "goal": "Sync records"},
        None,
    )

    assert "Sync records" in prompt
    assert "corr-1" in prompt


def test_federation_service_prefers_preset_prompt() -> None:
    """Federation service prefers preset prompt."""
    assert (
        build_trigger_prompt(
            {"trigger_id": "trg-1"},
            {"kind": "federation_task", "federation_prompt": "PRESET"},
            None,
        )
        == "PRESET"
    )


def test_federation_service_formats_generic_dict_trigger() -> None:
    """Federation service formats generic dict trigger."""
    prompt = trigger_to_prompt(
        {"event_name": "deploy", "source": "ci", "payload": {"status": "green"}}
    )

    assert "[EXTERNAL EVENT]" in prompt
    assert "source=ci" in prompt
    assert '"status": "green"' in prompt


def test_federation_service_ci_context_takes_precedence() -> None:
    """Federation service ci context takes precedence."""
    prompt = build_trigger_prompt(
        {"event_name": "deploy", "source": "ci"},
        {"kind": "federation_task", "task_id": "task-1", "goal": "Should not render"},
        {
            "repo": "org/repo",
            "workflow_name": "backend-ci",
            "failed_jobs": ["tests"],
            "failure_summary": "pytest failed",
        },
    )

    assert "[CI_REMEDIATION]" in prompt
    assert "repo=org/repo" in prompt
    assert "workflow_name=backend-ci" in prompt
    assert "Should not render" not in prompt


class _PromptTrigger:
    def to_prompt(self) -> str:
        return "CUSTOM PROMPT"


class _ObjectTrigger:
    event_name = "object_event"
    source = "object_source"
    payload = {"count": 1}
    meta = {"trace": "abc"}
    trigger_id = "obj-1"
    correlation_id = "corr-obj"


class _FeedbackTrigger:
    event_name = "action_feedback"
    source = "object_source"
    payload = "not-a-dict"
    meta = {"trace": "abc"}
    trigger_id = "obj-1"
    correlation_id = "corr-obj"


def test_federation_service_uses_trigger_to_prompt_method() -> None:
    """Federation service uses trigger to prompt method."""
    assert trigger_to_prompt(_PromptTrigger()) == "CUSTOM PROMPT"


def test_federation_service_formats_generic_object_trigger() -> None:
    """Federation service formats generic object trigger."""
    prompt = trigger_to_prompt(_ObjectTrigger())

    assert "source=object_source" in prompt
    assert "event_name=object_event" in prompt
    assert '"count": 1' in prompt


def test_federation_service_builds_action_feedback_from_event_name() -> None:
    """Federation service builds action feedback from event name."""
    prompt = build_trigger_prompt(
        _FeedbackTrigger(),
        {"status": "ok", "summary": "completed", "details": {"step": "deploy"}},
        None,
    )

    assert "[ACTION FEEDBACK]" in prompt
    assert "action_name=action_feedback" in prompt
    assert "status=ok" in prompt
    assert "completed" in prompt
    assert "corr-obj" in prompt


def test_federation_service_builds_action_feedback_from_kind_for_dict_trigger() -> None:
    """Federation service builds action feedback from kind for dict trigger."""
    prompt = build_trigger_prompt(
        {"trigger_id": "fb-1", "source": "worker", "event_name": "ignored"},
        {"kind": "action_feedback", "action_name": "publish", "meta": {"team": "qa"}},
        None,
    )

    assert "[ACTION FEEDBACK]" in prompt
    assert "action_name=publish" in prompt
    assert "source_system=worker" in prompt


def test_federation_service_build_trigger_prompt_falls_back_to_generic_prompt() -> None:
    """Federation service build trigger prompt falls back to generic prompt."""
    prompt = build_trigger_prompt(
        {"event_name": "deploy", "source": "ci", "payload": {"status": "green"}},
        {},
        None,
    )

    assert "[EXTERNAL EVENT]" in prompt
    assert "event_name=deploy" in prompt


def test_federation_service_caps_oversized_federation_task_prompt() -> None:
    """Federation service caps oversized federation task prompt."""
    huge_context = {"blob": "x" * (_MAX_TRIGGER_PROMPT_CHARS * 2)}
    prompt = build_trigger_prompt(
        {"trigger_id": "trg-1", "source": "hub", "correlation_id": "corr-1"},
        {
            "kind": "federation_task",
            "task_id": "task-1",
            "goal": "Sync records",
            "context": huge_context,
        },
        None,
    )

    assert len(prompt) <= _MAX_TRIGGER_PROMPT_CHARS + len(
        "\n…[truncated: external trigger payload too large]"
    )
    assert prompt.endswith("…[truncated: external trigger payload too large]")


def test_federation_service_caps_oversized_action_feedback_prompt() -> None:
    """Federation service caps oversized action feedback prompt."""
    prompt = build_trigger_prompt(
        {"trigger_id": "fb-1", "source": "worker"},
        {
            "kind": "action_feedback",
            "action_name": "publish",
            "details": {"blob": "y" * (_MAX_TRIGGER_PROMPT_CHARS * 2)},
        },
        None,
    )

    assert prompt.endswith("…[truncated: external trigger payload too large]")


def test_federation_service_caps_oversized_generic_trigger_prompt() -> None:
    """Federation service caps oversized generic trigger prompt."""
    prompt = build_trigger_prompt(
        {
            "event_name": "deploy",
            "source": "ci",
            "payload": {"status": "z" * (_MAX_TRIGGER_PROMPT_CHARS * 2)},
        },
        {},
        None,
    )

    assert prompt.endswith("…[truncated: external trigger payload too large]")


def test_federation_service_does_not_truncate_prompts_under_the_cap() -> None:
    """Federation service does not truncate prompts under the cap."""
    prompt = build_trigger_prompt(
        {"trigger_id": "trg-1", "source": "hub", "correlation_id": "corr-1"},
        {"kind": "federation_task", "task_id": "task-1", "goal": "Sync records"},
        None,
    )

    assert "…[truncated" not in prompt
