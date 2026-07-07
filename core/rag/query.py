"""Query planning value objects for the RAG facade."""

from __future__ import annotations

import builtins
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .graph import KnowledgeGraphEdge, KnowledgeGraphNode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphRAGSearchPlan:
    query: str
    vector_backend: str
    vector_candidates: builtins.list[str] = field(default_factory=list)
    graph_nodes: builtins.list[KnowledgeGraphNode] = field(default_factory=list)
    graph_edges: builtins.list[KnowledgeGraphEdge] = field(default_factory=list)
    broker_topics: builtins.list[str] = field(default_factory=list)
    cypher_hint: str = ""


QueryExpansionFn = Callable[[str], str | Iterable[str]]


def build_query_candidates(
    query: str,
    *,
    expander: QueryExpansionFn | None = None,
    max_candidates: int = 3,
) -> builtins.list[str]:
    """Build expanded query candidates with original-query fail-closed fallback.

    The original query is always included as the last candidate, so a failed or low-quality
    expansion path can fall back deterministically without dropping the user's exact wording.
    """
    original = str(query or "").strip()
    if not original:
        return []
    candidate_limit = max(1, max_candidates)
    expansion_limit = max(0, candidate_limit - 1)
    candidates: builtins.list[str] = []
    if expander is not None and expansion_limit > 0:
        try:
            expanded = expander(original)
            raw_candidates: Iterable[Any]
            if isinstance(expanded, str):
                raw_candidates = [expanded]
            else:
                raw_candidates = expanded
            for candidate in raw_candidates:
                normalized = str(candidate or "").strip()
                if normalized and normalized != original and normalized not in candidates:
                    candidates.append(normalized)
                    if len(candidates) >= expansion_limit:
                        break
        except Exception as exc:
            logger.warning("RAG query expansion failed; falling back to original query: %s", exc)
    candidates.append(original)
    return candidates[:candidate_limit]


__all__ = ["GraphRAGSearchPlan", "QueryExpansionFn", "build_query_candidates"]
