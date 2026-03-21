import importlib.util
import sys
from pathlib import Path


def _load_contracts_module():
    spec = importlib.util.spec_from_file_location(
        "contracts_federation_test_mod",
        Path("agent/core/contracts.py"),
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CONTRACTS = _load_contracts_module()


def test_external_trigger_to_prompt_and_detection():
    trigger = CONTRACTS.ExternalTrigger(
        trigger_id="trg-1",
        source="webhook:github",
        event_name="push",
        payload={"branch": "main"},
        meta={"repo": "Sidar"},
    )

    prompt = trigger.to_prompt()

    assert CONTRACTS.is_external_trigger(trigger) is True
    assert "webhook:github" in prompt
    assert "correlation_id=trg-1" in prompt
    assert '"branch": "main"' in prompt


def test_federation_task_envelope_converts_to_task_envelope():
    envelope = CONTRACTS.FederationTaskEnvelope(
        task_id="fed-1",
        source_system="crewai",
        source_agent="planner",
        target_system="sidar",
        target_agent="supervisor",
        goal="Yeni issue için çözüm planı üret",
        intent="planning",
        context={"repo": "Sidar"},
        inputs=["issue #42"],
    )

    task_envelope = envelope.to_task_envelope()
    prompt = envelope.to_prompt()

    assert CONTRACTS.is_federation_task_envelope(envelope) is True
    assert task_envelope.sender == "crewai:planner"
    assert task_envelope.receiver == "sidar:supervisor"
    assert task_envelope.goal == "Yeni issue için çözüm planı üret"
    assert envelope.protocol == "federation.v1"
    assert "protocol=federation.v1" in prompt
    assert '"repo": "Sidar"' in prompt


def test_federation_protocol_normalizes_legacy_aliases():
    envelope = CONTRACTS.FederationTaskEnvelope(
        task_id="fed-legacy",
        source_system="autogen",
        source_agent="coordinator",
        target_system="sidar",
        target_agent="supervisor",
        goal="Legacy alias ile gelen görevi normalize et",
        protocol="swarm.federation.v1",
    )
    result = CONTRACTS.FederationTaskResult(
        task_id="fed-legacy",
        source_system="sidar",
        source_agent="supervisor",
        target_system="autogen",
        target_agent="coordinator",
        status="success",
        summary="ok",
        protocol="swarm.federation.v1",
    )

    assert envelope.protocol == "federation.v1"
    assert result.protocol == "federation.v1"
    assert CONTRACTS.normalize_federation_protocol("swarm.federation.v1") == "federation.v1"
    assert CONTRACTS.is_federation_task_result(result) is True
    assert result.to_task_result().status == "success"
    assert envelope.correlation_id == "fed-legacy"
    assert result.correlation_id == "fed-legacy"
    assert "protocol=federation.v1" in result.to_prompt()


def test_action_feedback_converts_to_external_trigger():
    feedback = CONTRACTS.ActionFeedback(
        feedback_id="fb-1",
        source_system="crewai",
        source_agent="planner",
        action_name="open_pr",
        status="success",
        summary="PR açıldı",
        related_task_id="fed-7",
    )

    trigger = feedback.to_external_trigger()

    assert CONTRACTS.is_action_feedback(feedback) is True
    assert trigger.event_name == "action_feedback"
    assert trigger.correlation_id == "fed-7"
    assert trigger.payload["action_name"] == "open_pr"
    assert "correlation_id=fed-7" in feedback.to_prompt()


def test_broker_task_contracts_normalize_and_convert():
    envelope = CONTRACTS.BrokerTaskEnvelope(
        task_id="brk-1",
        sender="supervisor",
        receiver="coder",
        goal="Patch hazırla",
        intent="code_generation",
        exchange="sidar.swarm",
        protocol="swarm.broker.v1",
        headers={"correlation_id": "corr-7"},
    )
    task_envelope = envelope.to_task_envelope()
    result = CONTRACTS.BrokerTaskResult.from_task_result(
        CONTRACTS.TaskResult(task_id="brk-1", status="success", summary="ok"),
        sender="coder",
        receiver="supervisor",
        correlation_id=envelope.correlation_id,
    )

    assert envelope.protocol == "broker.task.v1"
    assert envelope.routing_key == "sidar.swarm.coder.code_generation"
    assert task_envelope.context["correlation_id"] == "corr-7"
    assert CONTRACTS.is_broker_task_envelope(envelope) is True
    assert CONTRACTS.is_broker_task_result(result) is True
    assert result.to_task_result().summary == "ok"
    assert "protocol=broker.task.v1" in result.to_prompt()


def test_protocol_and_correlation_helpers_cover_custom_and_empty_values():
    assert CONTRACTS.normalize_federation_protocol(" custom.proto.v2 ") == "custom.proto.v2"
    assert CONTRACTS.normalize_broker_protocol(" swarm.broker.v1 ") == "broker.task.v1"
    assert CONTRACTS.derive_correlation_id(None, "   ", "") == ""
    assert CONTRACTS.derive_broker_routing_key(receiver="reviewer", intent="graph_review") == "sidar.swarm.reviewer.graph_review"


def test_duck_typed_contract_detection_helpers_cover_true_and_false_paths():
    p2p_like = type(
        "DelegationRequest",
        (),
        {"task_id": "t-1", "reply_to": "coder", "target_agent": "reviewer", "payload": "review"},
    )()
    p2p_missing = type("DelegationRequest", (), {"task_id": "t-1", "reply_to": "coder"})()
    trigger_like = type(
        "ExternalTrigger",
        (),
        {"trigger_id": "tr-1", "source": "webhook", "event_name": "push", "payload": {"branch": "main"}},
    )()
    trigger_missing = type("ExternalTrigger", (), {"trigger_id": "tr-1", "source": "webhook"})()
    envelope_like = type(
        "FederationTaskEnvelope",
        (),
        {
            "task_id": "fed-1",
            "source_system": "crewai",
            "source_agent": "planner",
            "target_system": "sidar",
            "target_agent": "supervisor",
            "goal": "Plan üret",
        },
    )()
    envelope_missing = type("FederationTaskEnvelope", (), {"task_id": "fed-1"})()
    result_like = type(
        "FederationTaskResult",
        (),
        {
            "task_id": "fed-1",
            "source_system": "sidar",
            "source_agent": "supervisor",
            "target_system": "crewai",
            "target_agent": "planner",
            "status": "success",
            "summary": "ok",
        },
    )()
    result_missing = type("FederationTaskResult", (), {"task_id": "fed-1", "status": "success"})()
    broker_envelope_like = type(
        "BrokerTaskEnvelope",
        (),
        {"task_id": "b-1", "sender": "supervisor", "receiver": "coder", "goal": "g", "broker": "rabbitmq", "exchange": "sidar", "routing_key": "sidar.coder.code"},
    )()
    broker_envelope_missing = type("BrokerTaskEnvelope", (), {"task_id": "b-1", "sender": "supervisor"})()
    broker_result_like = type(
        "BrokerTaskResult",
        (),
        {"task_id": "b-1", "sender": "coder", "receiver": "supervisor", "status": "queued", "summary": "ok", "broker": "rabbitmq", "exchange": "sidar"},
    )()
    broker_result_missing = type("BrokerTaskResult", (), {"task_id": "b-1", "status": "queued"})()
    feedback_like = type(
        "ActionFeedback",
        (),
        {
            "feedback_id": "fb-1",
            "source_system": "crewai",
            "source_agent": "planner",
            "action_name": "open_pr",
            "status": "success",
            "summary": "ok",
        },
    )()
    feedback_missing = type("ActionFeedback", (), {"feedback_id": "fb-1", "status": "success"})()

    assert CONTRACTS.is_p2p_message(p2p_like) is True
    assert CONTRACTS.is_delegation_request(p2p_like) is True
    assert CONTRACTS.is_p2p_message(p2p_missing) is False
    assert CONTRACTS.is_external_trigger(trigger_like) is True
    assert CONTRACTS.is_external_trigger(trigger_missing) is False
    assert CONTRACTS.is_federation_task_envelope(envelope_like) is True
    assert CONTRACTS.is_federation_task_envelope(envelope_missing) is False
    assert CONTRACTS.is_federation_task_result(result_like) is True
    assert CONTRACTS.is_federation_task_result(result_missing) is False
    assert CONTRACTS.is_broker_task_envelope(broker_envelope_like) is True
    assert CONTRACTS.is_broker_task_envelope(broker_envelope_missing) is False
    assert CONTRACTS.is_broker_task_result(broker_result_like) is True
    assert CONTRACTS.is_broker_task_result(broker_result_missing) is False
    assert CONTRACTS.is_action_feedback(feedback_like) is True
    assert CONTRACTS.is_action_feedback(feedback_missing) is False


def test_p2p_message_bumped_preserves_payload_and_meta():
    request = CONTRACTS.DelegationRequest(
        task_id="p2p-1",
        reply_to="reviewer",
        target_agent="coder",
        payload="qa_feedback|decision=reject",
        intent="review",
        parent_task_id="root-1",
        handoff_depth=1,
        meta={"reason": "qa_retry"},
    )

    bumped = request.bumped()

    assert bumped is not request
    assert bumped.handoff_depth == 2
    assert bumped.payload == request.payload
    assert bumped.parent_task_id == "root-1"
    assert bumped.meta == {"reason": "qa_retry"}
    assert bumped.sender == "reviewer"
    assert bumped.receiver == "coder"


def test_broker_task_envelope_factory_and_result_defaults_cover_conversion_paths():
    envelope = CONTRACTS.TaskEnvelope(
        task_id="task-9",
        sender="supervisor",
        receiver="reviewer",
        goal="Graf etkisini değerlendir",
        intent="review",
        parent_task_id="root-9",
        context={"correlation_id": "corr-9", "scope": "web"},
        inputs=["web_server.py"],
    )

    broker = CONTRACTS.BrokerTaskEnvelope.from_task_envelope(
        envelope,
        broker="rabbitmq",
        exchange="sidar.mesh",
        reply_queue="sidar.reply",
        headers={"tenant": "acme"},
    )
    result = CONTRACTS.BrokerTaskResult(
        task_id="task-9",
        sender="reviewer",
        receiver="supervisor",
        status="queued",
        summary="işleme alındı",
        exchange="sidar.mesh",
    )

    assert broker.broker == "rabbitmq"
    assert broker.reply_queue == "sidar.reply"
    assert broker.routing_key == "sidar.mesh.reviewer.review"
    assert broker.correlation_id == "corr-9"
    assert broker.to_task_envelope().context["scope"] == "web"
    assert broker.to_task_envelope().inputs == ["web_server.py"]
    assert result.routing_key == "sidar.mesh.supervisor.queued"
    assert result.correlation_id == "task-9"

def test_broker_protocol_keeps_custom_non_alias_values():
    assert CONTRACTS.normalize_broker_protocol(" custom.broker.v2 ") == "custom.broker.v2"


def test_broker_task_envelope_to_prompt_serializes_transport_metadata():
    envelope = CONTRACTS.BrokerTaskEnvelope(
        task_id="brk-prompt",
        sender="supervisor",
        receiver="reviewer",
        goal="İnceleme isteğini kuyruğa yaz",
        intent="review",
        exchange="sidar.mesh",
        reply_queue="sidar.reply",
        headers={"tenant": "acme"},
    )

    prompt = envelope.to_prompt()

    assert "[BROKER TASK]" in prompt
    assert "broker=memory" in prompt
    assert "routing_key=sidar.mesh.reviewer.review" in prompt
    assert 'headers={"tenant": "acme"}' in prompt
