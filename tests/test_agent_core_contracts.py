"""
agent/core/contracts.py için birim testleri.
normalize_federation_protocol, normalize_broker_protocol,
derive_broker_routing_key, derive_correlation_id,
dataclasses (TaskEnvelope, TaskResult, P2PMessage, DelegationRequest,
ExternalTrigger, FederationTaskEnvelope, FederationTaskResult,
BrokerTaskEnvelope, BrokerTaskResult, ActionFeedback),
type guards, conversion methods.
"""
from __future__ import annotations


def _get_contracts():
    import agent.core.contracts as c
    return c


# ══════════════════════════════════════════════════════════════
# Protocol constants
# ══════════════════════════════════════════════════════════════

class TestProtocolConstants:
    def test_federation_protocol_v1(self):
        c = _get_contracts()
        assert c.FEDERATION_PROTOCOL_V1 == "federation.v1"

    def test_broker_protocol_v1(self):
        c = _get_contracts()
        assert c.BROKER_PROTOCOL_V1 == "broker.task.v1"

    def test_action_feedback_protocol_v1(self):
        c = _get_contracts()
        assert c.ACTION_FEEDBACK_PROTOCOL_V1 == "action_feedback.v1"

    def test_federation_aliases_contain_legacy(self):
        c = _get_contracts()
        assert c.LEGACY_FEDERATION_PROTOCOL_V1 in c.FEDERATION_PROTOCOL_ALIASES

    def test_broker_aliases_contain_legacy(self):
        c = _get_contracts()
        assert c.LEGACY_BROKER_PROTOCOL_V1 in c.BROKER_PROTOCOL_ALIASES


# ══════════════════════════════════════════════════════════════
# normalize_federation_protocol
# ══════════════════════════════════════════════════════════════

class TestNormalizeFederationProtocol:
    def test_canonical_passthrough(self):
        c = _get_contracts()
        assert c.normalize_federation_protocol("federation.v1") == "federation.v1"

    def test_legacy_normalized(self):
        c = _get_contracts()
        assert c.normalize_federation_protocol("swarm.federation.v1") == "federation.v1"

    def test_empty_normalized(self):
        c = _get_contracts()
        assert c.normalize_federation_protocol("") == "federation.v1"

    def test_none_normalized(self):
        c = _get_contracts()
        assert c.normalize_federation_protocol(None) == "federation.v1"

    def test_unknown_preserved(self):
        c = _get_contracts()
        result = c.normalize_federation_protocol("custom.protocol")
        assert result == "custom.protocol"

    def test_case_lowercased(self):
        c = _get_contracts()
        result = c.normalize_federation_protocol("FEDERATION.V1")
        assert result == "federation.v1"


# ══════════════════════════════════════════════════════════════
# normalize_broker_protocol
# ══════════════════════════════════════════════════════════════

class TestNormalizeBrokerProtocol:
    def test_canonical_passthrough(self):
        c = _get_contracts()
        assert c.normalize_broker_protocol("broker.task.v1") == "broker.task.v1"

    def test_legacy_normalized(self):
        c = _get_contracts()
        assert c.normalize_broker_protocol("swarm.broker.v1") == "broker.task.v1"

    def test_empty_normalized(self):
        c = _get_contracts()
        assert c.normalize_broker_protocol("") == "broker.task.v1"

    def test_none_normalized(self):
        c = _get_contracts()
        assert c.normalize_broker_protocol(None) == "broker.task.v1"


# ══════════════════════════════════════════════════════════════
# derive_broker_routing_key
# ══════════════════════════════════════════════════════════════

