"""
agent/core/contracts.py için birim testleri.
Saf stdlib modülü; stub gerekmez.
"""
from __future__ import annotations

import pathlib as _pl
import sys
import types as _types

import pytest

_proj = _pl.Path(__file__).parent.parent


def _get_contracts():
    # agent package stub — __path__ ile __init__.py çalışması engellenir
    if "agent" not in sys.modules:
        _pkg = _types.ModuleType("agent")
        _pkg.__path__ = [str(_proj / "agent")]
        _pkg.__package__ = "agent"
        sys.modules["agent"] = _pkg

    # agent.core stub — __path__ ile submodule import çalışır
    if "agent.core" not in sys.modules:
        core_pkg = _types.ModuleType("agent.core")
        core_pkg.__path__ = [str(_proj / "agent" / "core")]
        core_pkg.__package__ = "agent.core"
        sys.modules["agent.core"] = core_pkg
    else:
        core_pkg = sys.modules["agent.core"]
        if not hasattr(core_pkg, "__path__"):
            core_pkg.__path__ = [str(_proj / "agent" / "core")]
            core_pkg.__package__ = "agent.core"

    sys.modules.pop("agent.core.contracts", None)
    import agent.core.contracts as c
    return c


# ── Sabitler ─────────────────────────────────────────────────────────────────

class TestProtocolConstants:
    def test_federation_protocol_v1(self):
        c = _get_contracts()
        assert c.FEDERATION_PROTOCOL_V1 == "federation.v1"

    def test_legacy_federation_protocol_v1(self):
        c = _get_contracts()
        assert c.LEGACY_FEDERATION_PROTOCOL_V1 == "swarm.federation.v1"

    def test_broker_protocol_v1(self):
        c = _get_contracts()
        assert c.BROKER_PROTOCOL_V1 == "broker.task.v1"

    def test_legacy_broker_protocol_v1(self):
        c = _get_contracts()
        assert c.LEGACY_BROKER_PROTOCOL_V1 == "swarm.broker.v1"

    def test_federation_aliases_contains_both(self):
        c = _get_contracts()
        assert "federation.v1" in c.FEDERATION_PROTOCOL_ALIASES
        assert "swarm.federation.v1" in c.FEDERATION_PROTOCOL_ALIASES

    def test_broker_aliases_contains_both(self):
        c = _get_contracts()
        assert "broker.task.v1" in c.BROKER_PROTOCOL_ALIASES
        assert "swarm.broker.v1" in c.BROKER_PROTOCOL_ALIASES


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

class TestNormalizeFederationProtocol:
    def test_empty_returns_canonical(self):
        c = _get_contracts()
        assert c.normalize_federation_protocol("") == "federation.v1"

    def test_none_returns_canonical(self):
        c = _get_contracts()
        assert c.normalize_federation_protocol(None) == "federation.v1"

    def test_canonical_unchanged(self):
        c = _get_contracts()
        assert c.normalize_federation_protocol("federation.v1") == "federation.v1"

    def test_legacy_alias_normalized(self):
        c = _get_contracts()
        assert c.normalize_federation_protocol("swarm.federation.v1") == "federation.v1"

    def test_unknown_protocol_preserved(self):
        c = _get_contracts()
        assert c.normalize_federation_protocol("custom.v2") == "custom.v2"


class TestNormalizeBrokerProtocol:
    def test_empty_returns_canonical(self):
        c = _get_contracts()
        assert c.normalize_broker_protocol("") == "broker.task.v1"

    def test_none_returns_canonical(self):
        c = _get_contracts()
        assert c.normalize_broker_protocol(None) == "broker.task.v1"

    def test_legacy_alias_normalized(self):
        c = _get_contracts()
        assert c.normalize_broker_protocol("swarm.broker.v1") == "broker.task.v1"

    def test_unknown_protocol_preserved(self):
        c = _get_contracts()
        assert c.normalize_broker_protocol("rabbitmq.v3") == "rabbitmq.v3"


