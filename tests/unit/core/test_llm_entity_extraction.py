"""Tests for the LLM-assisted GraphRAG entity extraction schema seam."""

from __future__ import annotations

from typing import Any, cast

import pytest

from core.rag.entity_extraction import extract_document_entities
from core.rag.entity_helpers import clean_entity_value, entity_id
from core.rag.llm_entity_extraction import (
    LLM_ENTITY_SCHEMA_VERSION,
    LLMEntityExtractionSettings,
    coerce_llm_entity_payload,
    extract_llm_entity_payload,
    normalize_llm_entity_payload,
)


def test_normalize_llm_entity_payload_validates_schema_and_relation_endpoints() -> None:
    """LLM payloads are accepted only through the stable schema boundary."""
    entities, relations = normalize_llm_entity_payload(
        {
            "schema_version": LLM_ENTITY_SCHEMA_VERSION,
            "entities": [
                {"label": "Campaign", "name": "Launch", "properties": {"confidence": 0.91}},
                {"label": "Audience", "name": "Developers", "properties": {"nested": []}},
                {"label": "Unknown", "name": "Ignored"},
            ],
            "relations": [
                {
                    "source_label": "Campaign",
                    "source_name": "Launch",
                    "target_label": "Audience",
                    "target_name": "Developers",
                    "type": "TARGETS_AUDIENCE",
                },
                {
                    "source_label": "Campaign",
                    "source_name": "Launch",
                    "target_label": "Audience",
                    "target_name": "Developers",
                    "type": "UNSAFE_RELATION",
                },
            ],
        },
        clean_entity_value=clean_entity_value,
        entity_id=entity_id,
    )

    assert [entity.label for entity in entities] == ["Campaign", "Audience"]
    assert entities[0].properties["extraction"] == "llm"
    assert "nested" not in entities[1].properties
    assert [(relation.source, relation.target, relation.relation) for relation in relations] == [
        (entity_id("Campaign", "Launch"), entity_id("Audience", "Developers"), "TARGETS_AUDIENCE")
    ]


def test_extract_document_entities_can_merge_validated_llm_payload() -> None:
    """Deterministic extraction can be augmented without trusting raw LLM output."""
    entities, relations = extract_document_entities(
        "Campaign brief",
        "Brand: Sidar\nTone: Güvenilir",
        llm_payload={
            "schema_version": LLM_ENTITY_SCHEMA_VERSION,
            "entities": [
                {"label": "Campaign", "name": "Q3 Launch"},
                {"label": "Channel", "name": "Email"},
            ],
            "relations": [
                {
                    "source_label": "Campaign",
                    "source_name": "Q3 Launch",
                    "target_label": "Channel",
                    "target_name": "Email",
                    "type": "RUNS_ON",
                }
            ],
        },
        clean_entity_value=clean_entity_value,
        entity_id=entity_id,
    )

    entity_names = {(entity.label, entity.name) for entity in entities}
    assert ("Campaign", "Q3 Launch") in entity_names
    assert ("Channel", "Email") in entity_names
    assert any(relation.relation == "RUNS_ON" for relation in relations)


def test_normalize_llm_entity_payload_rejects_non_mapping_and_wrong_schema() -> None:
    """Invalid envelopes must not leak untrusted LLM output into GraphRAG memory."""
    for payload in (None, [], {"schema_version": "legacy"}):
        assert normalize_llm_entity_payload(
            payload,  # type: ignore[arg-type]
            clean_entity_value=clean_entity_value,
            entity_id=entity_id,
        ) == ([], [])


def test_normalize_llm_entity_payload_limits_entities_and_ignores_malformed_items() -> None:
    """Entity validation enforces max count, allowed labels, names and scalar properties."""
    entities, relations = normalize_llm_entity_payload(
        {
            "schema_version": LLM_ENTITY_SCHEMA_VERSION,
            "entities": [
                "not-a-mapping",
                {"label": "Campaign", "name": "Launch", "properties": {"ok": True}},
                {"label": "Audience", "name": "Developers"},
                {"label": "Brand", "name": "Sidar"},
            ],
            "relations": "not-a-list",
        },
        clean_entity_value=clean_entity_value,
        entity_id=entity_id,
        entity_max_per_doc=2,
    )

    assert [(entity.label, entity.name) for entity in entities] == [("Campaign", "Launch")]
    assert entities[0].properties == {"ok": True, "extraction": "llm"}
    assert relations == []


def test_normalize_llm_entity_payload_ignores_non_list_entities() -> None:
    """A valid envelope with non-list entities remains an empty, safe extraction."""
    entities, relations = normalize_llm_entity_payload(
        {
            "schema_version": LLM_ENTITY_SCHEMA_VERSION,
            "entities": {"label": "Campaign", "name": "Launch"},
            "relations": [],
        },
        clean_entity_value=clean_entity_value,
        entity_id=entity_id,
    )

    assert entities == []
    assert relations == []