class TestDeriveBrokerRoutingKey:
    def test_format(self):
        c = _get_contracts()
        key = c.derive_broker_routing_key(receiver="coder", intent="code_generation")
        assert "coder" in key
        assert "code_generation" in key

    def test_namespace_included(self):
        c = _get_contracts()
        key = c.derive_broker_routing_key(receiver="reviewer", intent="review", namespace="my.swarm")
        assert key.startswith("my.swarm.")

    def test_empty_receiver_fallback(self):
        c = _get_contracts()
        key = c.derive_broker_routing_key(receiver="", intent="mixed")
        assert "unknown" in key

    def test_empty_intent_fallback(self):
        c = _get_contracts()
        key = c.derive_broker_routing_key(receiver="qa", intent="")
        assert "mixed" in key


# ══════════════════════════════════════════════════════════════
# derive_correlation_id
# ══════════════════════════════════════════════════════════════

class TestDeriveCorrelationId:
    def test_first_non_empty_wins(self):
        c = _get_contracts()
        result = c.derive_correlation_id("", "  ", "abc123", "def")
        assert result == "abc123"

    def test_all_empty_returns_empty(self):
        c = _get_contracts()
        result = c.derive_correlation_id("", None, "  ")
        assert result == ""

    def test_single_value(self):
        c = _get_contracts()
        result = c.derive_correlation_id("corr-xyz")
        assert result == "corr-xyz"


# ══════════════════════════════════════════════════════════════
# TaskEnvelope
# ══════════════════════════════════════════════════════════════

class TestTaskEnvelope:
    def test_basic_fields(self):
        c = _get_contracts()
        env = c.TaskEnvelope(task_id="t1", sender="sup", receiver="coder", goal="write code")
        assert env.task_id == "t1"
        assert env.sender == "sup"
        assert env.receiver == "coder"
        assert env.goal == "write code"

    def test_defaults(self):
        c = _get_contracts()
        env = c.TaskEnvelope(task_id="t1", sender="s", receiver="r", goal="g")
        assert env.intent == "mixed"
        assert env.parent_task_id is None
        assert env.context == {}
        assert env.inputs == []


# ══════════════════════════════════════════════════════════════
# TaskResult
# ══════════════════════════════════════════════════════════════

class TestTaskResult:
    def test_basic_fields(self):
        c = _get_contracts()
        result = c.TaskResult(task_id="t1", status="success", summary="done")
        assert result.task_id == "t1"
        assert result.status == "success"
        assert result.summary == "done"

    def test_defaults(self):
        c = _get_contracts()
        result = c.TaskResult(task_id="t1", status="s", summary="x")
        assert result.evidence == []
        assert result.next_actions == []


# ══════════════════════════════════════════════════════════════
# P2PMessage
# ══════════════════════════════════════════════════════════════

class TestP2PMessage:
    def test_sender_property(self):
        c = _get_contracts()
        msg = c.P2PMessage(task_id="t1", reply_to="agent_a", target_agent="agent_b", payload="hello")
        assert msg.sender == "agent_a"

    def test_receiver_property(self):
        c = _get_contracts()
        msg = c.P2PMessage(task_id="t1", reply_to="agent_a", target_agent="agent_b", payload="hello")
        assert msg.receiver == "agent_b"

    def test_bumped_increments_depth(self):
        c = _get_contracts()
        msg = c.P2PMessage(task_id="t1", reply_to="a", target_agent="b", payload="x", handoff_depth=2)
        bumped = msg.bumped()
        assert bumped.handoff_depth == 3

    def test_bumped_preserves_fields(self):
        c = _get_contracts()
        msg = c.P2PMessage(task_id="t1", reply_to="a", target_agent="b", payload="payload", intent="review")
        bumped = msg.bumped()
        assert bumped.task_id == "t1"
        assert bumped.payload == "payload"
        assert bumped.intent == "review"


# ══════════════════════════════════════════════════════════════
# DelegationRequest
# ══════════════════════════════════════════════════════════════