class TestDeriveBrokerRoutingKey:
    def test_basic_routing_key(self):
        c = _get_contracts()
        key = c.derive_broker_routing_key(receiver="coder", intent="code")
        assert key == "sidar.swarm.coder.code"

    def test_custom_namespace(self):
        c = _get_contracts()
        key = c.derive_broker_routing_key(receiver="reviewer", intent="review", namespace="my.ns")
        assert key == "my.ns.reviewer.review"

    def test_empty_receiver_defaults_unknown(self):
        c = _get_contracts()
        key = c.derive_broker_routing_key(receiver="", intent="mixed")
        assert "unknown" in key

    def test_empty_intent_defaults_mixed(self):
        c = _get_contracts()
        key = c.derive_broker_routing_key(receiver="coder", intent="")
        assert "mixed" in key


class TestDeriveCorrelationId:
    def test_first_non_empty(self):
        c = _get_contracts()
        assert c.derive_correlation_id("", None, "abc", "def") == "abc"

    def test_all_empty_returns_empty_string(self):
        c = _get_contracts()
        assert c.derive_correlation_id("", None, "") == ""

    def test_single_value(self):
        c = _get_contracts()
        assert c.derive_correlation_id("xyz") == "xyz"

    def test_none_only_returns_empty(self):
        c = _get_contracts()
        assert c.derive_correlation_id(None, None) == ""


# ── Dataclass'lar ─────────────────────────────────────────────────────────────

class TestTaskEnvelope:
    def test_required_fields(self):
        c = _get_contracts()
        e = c.TaskEnvelope(task_id="t1", sender="s", receiver="r", goal="görev")
        assert e.task_id == "t1"
        assert e.goal == "görev"

    def test_defaults(self):
        c = _get_contracts()
        e = c.TaskEnvelope(task_id="t1", sender="s", receiver="r", goal="görev")
        assert e.intent == "mixed"
        assert e.parent_task_id is None
        assert e.context == {}
        assert e.inputs == []


class TestTaskResult:
    def test_required_fields(self):
        c = _get_contracts()
        r = c.TaskResult(task_id="t1", status="success", summary="özet")
        assert r.task_id == "t1"
        assert r.status == "success"

    def test_defaults(self):
        c = _get_contracts()
        r = c.TaskResult(task_id="t1", status="success", summary="özet")
        assert r.evidence == []
        assert r.next_actions == []


class TestP2PMessage:
    def test_sender_receiver_properties(self):
        c = _get_contracts()
        msg = c.P2PMessage(task_id="t1", reply_to="agent_a", target_agent="agent_b", payload="içerik")
        assert msg.sender == "agent_a"
        assert msg.receiver == "agent_b"

    def test_bumped_increments_depth(self):
        c = _get_contracts()
        msg = c.P2PMessage(task_id="t1", reply_to="a", target_agent="b", payload="p")
        bumped = msg.bumped()
        assert bumped.handoff_depth == 1

    def test_bumped_copies_meta(self):
        c = _get_contracts()
        msg = c.P2PMessage(task_id="t1", reply_to="a", target_agent="b", payload="p", meta={"key": "val"})
        bumped = msg.bumped()
        assert bumped.meta == {"key": "val"}
        bumped.meta["new"] = "x"
        assert "new" not in msg.meta


class TestDelegationRequest:
    def test_is_subclass_of_p2p(self):
        c = _get_contracts()
        req = c.DelegationRequest(task_id="t1", reply_to="a", target_agent="b", payload="p")
        assert isinstance(req, c.P2PMessage)

    def test_bumped_returns_delegation_request(self):
        c = _get_contracts()
        req = c.DelegationRequest(task_id="t1", reply_to="a", target_agent="b", payload="p")
        bumped = req.bumped()
        assert isinstance(bumped, c.DelegationRequest)


class TestDelegationResult:
    def test_fields(self):
        c = _get_contracts()
        dr = c.DelegationResult(task_id="t1", source_agent="a", target_agent="b", status="success", content="içerik")
        assert dr.content == "içerik"


