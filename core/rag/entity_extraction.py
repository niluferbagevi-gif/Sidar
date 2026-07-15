"""Deterministic entity extraction helpers for DocumentStore."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from core.rag.graph import ExtractedKnowledgeEntity, ExtractedKnowledgeRelation
from core.rag.llm_entity_extraction import normalize_llm_entity_payload

CleanEntityValue = Callable[[Any], str]
EntityIdFactory = Callable[[str, str], str]

_KEY_TO_LABEL = {
    "campaign": "Campaign",
    "campaign_name": "Campaign",
    "brand": "Brand",
    "brand_name": "Brand",
    "audience": "Audience",
    "target_audience": "Audience",
    "persona": "Audience",
    "tone": "Tone",
    "brand_voice": "Tone",
    "language": "Tone",
    "channel": "Channel",
    "platform": "Channel",
}

_PATTERNS: dict[str, list[str]] = {
    "Campaign": [r"(?:kampanya(?: adı)?|campaign(?: name)?)\s*[:：=-]\s*([^\n;|]+)"],
    "Brand": [r"(?:marka|brand(?: name)?)\s*[:：=-]\s*([^\n;|]+)"],
    "Audience": [r"(?:hedef kitle|target audience|audience|persona)\s*[:：=-]\s*([^\n;|]+)"],
    "Tone": [r"(?:marka dili|brand voice|tone|üslup|dil)\s*[:：=-]\s*([^\n;|]+)"],
    "Channel": [r"(?:kanal|channel|platform)\s*[:：=-]\s*([^\n;|]+)"],
}

_TAG_LABELS = {
    "campaign": "Campaign",
    "brand": "Brand",
    "audience": "Audience",
    "target_audience": "Audience",
    "tone": "Tone",
    "channel": "Channel",
}


def extract_json_entities(
    payload: Any,
    *,
    prefix: str = "",
    clean_entity_value: CleanEntityValue,
    entity_id: EntityIdFactory,
) -> list[ExtractedKnowledgeEntity]:
    """Extract known marketing entities from JSON-like payloads."""

    entities: list[ExtractedKnowledgeEntity] = []
    if isinstance(payload, dict):
        for raw_key, raw_value in payload.items():
            key = str(raw_key).strip().lower().replace("-", "_").replace(" ", "_")
            label = (
                "Campaign"
                if key == "name" and prefix.endswith("campaign")
                else _KEY_TO_LABEL.get(key, "")
            )
            if label and isinstance(raw_value, str | int | float):
                name = clean_entity_value(raw_value)
                if name:
                    entities.append(
                        ExtractedKnowledgeEntity(
                            id=entity_id(label, name),
                            label=label,
                            name=name,
                            properties={"source_field": key},
                        )
                    )
            if isinstance(raw_value, dict | list):
                child_prefix = f"{prefix}.{key}" if prefix else key
                entities.extend(
                    extract_json_entities(
                        raw_value,
                        prefix=child_prefix,
                        clean_entity_value=clean_entity_value,
                        entity_id=entity_id,
                    )
                )
    elif isinstance(payload, list):
        for item in payload[:20]:
            entities.extend(
                extract_json_entities(
                    item,
                    prefix=prefix,
                    clean_entity_value=clean_entity_value,
                    entity_id=entity_id,
                )
            )
    return entities


def extract_document_entities(
    title: str,
    content: str,
    *,
    tags: list[str] | None = None,
    source: str = "",
    entity_max_per_doc: int = 24,
    clean_entity_value: CleanEntityValue,
    entity_id: EntityIdFactory,
    llm_payload: dict[str, Any] | None = None,
) -> tuple[list[ExtractedKnowledgeEntity], list[ExtractedKnowledgeRelation]]:
    """Extract deterministic marketing/corporate entities and relations from a RAG document."""

    text = f"{title}\n{content}"
    tag_values = tags or []
    by_id: dict[str, ExtractedKnowledgeEntity] = {}

    def add_entity(label: str, raw_name: Any, **properties: Any) -> None:
        name = clean_entity_value(raw_name)
        if not name:
            return
        current_id = entity_id(label, name)
        current = dict(
            by_id.get(current_id, ExtractedKnowledgeEntity(current_id, label, name)).properties
        )
        current.update({key: value for key, value in properties.items() if value not in (None, "")})
        by_id[current_id] = ExtractedKnowledgeEntity(
            id=current_id,
            label=label,
            name=name,
            properties=current,
        )

    for label, label_patterns in _PATTERNS.items():
        for pattern in label_patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                value = clean_entity_value(match.group(1))
                if value:
                    add_entity(label, value, extraction="regex")

    for tag in tag_values:
        if ":" not in str(tag):
            continue
        key, value = [part.strip() for part in str(tag).split(":", 1)]
        tag_label = _TAG_LABELS.get(key.lower())
        if tag_label:
            add_entity(tag_label, value, extraction="tag", tag=tag)

    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            for entity in extract_json_entities(
                json.loads(stripped),
                clean_entity_value=clean_entity_value,
                entity_id=entity_id,
            ):
                add_entity(entity.label, entity.name, **entity.properties, extraction="json")
        except json.JSONDecodeError:
            pass

    if "kampanya" in title.lower() or "campaign" in title.lower():
        add_entity("Campaign", title, extraction="title")
    if source:
        add_entity("Source", source, extraction="source")

    llm_entities, llm_relations = normalize_llm_entity_payload(
        llm_payload,
        clean_entity_value=clean_entity_value,
        entity_id=entity_id,
        entity_max_per_doc=entity_max_per_doc,
    )
    for entity in llm_entities:
        add_entity(entity.label, entity.name, **entity.properties)

    entities = list(by_id.values())[: max(1, entity_max_per_doc)]
    entity_ids = {entity.id for entity in entities}
    ids_by_label: dict[str, list[str]] = {}
    for entity in entities:
        ids_by_label.setdefault(entity.label, []).append(entity.id)

    relations: list[ExtractedKnowledgeRelation] = []
    for campaign_id in ids_by_label.get("Campaign", []):
        for audience_id in ids_by_label.get("Audience", []):
            relations.append(
                ExtractedKnowledgeRelation(campaign_id, audience_id, "TARGETS_AUDIENCE")
            )
        for tone_id in ids_by_label.get("Tone", []):
            relations.append(ExtractedKnowledgeRelation(campaign_id, tone_id, "USES_TONE"))
        for brand_id in ids_by_label.get("Brand", []):
            relations.append(ExtractedKnowledgeRelation(campaign_id, brand_id, "PROMOTES_BRAND"))
        for channel_id in ids_by_label.get("Channel", []):
            relations.append(ExtractedKnowledgeRelation(campaign_id, channel_id, "RUNS_ON"))

    for brand_id in ids_by_label.get("Brand", []):
        for tone_id in ids_by_label.get("Tone", []):
            relations.append(ExtractedKnowledgeRelation(brand_id, tone_id, "HAS_BRAND_VOICE"))

    relations.extend(
        relation
        for relation in llm_relations
        if relation.source in entity_ids and relation.target in entity_ids
    )

    return entities, relations
