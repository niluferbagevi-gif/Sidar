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