class TestExternalTrigger:
    def test_post_init_sets_correlation_id(self):
        c = _get_contracts()
        t = c.ExternalTrigger(trigger_id="trig-1", source="webhook", event_name="ci_failure")
        assert t.correlation_id == "trig-1"

    def test_post_init_prefers_existing_correlation_id(self):
        c = _get_contracts()
        t = c.ExternalTrigger(trigger_id="trig-1", source="s", event_name="e", correlation_id="cid-99")
        assert t.correlation_id == "cid-99"

    def test_to_prompt_contains_event_name(self):
        c = _get_contracts()
        t = c.ExternalTrigger(trigger_id="t1", source="src", event_name="deploy")
        prompt = t.to_prompt()
        assert "[TRIGGER]" in prompt
        assert "deploy" in prompt

    def test_to_prompt_contains_payload(self):
        c = _get_contracts()
        t = c.ExternalTrigger(trigger_id="t1", source="s", event_name="e", payload={"key": "val"})
        assert "val" in t.to_prompt()


class TestFederationTaskEnvelope:
    def test_post_init_normalizes_protocol(self):
        c = _get_contracts()
        env = c.FederationTaskEnvelope(
            task_id="t1", source_system="sys_a", source_agent="a",
            target_system="sidar", target_agent="supervisor", goal="görev",
            protocol="swarm.federation.v1",
        )
        assert env.protocol == "federation.v1"

    def test_to_task_envelope(self):
        c = _get_contracts()
        env = c.FederationTaskEnvelope(
            task_id="t1", source_system="sys_a", source_agent="a",
            target_system="sidar", target_agent="sup", goal="hedef",
        )
        te = env.to_task_envelope()
        assert te.task_id == "t1"
        assert te.goal == "hedef"
        assert "sys_a:a" in te.sender

    def test_to_prompt_contains_federation_task(self):
        c = _get_contracts()
        env = c.FederationTaskEnvelope(
            task_id="t1", source_system="sys_a", source_agent="a",
            target_system="sidar", target_agent="sup", goal="hedef görev",
        )
        prompt = env.to_prompt()
        assert "[FEDERATION TASK]" in prompt
        assert "hedef görev" in prompt

    def test_correlation_id_derived_from_task_id(self):
        c = _get_contracts()
        env = c.FederationTaskEnvelope(
            task_id="task-xyz", source_system="s", source_agent="a",
            target_system="t", target_agent="b", goal="g",
        )
        assert env.correlation_id == "task-xyz"


class TestFederationTaskResult:
    def test_to_task_result(self):
        c = _get_contracts()
        r = c.FederationTaskResult(
            task_id="t1", source_system="s", source_agent="a",
            target_system="t", target_agent="b",
            status="success", summary="özet",
        )
        tr = r.to_task_result()
        assert tr.task_id == "t1"
        assert tr.status == "success"

    def test_to_prompt_contains_federation_result(self):
        c = _get_contracts()
        r = c.FederationTaskResult(
            task_id="t1", source_system="s", source_agent="a",
            target_system="t", target_agent="b", status="success", summary="tamamlandı",
        )
        prompt = r.to_prompt()
        assert "[FEDERATION RESULT]" in prompt
        assert "tamamlandı" in prompt

    def test_post_init_normalizes_protocol(self):
        c = _get_contracts()
        r = c.FederationTaskResult(
            task_id="t1", source_system="s", source_agent="a",
            target_system="t", target_agent="b", status="success", summary="özet",
            protocol="swarm.federation.v1",
        )
        assert r.protocol == "federation.v1"


