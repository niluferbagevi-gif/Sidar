from __future__ import annotations

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


def test_normalizers_and_correlation_and_routing_fallbacks() -> None:
    assert normalize_federation_protocol(None) == "federation.v1"
    assert normalize_federation_protocol(" SWARM.FEDERATION.V1 ") == "federation.v1"
    assert normalize_federation_protocol("custom.v2") == "custom.v2"

    assert normalize_broker_protocol("") == "broker.task.v1"
    assert normalize_broker_protocol(" SWARM.BROKER.V1 ") == "broker.task.v1"
    assert normalize_broker_protocol("broker.custom") == "broker.custom"

    assert derive_broker_routing_key(receiver="", intent="", namespace="") == "sidar.swarm.unknown.mixed"
    assert derive_correlation_id(None, "", "  ") == ""
    assert derive_correlation_id(None, "", " c-42 ", "later") == "c-42"


def test_p2p_message_properties_and_bumped() -> None:
    msg = P2PMessage(
        task_id="t-1",
        reply_to="sender-agent",
        target_agent="qa-agent",
        payload="run",
        handoff_depth=2,
        meta={"k": "v"},
    )

    bumped = msg.bumped()

    assert msg.sender == "sender-agent"
    assert msg.receiver == "qa-agent"
    assert bumped.handoff_depth == 3
    assert bumped.meta == {"k": "v"}
    assert bumped.meta is not msg.meta


def test_external_trigger_correlation_and_prompt_with_non_dict_payload() -> None:
    trigger = ExternalTrigger(
        trigger_id="tr-1",
        source="cron",
        event_name="nightly",
        payload="non-dict",
        meta={"correlation_id": "meta-cid"},
    )

    assert trigger.correlation_id == "meta-cid"
    prompt = trigger.to_prompt()
    assert "[TRIGGER]" in prompt
    assert "source=cron" in prompt
    assert "payload=\"non-dict\"" in prompt


def test_federation_envelope_and_result_conversion_prompt_and_correlation() -> None:
    env = FederationTaskEnvelope(
        task_id="task-1",
        source_system="sidar",
        source_agent="sup",
        target_system="ext",
        target_agent="worker",
        goal="analyze",
        protocol="SWARM.FEDERATION.V1",
        parent_task_id="parent-1",
        context={"x": "1"},
        inputs=["in"],
    )
    task_env = env.to_task_envelope()
    assert env.protocol == "federation.v1"
    assert env.correlation_id == "parent-1"
    assert task_env.sender == "sidar:sup"
    assert task_env.receiver == "ext:worker"
    assert task_env.context["correlation_id"] == "parent-1"
    assert "[FEDERATION TASK]" in env.to_prompt()

    result = FederationTaskResult(
        task_id="task-1",
        source_system="ext",
        source_agent="worker",
        target_system="sidar",
        target_agent="sup",
        status="ok",
        summary="done",
        protocol="SWARM.FEDERATION.V1",
        meta={"correlation_id": "meta-cid"},
        evidence=["e1"],
        next_actions=["n1"],
    )
    task_result = result.to_task_result()

    assert result.protocol == "federation.v1"
    assert result.correlation_id == "meta-cid"
    assert isinstance(task_result, TaskResult)
    assert task_result.evidence == ["e1"]
    assert "[FEDERATION RESULT]" in result.to_prompt()


def test_broker_envelope_and_result_lifecycle_and_prompt() -> None:
    env = TaskEnvelope(
        task_id="t-22",
        sender="sup",
        receiver="qa",
        goal="g",
        intent="coverage",
        parent_task_id="p-22",
        context={"correlation_id": "ctx-cid", "k": "v"},
        inputs=["i1"],
    )
    broker_env = BrokerTaskEnvelope.from_task_envelope(
        env,
        broker="rabbit",
        exchange="SIDAR.Exchange",
        reply_queue="reply.q",
        headers={"h": "1"},
    )

    assert broker_env.protocol == "broker.task.v1"
    assert broker_env.correlation_id == "ctx-cid"
    assert broker_env.routing_key == "sidar.exchange.qa.coverage"
    assert broker_env.to_task_envelope().context["correlation_id"] == "ctx-cid"
    assert "[BROKER TASK]" in broker_env.to_prompt()

    explicit_rk = BrokerTaskEnvelope(
        task_id="t-23",
        sender="a",
        receiver="b",
        goal="g",
        routing_key="already.set",
    )
    assert explicit_rk.routing_key == "already.set"

    tr = TaskResult(task_id="t-22", status="success", summary="ok", evidence=["ev"], next_actions=["next"])
    broker_result = BrokerTaskResult.from_task_result(
        tr,
        sender="qa",
        receiver="sup",
        exchange="sidar.swarm",
        headers={"correlation_id": "hdr-cid"},
    )

    assert broker_result.correlation_id == "hdr-cid"
    assert broker_result.routing_key == "sidar.swarm.sup.success"
    assert broker_result.to_task_result().summary == "ok"
    assert "[BROKER RESULT]" in broker_result.to_prompt()

    explicit_result_rk = BrokerTaskResult(
        task_id="t-24",
        sender="qa",
        receiver="sup",
        status="ok",
        summary="sum",
        routing_key="fixed.key",
    )
    assert explicit_result_rk.routing_key == "fixed.key"


