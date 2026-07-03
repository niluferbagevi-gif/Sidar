"""Pure formatting helpers for GraphRAG query and impact outputs."""

from __future__ import annotations

from typing import Any


def _string_list(value: Any) -> list[str]:
    """Return a deterministic string list from supported neighbor containers."""
    values = value if isinstance(value, list | tuple | set) else []
    return [str(item) for item in values]


def format_graph_search_results(
    query: str,
    *,
    code_results: list[dict[str, Any]],
    entity_results: list[dict[str, Any]],
    graph_nodes: dict[str, dict[str, Any]],
) -> str:
    """Format combined code-graph and entity-graph search results."""
    lines = [f"[GraphRAG: {query}]", ""]
    if entity_results:
        lines.append("İlişkisel bellek entity sonuçları:")
        for item in entity_results:
            node = item["node"]
            lines.append(
                f"- {node.get('label')}: {node.get('name')} "
                f"(score={item['score']}, id={node.get('id')})"
            )
            for relation in item.get("relations", [])[:4]:
                source_node = graph_nodes.get(str(relation.get("source")), {})
                target_node = graph_nodes.get(str(relation.get("target")), {})
                lines.append(
                    "  "
                    f"{source_node.get('name', relation.get('source'))} "
                    f"-[{relation.get('relation')}]-> "
                    f"{target_node.get('name', relation.get('target'))}"
                )
        lines.append("")

    if code_results:
        lines.append("Kod bağımlılık grafı sonuçları:")
    for item in code_results:
        lines.append(f"- {item['id']} (score={item['score']})")
        neighbors = _string_list(item.get("neighbors") or [])
        if neighbors:
            lines.append(f"  Komşular: {', '.join(neighbors)}")
        reverse_neighbors = _string_list(item.get("reverse_neighbors") or [])
        if reverse_neighbors:
            lines.append(f"  Ters Komşular: {', '.join(reverse_neighbors)}")
    return "\n".join(lines)


def format_graph_impact_analysis(analysis: dict[str, Any]) -> str:
    """Format structured graph impact analysis using the legacy text shape."""
    lines = [f"[GraphRAG Impact] {analysis['target']}", ""]
    impacted_endpoints = analysis.get("impacted_endpoints") or []
    impacted_endpoint_handlers = analysis.get("impacted_endpoint_handlers") or []
    caller_files = analysis.get("caller_files") or []
    direct_dependents = analysis.get("direct_dependents") or []
    dependencies = analysis.get("dependencies") or []
    review_targets = analysis.get("review_targets") or []
    dependency_paths = analysis.get("dependency_paths") or []

    lines.append(f"- Düğüm tipi: {analysis.get('node_type', 'file')}")
    lines.append(f"- Risk seviyesi: {analysis.get('risk_level', 'low')}")
    if direct_dependents:
        lines.append(f"- Doğrudan bağımlılar: {', '.join(direct_dependents)}")
    if dependencies:
        lines.append(f"- Aşağı akış bağımlılıklar: {', '.join(dependencies)}")
    if impacted_endpoints:
        lines.append(f"- Etkilenen endpoint'ler: {', '.join(impacted_endpoints)}")
    if impacted_endpoint_handlers:
        lines.append(f"- Etkilenen endpoint handler dosyaları: {', '.join(impacted_endpoint_handlers)}")
    if caller_files:
        lines.append(f"- Çağıran dosyalar: {', '.join(caller_files)}")
    if review_targets:
        lines.append(f"- Reviewer için önerilen hedefler: {', '.join(review_targets)}")
    if dependency_paths:
        lines.append("- Örnek etki zincirleri:")
        for idx, path in enumerate(dependency_paths, start=1):
            lines.append(f"  {idx}. {' -> '.join(path)}")
    return "\n".join(lines)
