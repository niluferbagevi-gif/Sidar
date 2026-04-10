from agent.core.contracts import (
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


def test_protocol_normalization_and_helpers():
    assert normalize_federation_protocol("SWARM.FEDERATION.V1") == "federation.v1"
    assert normalize_broker_protocol("swarm.broker.v1") == "broker.task.v1"
    assert derive_broker_routing_key(receiver="QA", intent="Review") == "sidar.swarm.qa.review"
    assert derive_correlation_id("", None, "cid-123", "fallback") == "cid-123"


def test_p2p_and_delegation_duck_typing():
    p2p = P2PMessage(task_id="t1", reply_to="coder", target_agent="qa", payload="please check")
    bumped = p2p.bumped()
    req = DelegationRequest(task_id="t2", reply_to="qa", target_agent="reviewer", payload="handoff")

    assert bumped.handoff_depth == p2p.handoff_depth + 1
    assert bumped.sender == "coder"
    assert bumped.receiver == "qa"
    assert is_p2p_message(p2p)
    assert is_delegation_request(req)


def test_external_trigger_and_action_feedback_conversion():
    feedback = ActionFeedback(
        feedback_id="fb-1",
        source_system="github",
        source_agent="bot",
        action_name="merge",
        status="ok",
        summary="merged",
        related_task_id="task-9",
    )

    trigger = feedback.to_external_trigger()

    assert is_action_feedback(feedback)
    assert is_external_trigger(trigger)
    assert trigger.correlation_id == "task-9"
    assert "action_feedback" in trigger.to_prompt()


def test_federation_envelope_and_result_conversion():
    fed = FederationTaskEnvelope(
        task_id="f1",
        source_system="sidar",
        source_agent="supervisor",
        target_system="remote",
        target_agent="analyst",
        goal="investigate",
        protocol="swarm.federation.v1",
        parent_task_id="p0",
    )
    envelope = fed.to_task_envelope()

    result = FederationTaskResult(
        task_id="f1",
        source_system="remote",
        source_agent="analyst",
        target_system="sidar",
        target_agent="supervisor",
        status="done",
        summary="completed",
    )

    assert fed.protocol == "federation.v1"
    assert envelope.context["correlation_id"] == "p0"
    assert result.to_task_result().summary == "completed"
    assert is_federation_task_envelope(fed)
    assert is_federation_task_result(result)


def test_broker_envelope_and_result_roundtrip():
    task = TaskEnvelope(task_id="t-1", sender="sup", receiver="qa", goal="validate")
    broker = BrokerTaskEnvelope.from_task_envelope(task, headers={"correlation_id": "cid-7"})
    back = broker.to_task_envelope()

    tr = TaskResult(task_id="t-1", status="ok", summary="fine")
    broker_result = BrokerTaskResult.from_task_result(tr, sender="qa", receiver="sup")

    assert is_broker_task_envelope(broker)
    assert is_broker_task_result(broker_result)
    assert broker.protocol == "broker.task.v1"
    assert back.task_id == "t-1"
    assert broker_result.to_task_result().status == "ok"
    assert "BROKER RESULT" in broker_result.to_prompt()


def test_external_trigger_post_init_correlation_priority():
    trigger = ExternalTrigger(
        trigger_id="tr-1",
        source="cron",
        event_name="nightly",
        payload={"task_id": "payload-task"},
        meta={"correlation_id": "meta-cid"},
        correlation_id="",
    )

    assert trigger.correlation_id == "meta-cid"
