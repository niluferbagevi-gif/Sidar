"""Schema validation helpers for future LLM-assisted GraphRAG extraction."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from core.rag.graph import ExtractedKnowledgeEntity, ExtractedKnowledgeRelation

CleanEntityValue = Callable[[Any], str]
EntityIdFactory = Callable[[str, str], str]

LLM_ENTITY_SCHEMA_VERSION = "graphrag.entity.v1"
ALLOWED_ENTITY_LABELS = frozenset({"Campaign", "Brand", "Audience", "Tone", "Channel", "Source"})
ALLOWED_RELATION_TYPES = frozenset(
    {
        "TARGETS_AUDIENCE",
        "USES_TONE",
        "PROMOTES_BRAND",
        "RUNS_ON",
        "HAS_BRAND_VOICE",
        "CITES_SOURCE",
    }
)


@dataclass(frozen=True)
class LLMEntityExtractionSettings:
    """Feature-flag-ready settings for the 2026-Q3 LLM extraction expansion."""

    enabled: bool = False
    schema_version: str = LLM_ENTITY_SCHEMA_VERSION
    max_entities: int = 24
    review_target: str = "2026-Q3"


def _safe_properties(value: Any) -> dict[str, Any]:
    """Return scalar-only properties from an untrusted LLM entity payload."""
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, Any] = {}
    for key, raw in value.items():
        if isinstance(raw, str | int | float | bool) or raw is None:
            safe[str(key)] = raw
    return safe


def _relation_endpoint_id(
    payload: Mapping[str, Any],
    *,
    prefix: str,
    clean_entity_value: CleanEntityValue,
    entity_id: EntityIdFactory,
) -> str:
    """Resolve a relation endpoint from either an id or label/name pair."""
    raw_id = payload.get(f"{prefix}_id")
    if isinstance(raw_id, str) and raw_id.strip():
        return raw_id.strip()

    raw_label = payload.get(f"{prefix}_label")
    raw_name = payload.get(f"{prefix}_name")
    label = clean_entity_value(raw_label)
    name = clean_entity_value(raw_name)
    if label in ALLOWED_ENTITY_LABELS and name:
        return entity_id(label, name)
    return ""


def normalize_llm_entity_payload(
    payload: Mapping[str, Any] | None,
    *,
    clean_entity_value: CleanEntityValue,
    entity_id: EntityIdFactory,
    entity_max_per_doc: int = 24,
) -> tuple[list[ExtractedKnowledgeEntity], list[ExtractedKnowledgeRelation]]:
    """Validate a candidate LLM GraphRAG entity payload against the stable schema."""
    if not isinstance(payload, Mapping):
        return [], []
    if payload.get("schema_version") != LLM_ENTITY_SCHEMA_VERSION:
        return [], []

    by_id: dict[str, ExtractedKnowledgeEntity] = {}
    raw_entities = payload.get("entities", [])
    if isinstance(raw_entities, list):
        for item in raw_entities[: max(1, entity_max_per_doc)]:
            if not isinstance(item, Mapping):
                continue
            label = clean_entity_value(item.get("label"))
            name = clean_entity_value(item.get("name"))
            if label not in ALLOWED_ENTITY_LABELS or not name:
                continue
            current_id = entity_id(label, name)
            properties = _safe_properties(item.get("properties"))
            properties["extraction"] = "llm"
            by_id[current_id] = ExtractedKnowledgeEntity(current_id, label, name, properties)

    relations: list[ExtractedKnowledgeRelation] = []
    raw_relations = payload.get("relations", [])
    if isinstance(raw_relations, list):
        for item in raw_relations:
            if not isinstance(item, Mapping):
                continue
            relation_type = clean_entity_value(item.get("type")).upper()
            if relation_type not in ALLOWED_RELATION_TYPES:
                continue
            source_id = _relation_endpoint_id(
                item,
                prefix="source",
                clean_entity_value=clean_entity_value,
                entity_id=entity_id,
            )
            target_id = _relation_endpoint_id(
                item,
                prefix="target",
                clean_entity_value=clean_entity_value,
                entity_id=entity_id,
            )
            if source_id in by_id and target_id in by_id:
                relations.append(ExtractedKnowledgeRelation(source_id, target_id, relation_type))

    return list(by_id.values()), relations


__all__ = [
    "ALLOWED_ENTITY_LABELS",
    "ALLOWED_RELATION_TYPES",
    "LLM_ENTITY_SCHEMA_VERSION",
    "LLMEntityExtractionSettings",
    "normalize_llm_entity_payload",
]
