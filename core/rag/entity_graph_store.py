"""Entity graph persistence and mutation helpers for DocumentStore."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("core.rag")
_ENTITY_NODE_PREFIXES = ("campaign:", "brand:", "audience:", "tone:", "channel:", "source:")


def load_entity_graph(graph_file: Path) -> dict[str, Any]:
    """Load persisted entity graph data with normalized nodes/edges containers."""

    if graph_file.exists():
        try:
            loaded = json.loads(graph_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return {
                    "nodes": dict(loaded.get("nodes") or {}),
                    "edges": list(loaded.get("edges") or []),
                }
        except Exception as exc:
            logger.warning("RAG entity graph okunamadı: %s", exc)
    return {"nodes": {}, "edges": []}


def ensure_entity_graph(owner: Any) -> dict[str, Any]:
    """Return owner graph state with dict/list containers guaranteed."""

    graph = getattr(owner, "_entity_graph", None)
    if not isinstance(graph, dict):
        graph = {"nodes": {}, "edges": []}
        owner._entity_graph = graph
    if not isinstance(graph.get("nodes"), dict):
        graph["nodes"] = {}
    if not isinstance(graph.get("edges"), list):
        graph["edges"] = []
    return graph


def save_entity_graph(owner: Any, graph_file: Path) -> None:
    """Persist the owner's normalized entity graph to disk."""

    graph_file.write_text(
        json.dumps(ensure_entity_graph(owner), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def upsert_document_entities(
    owner: Any,
    doc_id: str,
    title: str,
    content: str,
    *,
    source: str = "",
    tags: list[str] | None = None,
    session_id: str = "global",
) -> None:
    """Insert/update document, entity and relation nodes for a RAG document."""

    if not getattr(owner, "_entity_extraction_enabled", True):
        return
    graph = owner._ensure_entity_graph()
    nodes: dict[str, dict[str, Any]] = graph["nodes"]
    edges: list[dict[str, Any]] = graph["edges"]
    doc_node_id = f"doc:{doc_id}"

    edges[:] = [
        edge for edge in edges if edge.get("source") != doc_node_id and edge.get("doc_id") != doc_id
    ]
    nodes[doc_node_id] = {
        "id": doc_node_id,
        "label": "Document",
        "name": title or doc_id,
        "properties": {"doc_id": doc_id, "session_id": session_id, "source": source},
    }

    entities, relations = owner.extract_document_entities(title, content, tags=tags, source=source)
    entity_ids = {entity.id for entity in entities}
    for entity in entities:
        properties = dict(entity.properties)
        properties.update({"session_id": session_id, "last_doc_id": doc_id})
        nodes[entity.id] = {
            "id": entity.id,
            "label": entity.label,
            "name": entity.name,
            "properties": properties,
        }
        edges.append(
            {
                "source": doc_node_id,
                "target": entity.id,
                "relation": "MENTIONS",
                "doc_id": doc_id,
                "session_id": session_id,
            }
        )

    for relation in relations:
        if relation.source not in entity_ids or relation.target not in entity_ids:
            continue
        edges.append(
            {
                "source": relation.source,
                "target": relation.target,
                "relation": relation.relation,
                "doc_id": doc_id,
                "session_id": session_id,
                "properties": dict(relation.properties),
            }
        )

    owner._save_entity_graph()


def delete_document_entities(owner: Any, doc_id: str) -> None:
    """Delete document-scoped entity graph edges and orphaned marketing nodes."""

    graph = owner._ensure_entity_graph()
    nodes: dict[str, dict[str, Any]] = graph["nodes"]
    doc_node_id = f"doc:{doc_id}"
    nodes.pop(doc_node_id, None)
    graph["edges"] = [edge for edge in graph["edges"] if edge.get("doc_id") != doc_id]
    referenced = {
        str(edge.get("source"))
        for edge in graph["edges"]
        if str(edge.get("source", "")).startswith(_ENTITY_NODE_PREFIXES)
    } | {
        str(edge.get("target"))
        for edge in graph["edges"]
        if str(edge.get("target", "")).startswith(_ENTITY_NODE_PREFIXES)
    }
    for node_id in list(nodes):
        if node_id.startswith(_ENTITY_NODE_PREFIXES) and node_id not in referenced:
            nodes.pop(node_id, None)
    owner._save_entity_graph()


def search_entity_graph(
    graph: dict[str, Any], query: str, *, session_id: str = "global", top_k: int = 5
) -> list[dict[str, Any]]:
    """Search entity graph nodes and include nearby relations for matching nodes."""

    tokens = [token for token in re.split(r"[\s/_.:-]+", query.lower()) if token]
    if not tokens:
        return []
    scored: list[tuple[str, int]] = []
    nodes: dict[str, dict[str, Any]] = graph["nodes"]
    for node_id, node in nodes.items():
        raw_properties = node.get("properties")
        properties: dict[str, Any] = raw_properties if isinstance(raw_properties, dict) else {}
        node_session = str(properties.get("session_id", "global") or "global")
        if session_id != "global" and node_session not in {session_id, "global"}:
            continue
        haystack = " ".join(
            [str(node_id), str(node.get("label", "")), str(node.get("name", ""))]
            + [str(value) for value in properties.values()]
        ).lower()
        score = sum(haystack.count(token) for token in tokens)
        if score > 0:
            scored.append((node_id, score))
    scored.sort(key=lambda item: item[1], reverse=True)

    results: list[dict[str, Any]] = []
    for node_id, score in scored[:top_k]:
        relations = [
            edge
            for edge in graph["edges"]
            if edge.get("source") == node_id or edge.get("target") == node_id
        ][:8]
        results.append({"node": nodes[node_id], "score": score, "relations": relations})
    return results
