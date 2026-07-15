"""Tests for the LLM-assisted GraphRAG entity extraction schema seam."""

from __future__ import annotations

from core.rag.entity_extraction import extract_document_entities
from core.rag.entity_helpers import clean_entity_value, entity_id
from core.rag.llm_entity_extraction import LLM_ENTITY_SCHEMA_VERSION, normalize_llm_entity_payload


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