class TestBrokerTaskEnvelope:
    def test_post_init_derives_routing_key(self):
        c = _get_contracts()
        env = c.BrokerTaskEnvelope(task_id="t1", sender="s", receiver="coder", goal="görev", intent="code")
        assert "coder" in env.routing_key
        assert "code" in env.routing_key

    def test_post_init_normalizes_protocol(self):
        c = _get_contracts()
        env = c.BrokerTaskEnvelope(
            task_id="t1", sender="s", receiver="r", goal="g", protocol="swarm.broker.v1"
        )
        assert env.protocol == "broker.task.v1"

    def test_from_task_envelope(self):
        c = _get_contracts()
        te = c.TaskEnvelope(task_id="t1", sender="s", receiver="r", goal="hedef")
        be = c.BrokerTaskEnvelope.from_task_envelope(te)
        assert be.task_id == "t1"
        assert be.goal == "hedef"

    def test_to_task_envelope(self):
        c = _get_contracts()
        env = c.BrokerTaskEnvelope(task_id="t1", sender="s", receiver="r", goal="g")
        te = env.to_task_envelope()
        assert te.task_id == "t1"
        assert te.goal == "g"

    def test_to_prompt_contains_broker_task(self):
        c = _get_contracts()
        env = c.BrokerTaskEnvelope(task_id="t1", sender="s", receiver="r", goal="g")
        assert "[BROKER TASK]" in env.to_prompt()

    def test_explicit_routing_key_not_overridden(self):
        c = _get_contracts()
        env = c.BrokerTaskEnvelope(
            task_id="t1", sender="s", receiver="r", goal="g", routing_key="custom.key"
        )
        assert env.routing_key == "custom.key"


class TestBrokerTaskResult:
    def test_post_init_derives_routing_key(self):
        c = _get_contracts()
        r = c.BrokerTaskResult(task_id="t1", sender="s", receiver="coder", status="success", summary="özet")
        assert r.routing_key != ""

    def test_from_task_result(self):
        c = _get_contracts()
        tr = c.TaskResult(task_id="t1", status="success", summary="özet")
        br = c.BrokerTaskResult.from_task_result(tr, sender="s", receiver="r")
        assert br.task_id == "t1"
        assert br.status == "success"

    def test_to_task_result(self):
        c = _get_contracts()
        br = c.BrokerTaskResult(task_id="t1", sender="s", receiver="r", status="success", summary="özet")
        tr = br.to_task_result()
        assert tr.task_id == "t1"

    def test_to_prompt_contains_broker_result(self):
        c = _get_contracts()
        br = c.BrokerTaskResult(task_id="t1", sender="s", receiver="r", status="success", summary="özet")
        assert "[BROKER RESULT]" in br.to_prompt()


class TestActionFeedback:
    def test_post_init_derives_correlation_id(self):
        c = _get_contracts()
        fb = c.ActionFeedback(
            feedback_id="fb-1", source_system="sys_a", source_agent="bot",
            action_name="deploy", status="success", summary="başarılı",
        )
        assert fb.correlation_id == "fb-1"

    def test_to_external_trigger(self):
        c = _get_contracts()
        fb = c.ActionFeedback(
            feedback_id="fb-1", source_system="sys_a", source_agent="bot",
            action_name="deploy", status="success", summary="başarılı",
        )
        trigger = fb.to_external_trigger()
        assert trigger.event_name == "action_feedback"
        assert trigger.trigger_id == "fb-1"

    def test_to_prompt_contains_action_feedback(self):
        c = _get_contracts()
        fb = c.ActionFeedback(
            feedback_id="fb-1", source_system="s", source_agent="bot",
            action_name="release", status="success", summary="tamam",
        )
        prompt = fb.to_prompt()
        assert "[ACTION FEEDBACK]" in prompt
        assert "release" in prompt


# ── is_* tür kontrolcüleri ────────────────────────────────────────────────────

