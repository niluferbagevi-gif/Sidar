from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent.core.contracts import (
    ACTION_FEEDBACK_PROTOCOL_V1,
    BROKER_PROTOCOL_V1,
    FEDERATION_PROTOCOL_V1,
    ActionFeedback,
    BrokerTaskEnvelope,
    BrokerTaskResult,
    DelegationRequest,
    ExternalTrigger,
    FederationTaskEnvelope,
    FederationTaskResult,
    P2PMessage,
    TaskEnvelope,
    TaskResult,
    derive_broker_routing_key,
    derive_correlation_id,
    is_action_feedback,
    is_broker_task_envelope,
    is_broker_task_result,
    is_delegation_request,
    is_external_trigger,
    is_federation_task_envelope,
    is_federation_task_result,
    is_p2p_message,
    normalize_broker_protocol,
    normalize_federation_protocol,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, FEDERATION_PROTOCOL_V1),
        ("swarm.federation.v1", FEDERATION_PROTOCOL_V1),
        ("  FeDeration.v1  ", FEDERATION_PROTOCOL_V1),
        ("federation.v2", "federation.v2"),
    ],
)
def test_normalize_federation_protocol(value: object, expected: str) -> None:
    assert normalize_federation_protocol(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, BROKER_PROTOCOL_V1),
        ("swarm.broker.v1", BROKER_PROTOCOL_V1),
        ("  broker.task.v1  ", BROKER_PROTOCOL_V1),
        ("broker.task.v2", "broker.task.v2"),
    ],
)
def test_normalize_broker_protocol(value: object, expected: str) -> None:
    assert normalize_broker_protocol(value) == expected


def test_derive_helpers_cover_fallback_paths() -> None:
    assert (
        derive_broker_routing_key(receiver="  QA ", intent=" Test ", namespace=" SIDAR ")
        == "sidar.qa.test"
    )
    assert (
        derive_broker_routing_key(receiver="", intent="", namespace="")
        == "sidar.swarm.unknown.mixed"
    )
    assert derive_correlation_id("", None, " id-42 ") == "id-42"
    assert derive_correlation_id(None, "", " ") == ""


def test_p2p_message_properties_and_bump() -> None:
    message = P2PMessage(task_id="t1", reply_to="reviewer", target_agent="coder", payload="fix")

    bumped = message.bumped()

    assert message.sender == "reviewer"
    assert message.receiver == "coder"
    assert bumped.handoff_depth == 1
    assert bumped.meta is not message.meta


def test_external_trigger_post_init_and_prompt() -> None:
    trigger = ExternalTrigger(
        trigger_id="tr-1",
        source="webhook",
        event_name="opened",
        payload={"task_id": "task-88", "x": 1},
        meta={"foo": "bar"},
    )

    assert trigger.correlation_id == "task-88"
    prompt = trigger.to_prompt()
    assert "[TRIGGER]" in prompt
    assert "event=opened" in prompt
    assert '"foo": "bar"' in prompt


def test_external_trigger_with_non_dict_payload_uses_trigger_id_as_correlation() -> None:
    trigger = ExternalTrigger(
        trigger_id="tr-last",
        source="cron",
        event_name="tick",
        payload="not-a-dict",  # type: ignore[arg-type]
    )
    assert trigger.correlation_id == "tr-last"


def test_federation_task_envelope_conversion_and_prompt() -> None:
    envelope = FederationTaskEnvelope(
        task_id="fed-1",
        source_system="sidar",
        source_agent="supervisor",
        target_system="ext",
        target_agent="researcher",
        goal="collect docs",
        parent_task_id="p-1",
        context={"lang": "tr"},
        inputs=["url"],
        protocol="swarm.federation.v1",
        meta={"correlation_id": "corr-meta"},
    )

    task = envelope.to_task_envelope()

    assert envelope.protocol == FEDERATION_PROTOCOL_V1
    assert envelope.correlation_id == "corr-meta"
    assert task.sender == "sidar:supervisor"
    assert task.receiver == "ext:researcher"
    assert task.context["correlation_id"] == "corr-meta"
    assert "[FEDERATION TASK]" in envelope.to_prompt()


