"""Knowledge graph projection builders for RAG document and graph state."""

from __future__ import annotations

from typing import Any

from core.rag.graph import KnowledgeGraphEdge, KnowledgeGraphNode

DEFAULT_CYPHER_HINT = (
    "UNWIND $nodes AS node MERGE (n:KG {id: node.id}) "
    "SET n += node.properties, n.label = node.label "
    "WITH n UNWIND $edges AS edge MATCH (s:KG {id: edge.source}), (t:KG {id: edge.target}) "
    "MERGE (s)-[r:RELATED {relation: edge.relation}]->(t) SET r += edge.properties"
)


def clamp_projection_limit(limit: int | None, *, default: int = 100, maximum: int = 1000) -> int:
    """Clamp projection item count to the legacy safe range."""
    return max(1, min(int(limit or default), maximum))


def resolve_vector_backend(*, pgvector_available: bool, vector_backend: str) -> str:
    """Return the projection-facing vector backend label."""
    return "pgvector" if pgvector_available else vector_backend


def append_document_projection(
    *,
    nodes: list[KnowledgeGraphNode],
    edges: list[KnowledgeGraphEdge],
    index: dict[str, dict[str, Any]],
    session_id: str,
    vector_backend: str,
    max_items: int,
) -> None:
    """Append document/session/source nodes and edges to a projection."""
    for doc_id, meta in list(index.items())[:max_items]:
        doc_session = str(meta.get("session_id", "global") or "global")
        if session_id != "global" and doc_session != session_id:
            continue
        title = str(meta.get("title", "") or "")
        source = str(meta.get("source", "") or "")
        nodes.append(
            KnowledgeGraphNode(
                id=f"doc:{doc_id}",
                label="Document",
                properties={
                    "doc_id": doc_id,
                    "title": title,
                    "source": source,
                    "session_id": doc_session,
                    "vector_backend": vector_backend,
                },
            )
        )
        nodes.append(
            KnowledgeGraphNode(
                id=f"session:{doc_session}",
                label="Session",
                properties={"session_id": doc_session},
            )
        )
        edges.append(
            KnowledgeGraphEdge(
                source=f"session:{doc_session}",
                target=f"doc:{doc_id}",
                relation="CONTAINS_DOCUMENT",
            )
        )
        if source:
            nodes.append(
                KnowledgeGraphNode(
                    id=f"source:{source}",
                    label="Source",
                    properties={"source": source},
                )
            )
            edges.append(
                KnowledgeGraphEdge(
                    source=f"doc:{doc_id}",
                    target=f"source:{source}",
                    relation="DERIVED_FROM",
                )
            )


def append_entity_projection(
    *,
    nodes: list[KnowledgeGraphNode],
    edges: list[KnowledgeGraphEdge],
    entity_graph: dict[str, Any],
    session_id: str,
    max_items: int,
) -> None:
    """Append extracted entity graph nodes and edges to a projection."""
    for node_id, node in list(entity_graph["nodes"].items())[:max_items]:
        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        node_session = str(properties.get("session_id", "global") or "global")
        if session_id != "global" and node_session not in {session_id, "global"}:
            continue
        nodes.append(
            KnowledgeGraphNode(
                id=f"entity:{node_id}",
                label=str(node.get("label") or "Entity"),
                properties={
                    **properties,
                    "entity_id": node_id,
                    "name": str(node.get("name") or ""),
                },
            )
        )

    entity_edge_count = 0
    for edge in entity_graph["edges"]:
        if entity_edge_count >= max_items:
            break
        edge_session = str(edge.get("session_id", "global") or "global")
        if session_id != "global" and edge_session not in {session_id, "global"}:
            continue
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        if not source_id or not target_id:
            continue
        entity_edge_count += 1
        edges.append(
            KnowledgeGraphEdge(
                source=f"entity:{source_id}",
                target=f"entity:{target_id}",
                relation=str(edge.get("relation") or "RELATED_TO"),
                properties=dict(edge.get("properties") or {}),
            )
        )


def append_code_graph_projection(
    *,
    nodes: list[KnowledgeGraphNode],
    edges: list[KnowledgeGraphEdge],
    graph_index: Any,
    max_items: int,
) -> None:
    """Append code dependency graph nodes and edges to a projection."""
    for node_id, attrs in list(graph_index.nodes.items())[:max_items]:
        nodes.append(
            KnowledgeGraphNode(
                id=f"code:{node_id}",
                label="CodeNode",
                properties=dict(attrs),
            )
        )
    edge_count = 0
    for source_id, targets in graph_index.edges.items():
        for target_id in sorted(targets):
            edge_count += 1
            if edge_count > max_items:
                break
            edge_kinds = sorted(graph_index.edge_kinds.get((source_id, target_id), {"RELATED_TO"}))
            edges.append(
                KnowledgeGraphEdge(
                    source=f"code:{source_id}",
                    target=f"code:{target_id}",
                    relation=edge_kinds[0],
                    properties={"edge_kinds": edge_kinds},
                )
            )
        if edge_count > max_items:
            break


def dedupe_projection_nodes(nodes: list[KnowledgeGraphNode]) -> list[KnowledgeGraphNode]:
    """Deduplicate nodes by the legacy id/label key while preserving final values."""
    return list({(node.id, node.label): node for node in nodes}.values())


def build_knowledge_graph_projection_payload(
    *,
    index: dict[str, dict[str, Any]],
    entity_graph: dict[str, Any],
    graph_index: Any | None,
    session_id: str = "global",
    include_code_graph: bool = True,
    graph_rag_enabled: bool = True,
    pgvector_available: bool = False,
    vector_backend: str = "bm25",
    limit: int = 100,
) -> dict[str, Any]:
    """Build a portable knowledge graph projection payload."""
    max_items = clamp_projection_limit(limit)
    resolved_backend = resolve_vector_backend(
        pgvector_available=pgvector_available,
        vector_backend=vector_backend,
    )
    nodes: list[KnowledgeGraphNode] = []
    edges: list[KnowledgeGraphEdge] = []
    append_document_projection(
        nodes=nodes,
        edges=edges,
        index=index,
        session_id=session_id,
        vector_backend=resolved_backend,
        max_items=max_items,
    )
    append_entity_projection(
        nodes=nodes,
        edges=edges,
        entity_graph=entity_graph,
        session_id=session_id,
        max_items=max_items,
    )
    if include_code_graph and graph_rag_enabled and graph_index is not None:
        append_code_graph_projection(
            nodes=nodes, edges=edges, graph_index=graph_index, max_items=max_items
        )

    return {
        "nodes": dedupe_projection_nodes(nodes),
        "edges": edges,
        "cypher_hint": DEFAULT_CYPHER_HINT,
        "vector_backend": resolved_backend,
    }