class TestDelegationRequest:
    def test_is_subclass_of_p2p(self):
        c = _get_contracts()
        assert issubclass(c.DelegationRequest, c.P2PMessage)

    def test_is_p2p_message_true(self):
        c = _get_contracts()
        req = c.DelegationRequest(task_id="t1", reply_to="a", target_agent="b", payload="x")
        assert c.is_p2p_message(req) is True

    def test_is_delegation_request_true(self):
        c = _get_contracts()
        req = c.DelegationRequest(task_id="t1", reply_to="a", target_agent="b", payload="x")
        assert c.is_delegation_request(req) is True

    def test_p2p_not_delegation_request(self):
        c = _get_contracts()
        msg = c.P2PMessage(task_id="t1", reply_to="a", target_agent="b", payload="x")
        assert c.is_delegation_request(msg) is False


# ══════════════════════════════════════════════════════════════
# ExternalTrigger
# ══════════════════════════════════════════════════════════════

class TestExternalTrigger:
    def test_correlation_id_from_trigger_id(self):
        c = _get_contracts()
        trig = c.ExternalTrigger(trigger_id="trig-1", source="webhook", event_name="deploy")
        assert trig.correlation_id == "trig-1"

    def test_correlation_id_from_payload(self):
        c = _get_contracts()
        trig = c.ExternalTrigger(
            trigger_id="trig-1",
            source="cron",
            event_name="tick",
            payload={"correlation_id": "corr-abc"},
        )
        assert trig.correlation_id == "corr-abc"

    def test_to_prompt_contains_source(self):
        c = _get_contracts()
        trig = c.ExternalTrigger(trigger_id="t1", source="my_source", event_name="ping")
        prompt = trig.to_prompt()
        assert "my_source" in prompt

    def test_to_prompt_contains_event(self):
        c = _get_contracts()
        trig = c.ExternalTrigger(trigger_id="t1", source="s", event_name="deploy_started")
        prompt = trig.to_prompt()
        assert "deploy_started" in prompt

    def test_is_external_trigger_true(self):
        c = _get_contracts()
        trig = c.ExternalTrigger(trigger_id="t1", source="s", event_name="e")
        assert c.is_external_trigger(trig) is True

    def test_non_trigger_returns_false(self):
        c = _get_contracts()
        assert c.is_external_trigger("not a trigger") is False


# ══════════════════════════════════════════════════════════════
# FederationTaskEnvelope
# ══════════════════════════════════════════════════════════════

class TestFederationTaskEnvelope:
    def _make(self):
        c = _get_contracts()
        return c.FederationTaskEnvelope(
            task_id="fed-1",
            source_system="sidar",
            source_agent="supervisor",
            target_system="remote",
            target_agent="coder",
            goal="Write a function",
        )

    def test_protocol_normalized(self):
        env = self._make()
        c = _get_contracts()
        assert env.protocol == c.FEDERATION_PROTOCOL_V1

    def test_correlation_id_set(self):
        env = self._make()
        assert env.correlation_id == "fed-1"

    def test_to_task_envelope_conversion(self):
        env = self._make()
        te = env.to_task_envelope()
        c = _get_contracts()
        assert te.task_id == "fed-1"
        assert "sidar" in te.sender
        assert "remote" in te.receiver

    def test_to_prompt_contains_goal(self):
        env = self._make()
        prompt = env.to_prompt()
        assert "Write a function" in prompt

    def test_is_federation_task_envelope_true(self):
        env = self._make()
        c = _get_contracts()
        assert c.is_federation_task_envelope(env) is True


# ══════════════════════════════════════════════════════════════
# FederationTaskResult
# ══════════════════════════════════════════════════════════════

class TestFederationTaskResult:
    def _make(self):
        c = _get_contracts()
        return c.FederationTaskResult(
            task_id="res-1",
            source_system="remote",
            source_agent="coder",
            target_system="sidar",
            target_agent="supervisor",
            status="success",
            summary="Function written",
        )

    def test_protocol_normalized(self):
        r = self._make()
        c = _get_contracts()
        assert r.protocol == c.FEDERATION_PROTOCOL_V1

    def test_to_task_result(self):
        r = self._make()
        tr = r.to_task_result()
        assert tr.task_id == "res-1"
        assert tr.status == "success"

    def test_to_prompt_contains_status(self):
        r = self._make()
        assert "success" in r.to_prompt()

    def test_is_federation_task_result_true(self):
        r = self._make()
        c = _get_contracts()
        assert c.is_federation_task_result(r) is True