def test_federation_task_result_conversion_and_prompt() -> None:
    result = FederationTaskResult(
        task_id="fed-2",
        source_system="ext",
        source_agent="agent-a",
        target_system="sidar",
        target_agent="supervisor",
        status="done",
        summary="ok",
        evidence=["e1"],
        next_actions=["n1"],
        protocol="swarm.federation.v1",
        meta={"correlation_id": "corr-2"},
    )

    task_result = result.to_task_result()

    assert result.protocol == FEDERATION_PROTOCOL_V1
    assert result.correlation_id == "corr-2"
    assert task_result == TaskResult(
        task_id="fed-2", status="done", summary="ok", evidence=["e1"], next_actions=["n1"]
    )
    assert "[FEDERATION RESULT]" in result.to_prompt()


def test_broker_task_envelope_post_init_from_to_and_prompt() -> None:
    task = TaskEnvelope(
        task_id="t-1",
        sender="supervisor",
        receiver="qa",
        goal="run tests",
        intent="coverage",
        parent_task_id="p-9",
        context={"correlation_id": "ctx-corr", "k": "v"},
        inputs=["pytest"],
    )

    envelope = BrokerTaskEnvelope.from_task_envelope(
        task,
        broker="redis",
        exchange="sidar.bus",
        reply_queue="reply.q",
        headers={"x": "1"},
    )

    assert envelope.protocol == BROKER_PROTOCOL_V1
    assert envelope.correlation_id == "ctx-corr"
    assert envelope.routing_key == "sidar.bus.qa.coverage"

    back = envelope.to_task_envelope()
    assert back.context["correlation_id"] == "ctx-corr"
    assert "[BROKER TASK]" in envelope.to_prompt()


def test_broker_task_envelope_keeps_existing_routing_key() -> None:
    envelope = BrokerTaskEnvelope(
        task_id="t-2",
        sender="a",
        receiver="b",
        goal="g",
        routing_key="custom.key",
    )
    assert envelope.routing_key == "custom.key"


def test_broker_task_result_post_init_from_to_and_prompt() -> None:
    result = TaskResult(
        task_id="t-3", status="failed", summary="boom", evidence=["log"], next_actions=["retry"]
    )

    broker_result = BrokerTaskResult.from_task_result(
        result,
        sender="qa",
        receiver="supervisor",
        exchange="sidar.tasks",
        headers={"correlation_id": "hdr-corr"},
    )

    assert broker_result.protocol == BROKER_PROTOCOL_V1
    assert broker_result.correlation_id == "hdr-corr"
    assert broker_result.routing_key == "sidar.tasks.supervisor.failed"

    back = broker_result.to_task_result()
    assert back == result
    assert "[BROKER RESULT]" in broker_result.to_prompt()


def test_broker_task_result_keeps_existing_routing_key() -> None:
    broker_result = BrokerTaskResult(
        task_id="t-4",
        sender="x",
        receiver="y",
        status="done",
        summary="ok",
        routing_key="done.key",
    )
    assert broker_result.routing_key == "done.key"


def test_action_feedback_to_external_trigger_and_prompt() -> None:
    feedback = ActionFeedback(
        feedback_id="fb-1",
        source_system="jira",
        source_agent="ticket-bot",
        action_name="create_issue",
        status="success",
        summary="issue created",
        related_task_id="task-9",
        details={"issue": "JIRA-1"},
        meta={"team": "platform"},
    )

    trigger = feedback.to_external_trigger()

    assert feedback.correlation_id == "task-9"
    assert trigger.source == "federation:jira:action_feedback"
    assert trigger.payload["kind"] == "action_feedback"
    assert trigger.meta["feedback_status"] == "success"
    assert trigger.correlation_id == "task-9"
    assert trigger.protocol == ACTION_FEEDBACK_PROTOCOL_V1
    assert "[ACTION FEEDBACK]" in feedback.to_prompt()


@dataclass
class _LikeP2P:
    task_id: str = "t"
    reply_to: str = "a"
    target_agent: str = "b"
    payload: str = "p"


@dataclass
class _LikeDelegationRequest:
    task_id: str = "t"
    reply_to: str = "a"
    target_agent: str = "b"
    payload: str = "p"


_LikeDelegationRequest.__name__ = "DelegationRequest"


