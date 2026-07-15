"""Feature-flagged LLM-assisted GraphRAG extraction helpers."""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from typing import Any

from core.rag.graph import ExtractedKnowledgeEntity, ExtractedKnowledgeRelation

CleanEntityValue = Callable[[Any], str]
EntityIdFactory = Callable[[str, str], str]
LLMEntityExtractor = Callable[[str, str, list[str], str, "LLMEntityExtractionSettings"], Any]
LLMClientFactory = Callable[[], Any]

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


def build_llm_entity_extraction_prompt(
    title: str,
    content: str,
    *,
    tags: list[str] | None = None,
    source: str = "",
    settings: LLMEntityExtractionSettings | None = None,
) -> str:
    """Build the constrained JSON prompt for LLM-assisted GraphRAG extraction."""
    active_settings = settings or LLMEntityExtractionSettings()
    tag_text = ", ".join(tags or [])
    return (
        "Extract GraphRAG marketing entities as strict JSON only. "
        f"schema_version must be {active_settings.schema_version!r}. "
        f"Return at most {max(1, active_settings.max_entities)} entities. "
        f"Allowed labels: {sorted(ALLOWED_ENTITY_LABELS)}. "
        f"Allowed relation types: {sorted(ALLOWED_RELATION_TYPES)}. "
        "Use shape {\"schema_version\": str, \"entities\": "
        "[{\"label\": str, \"name\": str, \"properties\": object}], "
        "\"relations\": [{\"source_label\": str, \"source_name\": str, "
        "\"target_label\": str, \"target_name\": str, \"type\": str}]}.\n"
        f"Title: {title}\nSource: {source}\nTags: {tag_text}\nContent:\n{content}"
    )


def coerce_llm_entity_payload(value: Any) -> dict[str, Any] | None:
    """Coerce an LLM JSON response into a payload mapping, if possible."""
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


def _await_sync(awaitable: Coroutine[Any, Any, Any]) -> Any:
    """Resolve an awaitable from sync RAG ingestion code, including active event loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result: dict[str, Any] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            result["error"] = exc

    thread = threading.Thread(target=_runner, name="rag-llm-entity-extraction", daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def extract_llm_entity_payload(
    title: str,
    content: str,
    *,
    tags: list[str] | None = None,
    source: str = "",
    settings: LLMEntityExtractionSettings,
    extractor: LLMEntityExtractor | None = None,
    llm_client_factory: LLMClientFactory | None = None,
    model: str | None = None,
) -> dict[str, Any] | None:
    """Run the feature-flagged LLM extractor and return only schema-boundary payloads."""
    if not settings.enabled:
        return None

    tag_values = list(tags or [])
    if extractor is not None:
        return coerce_llm_entity_payload(extractor(title, content, tag_values, source, settings))
    if llm_client_factory is None:
        return None

    prompt = build_llm_entity_extraction_prompt(
        title, content, tags=tag_values, source=source, settings=settings
    )
    client = llm_client_factory()
    response = _await_sync(
        client.chat(
            [{"role": "user", "content": prompt}],
            model=model,
            temperature=0.0,
            stream=False,
            json_mode=True,
        )
    )
    return coerce_llm_entity_payload(response)


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
    "build_llm_entity_extraction_prompt",
    "coerce_llm_entity_payload",
    "extract_llm_entity_payload",
    "normalize_llm_entity_payload",
]
