"""Query planning value objects for the RAG facade."""

from __future__ import annotations

import builtins
from dataclasses import dataclass, field

from .graph import KnowledgeGraphEdge, KnowledgeGraphNode


@dataclass(frozen=True)
class GraphRAGSearchPlan:
    query: str
    vector_backend: str
    vector_candidates: builtins.list[str] = field(default_factory=list)
    graph_nodes: builtins.list[KnowledgeGraphNode] = field(default_factory=list)
    graph_edges: builtins.list[KnowledgeGraphEdge] = field(default_factory=list)
    broker_topics: builtins.list[str] = field(default_factory=list)
    cypher_hint: str = ""


__all__ = ["GraphRAGSearchPlan"]