@dataclass
class _LikeExternalTrigger:
    trigger_id: str = "tr"
    source: str = "src"
    event_name: str = "event"
    payload: dict[str, str] = None  # type: ignore[assignment]


_LikeExternalTrigger.__name__ = "ExternalTrigger"


@dataclass
class _LikeFederationTaskEnvelope:
    task_id: str = "t"
    source_system: str = "s"
    source_agent: str = "a"
    target_system: str = "tgt"
    target_agent: str = "agent"
    goal: str = "g"


_LikeFederationTaskEnvelope.__name__ = "FederationTaskEnvelope"


@dataclass
class _LikeFederationTaskResult:
    task_id: str = "t"
    source_system: str = "s"
    source_agent: str = "a"
    target_system: str = "tgt"
    target_agent: str = "agent"
    status: str = "done"
    summary: str = "ok"


_LikeFederationTaskResult.__name__ = "FederationTaskResult"


@dataclass
class _LikeActionFeedback:
    feedback_id: str = "f"
    source_system: str = "s"
    source_agent: str = "a"
    action_name: str = "act"
    status: str = "ok"
    summary: str = "done"


_LikeActionFeedback.__name__ = "ActionFeedback"


@dataclass
class _LikeBrokerTaskEnvelope:
    task_id: str = "t"
    sender: str = "s"
    receiver: str = "r"
    goal: str = "g"
    broker: str = "b"
    exchange: str = "e"
    routing_key: str = "rk"


_LikeBrokerTaskEnvelope.__name__ = "BrokerTaskEnvelope"


@dataclass
class _LikeBrokerTaskResult:
    task_id: str = "t"
    sender: str = "s"
    receiver: str = "r"
    status: str = "done"
    summary: str = "ok"
    broker: str = "b"
    exchange: str = "e"


_LikeBrokerTaskResult.__name__ = "BrokerTaskResult"


def test_type_guards_support_instances_and_duck_typing_variants() -> None:
    assert is_p2p_message(P2PMessage(task_id="t", reply_to="a", target_agent="b", payload="p"))
    assert is_p2p_message(_LikeP2P()) is False  # name is not P2PMessage/DelegationRequest
    like_p2p = _LikeP2P()
    like_p2p.__class__.__name__ = "P2PMessage"
    assert is_p2p_message(like_p2p)

    assert is_delegation_request(
        DelegationRequest(task_id="t", reply_to="a", target_agent="b", payload="p")
    )
    assert is_delegation_request(_LikeDelegationRequest())

    assert is_external_trigger(ExternalTrigger(trigger_id="tr", source="s", event_name="e"))
    assert is_external_trigger(_LikeExternalTrigger(payload={}))

    assert is_federation_task_envelope(
        FederationTaskEnvelope(
            task_id="t",
            source_system="s",
            source_agent="a",
            target_system="x",
            target_agent="y",
            goal="g",
        )
    )
    assert is_federation_task_envelope(_LikeFederationTaskEnvelope())

    assert is_federation_task_result(
        FederationTaskResult(
            task_id="t",
            source_system="s",
            source_agent="a",
            target_system="x",
            target_agent="y",
            status="ok",
            summary="sum",
        )
    )
    assert is_federation_task_result(_LikeFederationTaskResult())

    assert is_action_feedback(
        ActionFeedback(
            feedback_id="f",
            source_system="s",
            source_agent="a",
            action_name="ac",
            status="ok",
            summary="sum",
        )
    )
    assert is_action_feedback(_LikeActionFeedback())

    assert is_broker_task_envelope(
        BrokerTaskEnvelope(task_id="t", sender="s", receiver="r", goal="g")
    )
    assert is_broker_task_envelope(_LikeBrokerTaskEnvelope())

    assert is_broker_task_result(
        BrokerTaskResult(task_id="t", sender="s", receiver="r", status="ok", summary="sum")
    )
    assert is_broker_task_result(_LikeBrokerTaskResult())


def test_type_guards_reject_invalid_objects() -> None:
    assert not is_p2p_message(object())
    assert not is_delegation_request(object())
    assert not is_external_trigger(object())
    assert not is_federation_task_envelope(object())
    assert not is_federation_task_result(object())
    assert not is_action_feedback(object())
    assert not is_broker_task_envelope(object())
    assert not is_broker_task_result(object())