def test_action_feedback_to_external_trigger_and_prompt() -> None:
    fb = ActionFeedback(
        feedback_id="fb-1",
        source_system="ext",
        source_agent="runner",
        action_name="deploy",
        status="ok",
        summary="done",
        related_task_id="task-9",
        details={"duration": 3},
        meta={"tenant": "acme"},
    )

    assert fb.correlation_id == "task-9"
    trigger = fb.to_external_trigger()

    assert isinstance(trigger, ExternalTrigger)
    assert trigger.source == "federation:ext:action_feedback"
    assert trigger.payload["kind"] == "action_feedback"
    assert trigger.meta["feedback_status"] == "ok"
    assert "[ACTION FEEDBACK]" in fb.to_prompt()


def test_duck_typing_helpers_true_and_false_paths() -> None:
    p2p = P2PMessage(task_id="1", reply_to="a", target_agent="b", payload="x")
    deleg = DelegationRequest(task_id="2", reply_to="a", target_agent="b", payload="x")
    ext = ExternalTrigger(trigger_id="tr", source="s", event_name="e", payload={})
    fenv = FederationTaskEnvelope(
        task_id="f1",
        source_system="s1",
        source_agent="a1",
        target_system="s2",
        target_agent="a2",
        goal="g",
    )
    fres = FederationTaskResult(
        task_id="f2",
        source_system="s1",
        source_agent="a1",
        target_system="s2",
        target_agent="a2",
        status="ok",
        summary="sum",
    )
    fb = ActionFeedback(
        feedback_id="fb", source_system="s", source_agent="a", action_name="act", status="ok", summary="sum"
    )
    benv = BrokerTaskEnvelope(task_id="b1", sender="s", receiver="r", goal="g")
    bres = BrokerTaskResult(task_id="b2", sender="s", receiver="r", status="ok", summary="sum")

    assert is_p2p_message(p2p) is True
    assert is_delegation_request(deleg) is True
    assert is_external_trigger(ext) is True
    assert is_federation_task_envelope(fenv) is True
    assert is_federation_task_result(fres) is True
    assert is_action_feedback(fb) is True
    assert is_broker_task_envelope(benv) is True
    assert is_broker_task_result(bres) is True

    DuckP2P = type("P2PMessage", (), {"task_id": "1", "reply_to": "a", "target_agent": "b", "payload": "x"})
    DuckDeleg = type(
        "DelegationRequest",
        (),
        {"task_id": "1", "reply_to": "a", "target_agent": "b", "payload": "x"},
    )
    DuckExt = type("ExternalTrigger", (), {"trigger_id": "1", "source": "s", "event_name": "e", "payload": {}})
    DuckFEnv = type(
        "FederationTaskEnvelope",
        (),
        {"task_id": "1", "source_system": "s", "source_agent": "a", "target_system": "t", "target_agent": "b", "goal": "g"},
    )
    DuckFRes = type(
        "FederationTaskResult",
        (),
        {
            "task_id": "1",
            "source_system": "s",
            "source_agent": "a",
            "target_system": "t",
            "target_agent": "b",
            "status": "ok",
            "summary": "sum",
        },
    )
    DuckFb = type(
        "ActionFeedback",
        (),
        {"feedback_id": "f", "source_system": "s", "source_agent": "a", "action_name": "act", "status": "ok", "summary": "sum"},
    )
    DuckBEnv = type(
        "BrokerTaskEnvelope",
        (),
        {"task_id": "1", "sender": "s", "receiver": "r", "goal": "g", "broker": "b", "exchange": "e", "routing_key": "rk"},
    )
    DuckBRes = type(
        "BrokerTaskResult",
        (),
        {"task_id": "1", "sender": "s", "receiver": "r", "status": "ok", "summary": "sum", "broker": "b", "exchange": "e"},
    )

    assert is_p2p_message(DuckP2P()) is True
    assert is_delegation_request(DuckDeleg()) is True
    assert is_external_trigger(DuckExt()) is True
    assert is_federation_task_envelope(DuckFEnv()) is True
    assert is_federation_task_result(DuckFRes()) is True
    assert is_action_feedback(DuckFb()) is True
    assert is_broker_task_envelope(DuckBEnv()) is True
    assert is_broker_task_result(DuckBRes()) is True

    assert is_p2p_message(object()) is False
    assert is_delegation_request(object()) is False
    assert is_external_trigger(object()) is False
    assert is_federation_task_envelope(object()) is False
    assert is_federation_task_result(object()) is False
    assert is_action_feedback(object()) is False
    assert is_broker_task_envelope(object()) is False
    assert is_broker_task_result(object()) is False