class TestTypeCheckers:
    def test_is_p2p_message_true(self):
        c = _get_contracts()
        msg = c.P2PMessage(task_id="t", reply_to="a", target_agent="b", payload="p")
        assert c.is_p2p_message(msg) is True

    def test_is_p2p_message_false_for_str(self):
        c = _get_contracts()
        assert c.is_p2p_message("not a message") is False

    def test_is_delegation_request_true(self):
        c = _get_contracts()
        req = c.DelegationRequest(task_id="t", reply_to="a", target_agent="b", payload="p")
        assert c.is_delegation_request(req) is True

    def test_is_delegation_request_false_for_p2p(self):
        c = _get_contracts()
        msg = c.P2PMessage(task_id="t", reply_to="a", target_agent="b", payload="p")
        assert c.is_delegation_request(msg) is False

    def test_is_external_trigger_true(self):
        c = _get_contracts()
        t = c.ExternalTrigger(trigger_id="t1", source="s", event_name="e")
        assert c.is_external_trigger(t) is True

    def test_is_external_trigger_false(self):
        c = _get_contracts()
        assert c.is_external_trigger("string") is False

    def test_is_federation_task_envelope_true(self):
        c = _get_contracts()
        env = c.FederationTaskEnvelope(
            task_id="t1", source_system="s", source_agent="a",
            target_system="t", target_agent="b", goal="g",
        )
        assert c.is_federation_task_envelope(env) is True

    def test_is_federation_task_envelope_duck_typed_true(self):
        c = _get_contracts()
        DuckEnvelope = type(
            "FederationTaskEnvelope",
            (),
            {
                "task_id": "t1",
                "source_system": "s",
                "source_agent": "a",
                "target_system": "t",
                "target_agent": "b",
                "goal": "g",
            },
        )
        assert c.is_federation_task_envelope(DuckEnvelope()) is True

    def test_is_federation_task_result_true(self):
        c = _get_contracts()
        r = c.FederationTaskResult(
            task_id="t1", source_system="s", source_agent="a",
            target_system="t", target_agent="b", status="success", summary="özet",
        )
        assert c.is_federation_task_result(r) is True

    def test_is_federation_task_result_duck_typed_true(self):
        c = _get_contracts()
        DuckResult = type(
            "FederationTaskResult",
            (),
            {
                "task_id": "t1",
                "source_system": "s",
                "source_agent": "a",
                "target_system": "t",
                "target_agent": "b",
                "status": "success",
                "summary": "özet",
            },
        )
        assert c.is_federation_task_result(DuckResult()) is True

    def test_is_action_feedback_true(self):
        c = _get_contracts()
        fb = c.ActionFeedback(
            feedback_id="fb1", source_system="s", source_agent="a",
            action_name="act", status="ok", summary="tamam",
        )
        assert c.is_action_feedback(fb) is True

    def test_is_action_feedback_duck_typed_true(self):
        c = _get_contracts()
        DuckFeedback = type(
            "ActionFeedback",
            (),
            {
                "feedback_id": "fb1",
                "source_system": "s",
                "source_agent": "a",
                "action_name": "act",
                "status": "ok",
                "summary": "tamam",
            },
        )
        assert c.is_action_feedback(DuckFeedback()) is True

    def test_is_broker_task_envelope_true(self):
        c = _get_contracts()
        env = c.BrokerTaskEnvelope(task_id="t1", sender="s", receiver="r", goal="g")
        assert c.is_broker_task_envelope(env) is True

    def test_is_broker_task_envelope_duck_typed_true(self):
        c = _get_contracts()
        DuckBrokerEnv = type(
            "BrokerTaskEnvelope",
            (),
            {
                "task_id": "t1",
                "sender": "s",
                "receiver": "r",
                "goal": "g",
                "broker": "rabbitmq",
                "exchange": "sidar.swarm.tasks",
                "routing_key": "sidar.swarm.r.mixed",
            },
        )
        assert c.is_broker_task_envelope(DuckBrokerEnv()) is True

    def test_is_broker_task_result_true(self):
        c = _get_contracts()
        r = c.BrokerTaskResult(task_id="t1", sender="s", receiver="r", status="success", summary="özet")
        assert c.is_broker_task_result(r) is True

    def test_is_broker_task_result_false_for_none(self):
        c = _get_contracts()
        assert c.is_broker_task_result(None) is False