# ══════════════════════════════════════════════════════════════
# BrokerTaskEnvelope
# ══════════════════════════════════════════════════════════════

class TestBrokerTaskEnvelope:
    def _make(self):
        c = _get_contracts()
        return c.BrokerTaskEnvelope(
            task_id="broker-1",
            sender="supervisor",
            receiver="coder",
            goal="Build module",
            intent="code_generation",
        )

    def test_protocol_normalized(self):
        env = self._make()
        c = _get_contracts()
        assert env.protocol == c.BROKER_PROTOCOL_V1

    def test_routing_key_auto_generated(self):
        env = self._make()
        assert "coder" in env.routing_key

    def test_correlation_id_from_task_id(self):
        env = self._make()
        assert env.correlation_id == "broker-1"

    def test_from_task_envelope(self):
        c = _get_contracts()
        te = c.TaskEnvelope(task_id="t1", sender="sup", receiver="coder", goal="Write code")
        broker_env = c.BrokerTaskEnvelope.from_task_envelope(te)
        assert broker_env.task_id == "t1"
        assert broker_env.goal == "Write code"

    def test_to_task_envelope(self):
        env = self._make()
        te = env.to_task_envelope()
        assert te.task_id == "broker-1"
        assert te.goal == "Build module"

    def test_to_prompt_contains_broker(self):
        env = self._make()
        prompt = env.to_prompt()
        assert "broker" in prompt.lower()

    def test_is_broker_task_envelope_true(self):
        env = self._make()
        c = _get_contracts()
        assert c.is_broker_task_envelope(env) is True


# ══════════════════════════════════════════════════════════════
# BrokerTaskResult
# ══════════════════════════════════════════════════════════════

class TestBrokerTaskResult:
    def _make(self):
        c = _get_contracts()
        return c.BrokerTaskResult(
            task_id="res-1",
            sender="coder",
            receiver="supervisor",
            status="success",
            summary="Done",
        )

    def test_protocol_normalized(self):
        r = self._make()
        c = _get_contracts()
        assert r.protocol == c.BROKER_PROTOCOL_V1

    def test_routing_key_auto_generated(self):
        r = self._make()
        assert r.routing_key  # non-empty

    def test_from_task_result(self):
        c = _get_contracts()
        tr = c.TaskResult(task_id="t1", status="success", summary="ok")
        br = c.BrokerTaskResult.from_task_result(tr, sender="coder", receiver="supervisor")
        assert br.task_id == "t1"
        assert br.status == "success"

    def test_to_task_result(self):
        r = self._make()
        tr = r.to_task_result()
        assert tr.status == "success"

    def test_is_broker_task_result_true(self):
        r = self._make()
        c = _get_contracts()
        assert c.is_broker_task_result(r) is True


# ══════════════════════════════════════════════════════════════
# ActionFeedback
# ══════════════════════════════════════════════════════════════

class TestActionFeedback:
    def _make(self):
        c = _get_contracts()
        return c.ActionFeedback(
            feedback_id="fb-1",
            source_system="jira",
            source_agent="webhook",
            action_name="create_issue",
            status="success",
            summary="Issue created",
        )

    def test_correlation_id_from_feedback_id(self):
        fb = self._make()
        assert fb.correlation_id == "fb-1"

    def test_to_external_trigger(self):
        fb = self._make()
        trig = fb.to_external_trigger()
        c = _get_contracts()
        assert c.is_external_trigger(trig) is True
        assert trig.event_name == "action_feedback"

    def test_to_prompt_contains_action(self):
        fb = self._make()
        prompt = fb.to_prompt()
        assert "create_issue" in prompt

    def test_is_action_feedback_true(self):
        fb = self._make()
        c = _get_contracts()
        assert c.is_action_feedback(fb) is True