def test_normalize_llm_entity_payload_accepts_relation_raw_ids_and_filters_bad_edges() -> None:
    """Relations can use ids directly, but only when both endpoints are validated entities."""
    campaign_id = entity_id("Campaign", "Launch")
    audience_id = entity_id("Audience", "Developers")

    entities, relations = normalize_llm_entity_payload(
        {
            "schema_version": LLM_ENTITY_SCHEMA_VERSION,
            "entities": [
                {
                    "label": "Campaign",
                    "name": "Launch",
                    "properties": {
                        "confidence": 0.95,
                        "enabled": True,
                        "nullable": None,
                        "nested": {"unsafe": "ignored"},
                    },
                },
                {"label": "Audience", "name": "Developers"},
            ],
            "relations": [
                "not-a-mapping",
                {"type": "RUNS_ON", "source_label": "Campaign", "target_name": "Developers"},
                {"type": "CITES_SOURCE", "source_id": campaign_id, "target_id": "source:missing"},
                {
                    "type": "targets_audience",
                    "source_id": f" {campaign_id} ",
                    "target_id": audience_id,
                },
            ],
        },
        clean_entity_value=clean_entity_value,
        entity_id=entity_id,
    )

    assert entities[0].properties == {
        "confidence": 0.95,
        "enabled": True,
        "nullable": None,
        "extraction": "llm",
    }
    assert [(relation.source, relation.target, relation.relation) for relation in relations] == [
        (campaign_id, audience_id, "TARGETS_AUDIENCE")
    ]


def test_extract_llm_entity_payload_respects_feature_flag_and_coerces_json() -> None:
    calls: list[str] = []

    def fake_extractor(title, content, tags, source, settings):
        calls.append(title)
        return """```json
        {"schema_version":"graphrag.entity.v1","entities":[{"label":"Campaign","name":"Launch"}],"relations":[]}
        ```"""

    disabled = LLMEntityExtractionSettings(enabled=False)
    assert (
        extract_llm_entity_payload(
            "Launch",
            "content",
            tags=["campaign:Launch"],
            settings=disabled,
            extractor=fake_extractor,
        )
        is None
    )
    assert calls == []

    enabled = LLMEntityExtractionSettings(enabled=True)
    payload = extract_llm_entity_payload(
        "Launch", "content", tags=["campaign:Launch"], settings=enabled, extractor=fake_extractor
    )

    assert payload is not None
    assert payload["schema_version"] == LLM_ENTITY_SCHEMA_VERSION
    assert calls == ["Launch"]


async def test_extract_llm_entity_payload_uses_llm_client_factory_when_enabled() -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        async def chat(self, messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return {
                "schema_version": LLM_ENTITY_SCHEMA_VERSION,
                "entities": [{"label": "Channel", "name": "LinkedIn"}],
                "relations": [],
            }

    payload = extract_llm_entity_payload(
        "Launch",
        "Channel: LinkedIn",
        source="memory://launch",
        settings=LLMEntityExtractionSettings(enabled=True),
        llm_client_factory=FakeClient,
        model="qwen2.5-coder:7b",
    )

    assert payload is not None
    assert payload["entities"][0]["name"] == "LinkedIn"
    assert captured["kwargs"] == {
        "model": "qwen2.5-coder:7b",
        "temperature": 0.0,
        "stream": False,
        "json_mode": True,
    }
    messages = cast(list[dict[str, Any]], captured["messages"])
    assert "Allowed labels" in messages[0]["content"]


def test_coerce_llm_entity_payload_rejects_non_json_and_non_mapping_values() -> None:
    assert coerce_llm_entity_payload(123) is None
    assert coerce_llm_entity_payload("not-json") is None
    assert coerce_llm_entity_payload('["not", "mapping"]') is None
    assert coerce_llm_entity_payload('{"schema_version":"graphrag.entity.v1"}') == {
        "schema_version": LLM_ENTITY_SCHEMA_VERSION
    }


def test_extract_llm_entity_payload_returns_none_without_extractor_or_client() -> None:
    assert (
        extract_llm_entity_payload(
            "Launch", "content", settings=LLMEntityExtractionSettings(enabled=True)
        )
        is None
    )


def test_extract_llm_entity_payload_uses_llm_client_factory_without_running_loop() -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        async def chat(self, messages, **kwargs):
            captured["messages"] = messages
            return '{"schema_version":"graphrag.entity.v1","entities":[],"relations":[]}'

    payload = extract_llm_entity_payload(
        "Launch",
        "content",
        settings=LLMEntityExtractionSettings(enabled=True),
        llm_client_factory=FakeClient,
    )

    assert payload == {"schema_version": LLM_ENTITY_SCHEMA_VERSION, "entities": [], "relations": []}
    messages = cast(list[dict[str, Any]], captured["messages"])
    assert "GraphRAG marketing entities" in messages[0]["content"]


async def test_extract_llm_entity_payload_reraises_threaded_llm_errors() -> None:
    class FailingClient:
        async def chat(self, messages, **kwargs):
            raise RuntimeError("llm unavailable")

    with pytest.raises(RuntimeError, match="llm unavailable"):
        extract_llm_entity_payload(
            "Launch",
            "content",
            settings=LLMEntityExtractionSettings(enabled=True),
            llm_client_factory=FailingClient,
        )
