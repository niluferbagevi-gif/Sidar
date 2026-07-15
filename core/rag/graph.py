"""Code and knowledge graph primitives used by the RAG facade."""

from __future__ import annotations

import ast as ast
import builtins
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.utils.network_validation import is_local_only_host

logger = logging.getLogger(__name__)

LLM_ENTITY_EXTRACTION_TODO = (
    "TODO(2026-Q3): deterministic GraphRAG entity extraction should be augmented with "
    "an LLM-assisted extractor behind a feature flag and the "
    "core.rag.llm_entity_extraction schema validation boundary."
)


class GraphIndex:
    """Kod tabanı içi modül, endpoint ve çağrı ilişkilerini yönlü grafik olarak tutar."""

    SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}
    ROUTE_DECORATOR_METHODS = {
        "get": "GET",
        "post": "POST",
        "put": "PUT",
        "delete": "DELETE",
        "patch": "PATCH",
        "websocket": "WS",
    }
    HTTP_CALL_METHODS = {"get", "post", "put", "delete", "patch"}

    def __init__(self, root_dir: Path, *, max_files: int = 5000) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.max_files = max_files
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, set[str]] = {}
        self.reverse_edges: dict[str, set[str]] = {}
        self.edge_kinds: dict[tuple[str, str], set[str]] = {}

    @staticmethod
    def _normalize_node_id(root_dir: Path, path: Path) -> str:
        return path.resolve().relative_to(root_dir.resolve()).as_posix()

    def clear(self) -> None:
        self.nodes.clear()
        self.edges.clear()
        self.reverse_edges.clear()
        self.edge_kinds.clear()

    def add_node(self, node_id: str, **attributes: Any) -> None:
        current = self.nodes.setdefault(node_id, {})
        current.update({key: value for key, value in attributes.items() if value is not None})
        self.edges.setdefault(node_id, set())
        self.reverse_edges.setdefault(node_id, set())

    def add_edge(self, source: str, target: str, *, kind: str = "depends_on") -> None:
        self.edges.setdefault(source, set()).add(target)
        self.edges.setdefault(target, set())
        self.reverse_edges.setdefault(source, set())
        self.reverse_edges.setdefault(target, set()).add(source)
        self.edge_kinds.setdefault((source, target), set()).add(kind)

    @classmethod
    def _endpoint_node_id(cls, method: str, path: str) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"endpoint:{method.upper()} {normalized_path}"

    def _iter_source_files(self, root_dir: Path) -> builtins.list[Path]:
        files: builtins.list[Path] = []
        for path in root_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                continue
            if any(
                part in {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
                for part in path.parts
            ):
                continue
            files.append(path)
            if len(files) >= self.max_files:
                break
        return sorted(files)

    @staticmethod
    def _python_import_candidates(
        current_file: Path, module_name: str, level: int, root_dir: Path
    ) -> builtins.list[Path]:
        base_dir = current_file.parent
        if level > 0:
            for _ in range(max(0, level - 1)):
                base_dir = base_dir.parent
        module_parts = [part for part in (module_name or "").split(".") if part]
        base_target = base_dir.joinpath(*module_parts) if module_parts else base_dir
        candidates = [
            base_target.with_suffix(".py"),
            base_target / "__init__.py",
        ]
        return [
            candidate.resolve()
            for candidate in candidates
            if candidate.exists() and candidate.is_relative_to(root_dir)
        ]

    @staticmethod
    def _script_import_candidates(
        current_file: Path, import_ref: str, root_dir: Path
    ) -> builtins.list[Path]:
        import_ref = import_ref.strip()
        if not import_ref.startswith("."):
            return []
        base_target = (current_file.parent / import_ref).resolve()
        candidates = [
            base_target,
            base_target.with_suffix(".js"),
            base_target.with_suffix(".jsx"),
            base_target.with_suffix(".ts"),
            base_target.with_suffix(".tsx"),
            base_target / "index.js",
            base_target / "index.ts",
            base_target / "index.jsx",
            base_target / "index.tsx",
        ]
        return [
            candidate
            for candidate in candidates
            if candidate.exists() and candidate.is_file() and candidate.is_relative_to(root_dir)
        ]

    @staticmethod
    def _extract_str_literal(node: Any) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value.strip()
        legacy_str_cls = ast.__dict__.get("Str")
        if legacy_str_cls is not None and isinstance(node, legacy_str_cls):
            raw_value = getattr(node, "s", None)
            return raw_value.strip() if isinstance(raw_value, str) else None
        return None

    @staticmethod
    def _normalize_endpoint_path(raw_url: str) -> str | None:
        value = (raw_url or "").strip().strip("'\"")
        if not value or "${" in value or "{" in value:
            return None
        if value.startswith(("ws://", "wss://", "http://", "https://")):
            parsed = urllib.parse.urlparse(value)
            hostname = (parsed.hostname or "").lower()
            # B104 bypass yerine: hostname'in gerçekten yerel (loopback ya da
            # unspecified) olduğunu `ipaddress` tabanlı doğrulayıcıyla kontrol et.
            if hostname and not is_local_only_host(hostname):
                return None
            value = parsed.path or "/"
        if not value.startswith("/"):
            return None
        return value or "/"

    def _parse_python_source(
        self, file_path: Path, content: str
    ) -> tuple[builtins.list[Path], builtins.list[dict[str, str]], builtins.list[dict[str, str]]]:
        deps: builtins.list[Path] = []
        endpoint_defs: builtins.list[dict[str, str]] = []
        endpoint_calls: builtins.list[dict[str, str]] = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return deps, endpoint_defs, endpoint_calls

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    deps.extend(
                        self._python_import_candidates(file_path, alias.name, 0, self.root_dir)
                    )
                continue

            if isinstance(node, ast.ImportFrom):
                deps.extend(
                    self._python_import_candidates(
                        file_path, node.module or "", int(node.level or 0), self.root_dir
                    )
                )
                continue

            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call) or not isinstance(
                        decorator.func, ast.Attribute
                    ):
                        continue
                    method = self.ROUTE_DECORATOR_METHODS.get(decorator.func.attr.lower())
                    if not method or not decorator.args:
                        continue
                    route_path = self._extract_str_literal(decorator.args[0])
                    normalized_path = self._normalize_endpoint_path(route_path or "")
                    if not normalized_path:
                        continue
                    endpoint_defs.append(
                        {
                            "endpoint_id": self._endpoint_node_id(method, normalized_path),
                            "method": method,
                            "path": normalized_path,
                            "handler": node.name,
                        }
                    )
                continue

            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue

            call_method = node.func.attr.lower()
            if call_method not in self.HTTP_CALL_METHODS:
                continue

            base_name = ""
            if isinstance(node.func.value, ast.Name):
                base_name = node.func.value.id.lower()
            elif isinstance(node.func.value, ast.Attribute):
                base_name = node.func.value.attr.lower()
            if base_name in {"app", "router"}:
                continue

            if not node.args:
                continue
            target = self._extract_str_literal(node.args[0])
            normalized_path = self._normalize_endpoint_path(target or "")
            if not normalized_path:
                continue
            endpoint_calls.append(
                {
                    "endpoint_id": self._endpoint_node_id(call_method.upper(), normalized_path),
                    "method": call_method.upper(),
                    "path": normalized_path,
                }
            )

        return deps, endpoint_defs, endpoint_calls

    def _extract_script_endpoint_calls(self, content: str) -> builtins.list[dict[str, str]]:
        calls: builtins.list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        fetch_pattern = re.compile(
            r"""fetch\(\s*['"](?P<url>[^'"]+)['"]\s*(?:,\s*\{(?P<opts>.*?)\})?\s*\)""",
            re.DOTALL,
        )
        for match in fetch_pattern.finditer(content):
            path = self._normalize_endpoint_path(match.group("url"))
            if not path:
                continue
            opts = match.group("opts") or ""
            method_match = re.search(r"""method\s*:\s*['"]([A-Za-z]+)['"]""", opts)
            method = (method_match.group(1) if method_match else "GET").upper()
            key = (method, path)
            if key in seen:
                continue
            seen.add(key)
            calls.append(
                {
                    "endpoint_id": self._endpoint_node_id(method, path),
                    "method": method,
                    "path": path,
                }
            )

        for match in re.finditer(r"""new\s+WebSocket\(\s*['"](?P<url>[^'"]+)['"]\s*\)""", content):
            path = self._normalize_endpoint_path(match.group("url"))
            if not path:
                continue
            key = ("WS", path)
            if key in seen:
                continue
            seen.add(key)
            calls.append(
                {"endpoint_id": self._endpoint_node_id("WS", path), "method": "WS", "path": path}
            )

        return calls

    def _extract_dependencies(
        self, file_path: Path, content: str
    ) -> tuple[builtins.list[Path], builtins.list[dict[str, str]], builtins.list[dict[str, str]]]:
        if file_path.suffix.lower() == ".py":
            return self._parse_python_source(file_path, content)

        deps: builtins.list[Path] = []
        import_refs = re.findall(
            r"""(?:from|import)\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)""", content
        )
        for pair in import_refs:
            ref = next((item for item in pair if item), "")
            deps.extend(self._script_import_candidates(file_path, ref, self.root_dir))
        return deps, [], self._extract_script_endpoint_calls(content)

    def rebuild(self, root_dir: Path | None = None) -> dict[str, int]:
        scan_root = Path(root_dir or self.root_dir).resolve()
        self.root_dir = scan_root
        self.clear()
        files = self._iter_source_files(scan_root)
        for file_path in files:
            node_id = self._normalize_node_id(scan_root, file_path)
            self.add_node(node_id, file_type=file_path.suffix.lower(), node_type="file")
        for file_path in files:
            source_id = self._normalize_node_id(scan_root, file_path)
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                logger.debug(
                    "Dosya okunamadı, dependency extraction atlandı (%s): %s", file_path, exc
                )
                continue
            dep_paths, endpoint_defs, endpoint_calls = self._extract_dependencies(
                file_path, content
            )
            for dep_path in dep_paths:
                target_id = self._normalize_node_id(scan_root, dep_path)
                if target_id in self.nodes:
                    self.add_edge(source_id, target_id, kind="imports")
            for endpoint in endpoint_defs:
                endpoint_id = endpoint["endpoint_id"]
                self.add_node(
                    endpoint_id,
                    node_type="endpoint",
                    method=endpoint["method"],
                    path=endpoint["path"],
                    handler=endpoint.get("handler"),
                    file_type="endpoint",
                )
                self.add_edge(endpoint_id, source_id, kind="handled_by")
            for endpoint in endpoint_calls:
                endpoint_id = endpoint["endpoint_id"]
                self.add_node(
                    endpoint_id,
                    node_type="endpoint",
                    method=endpoint["method"],
                    path=endpoint["path"],
                    file_type="endpoint",
                )
                self.add_edge(source_id, endpoint_id, kind="calls_endpoint")
        edge_count = sum(len(targets) for targets in self.edges.values())
        return {"nodes": len(self.nodes), "edges": edge_count}

    def neighbors(self, node_id: str) -> builtins.list[str]:
        return sorted(self.edges.get(node_id, set()))

    def reverse_neighbors(self, node_id: str) -> builtins.list[str]:
        return sorted(self.reverse_edges.get(node_id, set()))

    def resolve_node_id(self, query: str) -> str | None:
        normalized = query.strip()
        if not normalized:
            return None
        if normalized in self.nodes:
            return normalized
        lowered = normalized.lower()
        exact_matches = [node_id for node_id in self.nodes if node_id.lower() == lowered]
        if len(exact_matches) == 1:
            return exact_matches[0]
        suffix_matches = [
            node_id
            for node_id in self.nodes
            if node_id.lower().endswith(lowered) or lowered in node_id.lower()
        ]
        return sorted(suffix_matches, key=len)[0] if len(suffix_matches) == 1 else None

    def explain_dependency_path(self, source: str, target: str) -> builtins.list[str]:
        source_id = self.resolve_node_id(source) or source.strip()
        target_id = self.resolve_node_id(target) or target.strip()
        if source_id not in self.nodes or target_id not in self.nodes:
            return []
        queue: builtins.list[builtins.list[str]] = [[source_id]]
        seen = {source_id}
        while queue:
            path = queue.pop(0)
            last = path[-1]
            if last == target_id:
                return path
            for neighbor in sorted(self.edges.get(last, set())):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(path + [neighbor])
        return []

    def _collect_bfs(
        self, start: str, adjacency: dict[str, set[str]], max_depth: int
    ) -> dict[str, int]:
        if start not in adjacency:
            return {}
        queue: builtins.list[tuple[str, int]] = [(start, 0)]
        seen = {start}
        distances: dict[str, int] = {}
        while queue:
            node_id, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for neighbor in sorted(adjacency.get(node_id, set())):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                distances[neighbor] = depth + 1
                queue.append((neighbor, depth + 1))
        return distances

    def impact_analysis(
        self, target: str, *, max_depth: int = 4, top_k: int = 10
    ) -> dict[str, Any]:
        node_id = self.resolve_node_id(target)
        if not node_id or node_id not in self.nodes:
            return {}

        forward = self._collect_bfs(node_id, self.edges, max_depth)
        reverse = self._collect_bfs(node_id, self.reverse_edges, max_depth)
        direct_dependents = self.reverse_neighbors(node_id)
        endpoint_impacts = [item for item in reverse if str(item).startswith("endpoint:")]
        caller_files = [
            item for item in reverse if self.nodes.get(item, {}).get("node_type") == "file"
        ]
        impacted_endpoint_handlers: builtins.list[str] = []
        for endpoint_id in sorted(endpoint_impacts):
            for handler_file in self.neighbors(endpoint_id):
                if self.nodes.get(handler_file, {}).get("node_type") == "file":
                    impacted_endpoint_handlers.append(handler_file)
        impacted_endpoint_handlers = sorted(dict.fromkeys(impacted_endpoint_handlers))

        review_targets = sorted(
            dict.fromkeys(
                list(direct_dependents[:top_k])
                + caller_files[:top_k]
                + impacted_endpoint_handlers[:top_k]
            )
        )[:top_k]

        dependency_samples: builtins.list[builtins.list[str]] = []
        sample_candidates = endpoint_impacts[:3] + caller_files[:3]
        for candidate in sample_candidates[:3]:
            path = self.explain_dependency_path(candidate, node_id)
            if path:
                dependency_samples.append(path)

        if endpoint_impacts:
            risk_level = "high"
        elif len(caller_files) >= 3 or len(direct_dependents) >= 3:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "target": node_id,
            "node_type": self.nodes.get(node_id, {}).get("node_type", "file"),
            "risk_level": risk_level,
            "direct_dependents": direct_dependents[:top_k],
            "transitive_dependents": sorted(reverse, key=lambda item: (reverse[item], item))[
                :top_k
            ],
            "dependencies": sorted(forward, key=lambda item: (forward[item], item))[:top_k],
            "impacted_endpoints": sorted(endpoint_impacts)[:top_k],
            "impacted_endpoint_handlers": impacted_endpoint_handlers[:top_k],
            "caller_files": sorted(caller_files)[:top_k],
            "review_targets": review_targets,
            "dependency_paths": dependency_samples[:3],
        }

    def search_related(self, query: str, top_k: int = 5) -> builtins.list[dict[str, object]]:
        tokens = [token for token in re.split(r"[\s/_.:-]+", query.lower()) if token]
        scored: builtins.list[tuple[str, int]] = []
        for node_id in self.nodes:
            lowered = node_id.lower()
            score = sum(lowered.count(token) * 2 for token in tokens)
            score += len(self.edges.get(node_id, set()))
            score += len(self.reverse_edges.get(node_id, set()))
            if score > 0:
                scored.append((node_id, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return [
            {
                "id": node_id,
                "score": score,
                "neighbors": self.neighbors(node_id)[:5],
                "reverse_neighbors": self.reverse_neighbors(node_id)[:5],
                "node_type": self.nodes.get(node_id, {}).get("node_type", "file"),
            }
            for node_id, score in scored[:top_k]
        ]


@dataclass(frozen=True)
class KnowledgeGraphNode:
    id: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeGraphEdge:
    source: str
    target: str
    relation: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedKnowledgeEntity:
    id: str
    label: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedKnowledgeRelation:
    source: str
    target: str
    relation: str
    properties: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ExtractedKnowledgeEntity",
    "ExtractedKnowledgeRelation",
    "GraphIndex",
    "KnowledgeGraphEdge",
    "KnowledgeGraphNode",
    "LLM_ENTITY_EXTRACTION_TODO",
]
