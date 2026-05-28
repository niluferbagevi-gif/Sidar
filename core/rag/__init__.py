"""
Sidar Project - Belge Deposu ve Arama (RAG)
ChromaDB tabanlı Vektör Arama + BM25 Hibrit Sistemi.
Sürüm: 2.7.0 (GPU Hızlandırmalı Embedding + Motor Bağımsız Sorgu)

Özellikler:
1. Vektör Arama (ChromaDB): Anlamsal yakınlık (Semantic Search) - Chunking destekli
   → USE_GPU=true ise sentence-transformers CUDA üzerinde çalışır
   → GPU_MIXED_PRECISION=true ise FP16 ile bellek tasarrufu sağlanır
2. BM25 (SQLite FTS5): Disk tabanlı kelime sıklığı ve nadirlik tabanlı arama
3. Fallback: Basit anahtar kelime eşleşmesi
"""

import ast
import asyncio
import builtins
import functools
import hashlib
import importlib
import ipaddress
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bleach as _bleach
from opentelemetry import trace as _otel_trace

from config import Config
from core.db import postgres_failure_diagnosis
from core.embeddings import (
    get_sentence_transformer_model,
    sentence_transformer_local_files_only,
)
from core.utils.network_validation import is_local_only_host

_BLEACH_AVAILABLE = True

logger = logging.getLogger(__name__)
list = builtins.list
_DOCUMENT_STORE_SINGLETONS: dict[tuple[str, bool, str], "DocumentStore"] = {}
_DOCUMENT_STORE_SINGLETONS_LOCK = threading.Lock()


def _pgvector_failure_action_message(exc: BaseException) -> str:
    """Return a single-line pgvector fallback message using DB diagnostics."""

    diagnosis = postgres_failure_diagnosis("pgvector backend başlatılamadı", exc)
    if "yetki/parola" in diagnosis:
        return (
            "pgvector pasif, BM25 fallback aktif edildi. DATABASE_URL, SIDAR_CONTAINER_DATABASE_URL "
            "ve POSTGRES_PASSWORD değerleriyle parola/yetki ayarlarını "
            f"kontrol edin. Teşhis: {diagnosis}."
        )
    return f"pgvector pasif, BM25 fallback aktif. Teşhis: {diagnosis}."


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
class GraphRAGSearchPlan:
    query: str
    vector_backend: str
    vector_candidates: builtins.list[str] = field(default_factory=list)
    graph_nodes: builtins.list[KnowledgeGraphNode] = field(default_factory=list)
    graph_edges: builtins.list[KnowledgeGraphEdge] = field(default_factory=list)
    broker_topics: builtins.list[str] = field(default_factory=list)
    cypher_hint: str = ""


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


def embed_texts_for_semantic_cache(
    texts: builtins.list[str], cfg: Config | None = None
) -> builtins.list[builtins.list[float]]:
    from core.embeddings import embed_texts_for_semantic_cache as _embed

    return _embed(texts, cfg=cfg)


def build_embedding_function(
    use_gpu: bool = False,
    gpu_device: int = 0,
    mixed_precision: bool = False,
    cfg: Any | None = None,
) -> Any:
    """Public wrapper for backward-compatible embedding function construction."""
    return _build_embedding_function(
        use_gpu=use_gpu,
        gpu_device=gpu_device,
        mixed_precision=mixed_precision,
        cfg=cfg,
    )


def _build_embedding_function(
    use_gpu: bool = False,
    gpu_device: int = 0,
    mixed_precision: bool = False,
    cfg: Any | None = None,
) -> Any:
    """
    ChromaDB için GPU-farkında embedding fonksiyonu oluşturur.

    use_gpu=True  →  sentence-transformers all-MiniLM-L6-v2 CUDA üzerinde çalışır.
    use_gpu=False →  embedding fonksiyonu açıkça CPU device ile kurulur.

    Döndürülen nesne None ise ChromaDB kendi varsayılanını kullanır.
    """
    try:
        local_files_only = bool(sentence_transformer_local_files_only(cfg or Config, "all-MiniLM-L6-v2"))
        factory_identity = _resolve_embedding_factory_identity()
        return _build_embedding_function_cached(
            use_gpu=use_gpu,
            gpu_device=gpu_device,
            mixed_precision=mixed_precision,
            local_files_only=local_files_only,
            factory_identity=factory_identity,
        )
    except Exception as exc:
        logger.warning("⚠️  GPU embedding başlatılamadı, CPU'ya dönülüyor: %s", exc)
        local_files_only = bool(sentence_transformer_local_files_only(cfg or Config, "all-MiniLM-L6-v2"))
        factory_identity = _resolve_embedding_factory_identity()
        try:
            return _build_embedding_function_cached(
                use_gpu=False,
                gpu_device=0,
                mixed_precision=False,
                local_files_only=local_files_only,
                factory_identity=factory_identity,
            )
        except Exception as cpu_exc:
            logger.warning("⚠️  CPU embedding de başlatılamadı: %s", cpu_exc)
            return None


def _resolve_embedding_factory_identity() -> tuple[str, int]:
    embedding_module = sys.modules.get("chromadb.utils.embedding_functions")
    if embedding_module is None:
        embedding_module = importlib.import_module("chromadb.utils.embedding_functions")
    factory = embedding_module.SentenceTransformerEmbeddingFunction
    return (getattr(factory, "__module__", ""), id(factory))


@functools.lru_cache(maxsize=8)
def _build_embedding_function_cached(
    *,
    use_gpu: bool,
    gpu_device: int,
    mixed_precision: bool,
    local_files_only: bool,
    factory_identity: tuple[str, int],
) -> Any:
    del factory_identity
    embedding_module = sys.modules.get("chromadb.utils.embedding_functions")
    if embedding_module is None:
        embedding_module = importlib.import_module("chromadb.utils.embedding_functions")
    SentenceTransformerEmbeddingFunction = embedding_module.SentenceTransformerEmbeddingFunction

    device = "cpu"
    torch: Any | None = None
    if use_gpu:
        import torch as _torch

        torch = _torch
        device = f"cuda:{gpu_device}" if torch.cuda.is_available() else "cpu"

    model_name = "all-MiniLM-L6-v2"
    ef = SentenceTransformerEmbeddingFunction(
        model_name=model_name,
        device=device,
        local_files_only=local_files_only,
    )

    # Mixed precision: sentence-transformers encode sırasında half() uygula
    if mixed_precision and device.startswith("cuda"):
        if torch is not None and hasattr(torch, "autocast"):
            _orig_call = ef.__call__

            def _fp16_call(input: Any) -> Any:
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    return _orig_call(input)

            ef.__call__ = _fp16_call
        else:
            logging.warning("⚠️  mixed_precision istendi ancak torch.autocast bulunamadı; FP16 devre dışı.")

    logger.info(
        "ChromaDB embedding fonksiyonu başlatıldı: device=%s  mixed_precision=%s",
        device,
        mixed_precision,
    )
    return ef


class DocumentStore:
    """
    Yerel belge deposu — ChromaDB ile semantik arama.

    Güncellemeler (v2.6.0):
    - Recursive Character Chunking ile büyük belgeleri mantıksal parçalara ayırır.
    - USE_GPU=true ise GPU hızlandırmalı embedding fonksiyonu kullanılır.
    - GPU_MIXED_PRECISION=true ise FP16 ile VRAM tasarrufu sağlanır.
    """

    _hf_env_lock = threading.Lock()
    _hf_env_applied = False
    _backend_init_lock = threading.Lock()
    _backend_info_logged: dict[str, bool] = {}

    def __init__(
        self,
        store_dir: Path,
        top_k: int | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        use_gpu: bool = False,
        gpu_device: int = 0,
        mixed_precision: bool = False,
        cfg: Config | None = None,
        initialize_vector: bool = True,
    ) -> None:
        self.cfg = cfg or Config()
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.store_dir / "index.json"
        self.default_top_k = top_k if top_k is not None else getattr(self.cfg, "RAG_TOP_K", 3)
        self._chunk_size = (
            chunk_size if chunk_size is not None else getattr(self.cfg, "RAG_CHUNK_SIZE", 1000)
        )
        self._chunk_overlap = (
            chunk_overlap
            if chunk_overlap is not None
            else getattr(self.cfg, "RAG_CHUNK_OVERLAP", 200)
        )

        # GPU embedding ayarları
        self._use_gpu = use_gpu
        self._gpu_device = gpu_device
        self._mixed_precision = mixed_precision

        # ChromaDB delete+upsert atomikliği için lock
        self._write_lock = threading.Lock()

        # Meta verileri yükle
        self._index: dict[str, dict[str, Any]] = self._load_index()
        self.entity_graph_file = self.store_dir / "entity_graph.json"
        self._entity_graph: dict[str, Any] = self._load_entity_graph()
        self._entity_extraction_enabled = bool(
            getattr(self.cfg, "ENABLE_RAG_ENTITY_EXTRACTION", True)
        )
        self._entity_max_per_doc = int(getattr(self.cfg, "RAG_ENTITY_MAX_PER_DOC", 24) or 24)

        self._vector_backend = (
            str(getattr(self.cfg, "RAG_VECTOR_BACKEND", "chroma") or "chroma").strip().lower()
        )
        self._is_local_llm_provider = (
            str(getattr(self.cfg, "AI_PROVIDER", "") or "").lower() == "ollama"
        )
        self._local_hybrid_enabled = bool(getattr(self.cfg, "RAG_LOCAL_ENABLE_HYBRID", False))
        self._graph_rag_enabled = bool(getattr(self.cfg, "ENABLE_GRAPH_RAG", True))
        self._graph_root_dir = Path(
            getattr(self.cfg, "BASE_DIR", Path.cwd()) or Path.cwd()
        ).resolve()
        self._graph_index = GraphIndex(
            self._graph_root_dir,
            max_files=int(getattr(self.cfg, "GRAPH_RAG_MAX_FILES", 5000) or 5000),
        )
        self._graph_ready = False

        # Arama motorlarını başlat
        self._chroma_available = self._check_import("chromadb")
        self._pgvector_available = False

        self.chroma_client: Any | None = None
        self.collection: Any | None = None
        self.pg_engine: Any | None = None
        self._pg_embedding_model: Any | None = None
        self._pg_table = str(
            getattr(self.cfg, "PGVECTOR_TABLE", "rag_embeddings") or "rag_embeddings"
        )
        self._pg_embedding_dim = int(getattr(self.cfg, "PGVECTOR_EMBEDDING_DIM", 384) or 384)
        self._pg_embedding_model_name = str(
            getattr(self.cfg, "PGVECTOR_EMBEDDING_MODEL", "all-MiniLM-L6-v2") or "all-MiniLM-L6-v2"
        )
        self._vector_initialization_enabled = bool(initialize_vector)

        self._vector_init_done = False
        self._bm25_init_done = False
        self._initialize_backends_once()

    def _initialize_backends_once(self) -> None:
        with self._backend_init_lock:
            if self._vector_initialization_enabled:
                if self._vector_init_done:
                    logger.info("RAG backend init (1/2): vector=already-initialized")
                elif self._vector_backend == "pgvector":
                    self._chroma_available = False
                    self._init_pgvector()
                    self._vector_init_done = True
                    self._log_backend_init_status_once(
                        "vector_pgvector_status",
                        "RAG backend init (1/2): pgvector=%s",
                        "ready" if self._pgvector_available else "fallback",
                    )
                elif self._chroma_available:
                    self._init_chroma()
                    self._vector_init_done = True
                    self._log_backend_init_status_once(
                        "vector_chroma_status",
                        "RAG backend init (1/2): chroma=%s",
                        "ready" if self._chroma_available else "fallback",
                    )
            else:
                self._chroma_available = False
                self._log_backend_init_status_once(
                    "vector_disabled_notice",
                    "DocumentStore vektör başlatması devre dışı (initialize_vector=False).",
                )
                self._log_backend_init_status_once("vector_disabled_status", "RAG backend init (1/2): vector=disabled")

            # BM25 (SQLite FTS5) Başlatma
            self._bm25_available = True
            if self._bm25_init_done:
                logger.info("RAG backend init (2/2): bm25=already-initialized")
            else:
                self._init_fts()
                self._bm25_init_done = True
                self._log_backend_init_status_once(
                    "bm25_status",
                    "RAG backend init (2/2): bm25=%s",
                    "ready" if self._bm25_available else "fallback",
                )

            self._log_vector_backend_preference_hint()



    def _log_vector_backend_preference_hint(self) -> None:
        """Explain why BM25 is active when vector backends are also available."""
        if self._vector_backend != "bm25":
            return
        if not self._chroma_available and not self._pgvector_available:
            return

        available_vector: list[str] = []
        if self._chroma_available:
            available_vector.append("chroma")
        if self._pgvector_available:
            available_vector.append("pgvector")

        self._log_backend_init_status_once(
            "vector_preference_bm25_hint",
            "RAG_VECTOR_BACKEND=bm25 olduğu için aktif bellek BM25 olarak kalacak; hazır vektör backend(ler): %s. GPU/vektör kullanmak için RAG_VECTOR_BACKEND=chroma (veya pgvector), hibrit için RAG_LOCAL_ENABLE_HYBRID=true ayarlayın.",
            ",".join(available_vector),
        )

    @classmethod
    def _log_backend_init_status_once(cls, key: str, message: str, *args: Any) -> None:
        """Emit backend init messages as info once per process, then debug."""
        if not cls._backend_info_logged.get(key, False):
            cls._backend_info_logged[key] = True
            logger.info(message, *args)
            return
        logger.debug(message, *args)

    def _require_pg_engine(self) -> Any:
        engine = getattr(self, "pg_engine", None)
        if engine is None:
            raise RuntimeError("pgvector engine başlatılmamış.")
        return engine

    def _require_chroma_collection(self) -> Any:
        collection = getattr(self, "collection", None)
        if collection is None:
            raise RuntimeError("Chroma collection başlatılmamış.")
        return collection

    def _hf_runtime_env_overrides(self) -> dict[str, str]:
        """HF SDK/transformers için gerekli geçici ortam değişkenlerini hesapla."""
        overrides: dict[str, str] = {
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TRANSFORMERS_VERBOSITY": "error",
        }
        hf_token = getattr(self.cfg, "HF_TOKEN", "")
        if hf_token:
            overrides["HF_TOKEN"] = str(hf_token)
            overrides["HUGGING_FACE_HUB_TOKEN"] = str(hf_token)

        model_names = {
            "sentence-transformers/all-MiniLM-L6-v2",
            "all-MiniLM-L6-v2",
            str(getattr(self, "_pg_embedding_model_name", "") or ""),
        }
        if any(
            sentence_transformer_local_files_only(self.cfg, model_name)
            for model_name in model_names
            if model_name
        ):
            # HuggingFace/transformers explicitly support the numeric convention.
            # Keep it scoped to the SDK call so a parent Sidar process does not
            # leak HF_HUB_OFFLINE=1 into subprocesses that import config.py.
            overrides["HF_HUB_OFFLINE"] = "1"
            overrides["TRANSFORMERS_OFFLINE"] = "1"
        return overrides

    @contextmanager
    def _scoped_hf_runtime_env(self) -> Any:
        """Temporarily apply HuggingFace runtime environment and then restore it."""
        with self._hf_env_lock:
            overrides = self._hf_runtime_env_overrides()
            previous = {key: os.environ.get(key) for key in overrides}
            try:
                os.environ.update(overrides)
                type(self)._hf_env_applied = True
                yield
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def _apply_hf_runtime_env(self) -> None:
        """Backward-compatible no-leak wrapper for scoped HF runtime setup."""
        with self._scoped_hf_runtime_env():
            return None

    def close(self) -> None:
        """Ağır kaynakları serbest bırak."""
        self._pg_embedding_model = None
        pg_engine = getattr(self, "pg_engine", None)
        if pg_engine is not None:
            try:
                pg_engine.dispose()
            except Exception:
                logger.debug("pg_engine dispose edilemedi.", exc_info=True)
            finally:
                self.pg_engine = None

    def __del__(self) -> None:  # pragma: no cover
        try:
            self.close()
        except Exception as exc:
            logger.warning("RAG kaynakları kapatılırken hata oluştu: %s", exc, exc_info=True)

    # ─────────────────────────────────────────────
    #  BAŞLANGIÇ & AYARLAR
    # ─────────────────────────────────────────────

    def _check_import(self, module_name: str) -> bool:
        try:
            importlib.import_module(module_name)
            return True
        except Exception:
            return False

    def _init_chroma(self) -> None:
        """ChromaDB istemcisini ve koleksiyonunu başlat (GPU embedding destekli)."""
        # PostHog telemetri kütüphanesinin capture() API uyuşmazlığını
        # tetiklememesi için ChromaDB telemetrisini ortam değişkeniyle kapat.
        os.environ["CHROMA_TELEMETRY_DISABLED"] = "1"

        try:
            import chromadb
            from chromadb.config import Settings

            # Embedding modeli başlatılırken HF runtime değişkenlerini sızdırmadan uygula.
            with self._scoped_hf_runtime_env():
                # Veritabanını data/rag/chroma_db içinde tut
                db_path = self.store_dir / "chroma_db"
                self.chroma_client = chromadb.PersistentClient(
                    path=str(db_path),
                    settings=Settings(anonymized_telemetry=False),
                )

                # GPU-farkında embedding fonksiyonu
                embedding_fn = _build_embedding_function(
                    use_gpu=self._use_gpu,
                    gpu_device=self._gpu_device,
                    mixed_precision=self._mixed_precision,
                    cfg=self.cfg,
                )

            create_kwargs: dict[str, Any] = {"metadata": {"hnsw:space": "cosine"}}
            if embedding_fn is not None:
                create_kwargs["embedding_function"] = embedding_fn

            self.collection = self.chroma_client.get_or_create_collection(
                name="sidar_knowledge_base",
                **create_kwargs,
            )

            device_info = f"cuda:{self._gpu_device}" if self._use_gpu and embedding_fn else "cpu"
            logger.info(
                "ChromaDB vektör veritabanı başlatıldı. Embedding device: %s",
                device_info,
            )
        except Exception as exc:
            logger.error("ChromaDB başlatma hatası: %s", exc)
            self._chroma_available = False

    def _init_fts(self) -> None:
        """SQLite FTS5 sanal tablosunu başlatır (Disk tabanlı BM25)."""
        import sqlite3

        try:
            db_path = self.store_dir / "bm25_fts.db"
            self.fts_conn = sqlite3.connect(db_path, check_same_thread=False)
            self.fts_conn.row_factory = sqlite3.Row
            with self._write_lock:
                # FTS5 eklentisi ile sanal tablo oluştur (Türkçe karakter destekli)
                self.fts_conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS bm25_index USING fts5(
                        doc_id UNINDEXED,
                        session_id UNINDEXED,
                        content,
                        tokenize='unicode61 remove_diacritics 1'
                    );
                """)
                # Eski verileri migrate et (FTS5 boşsa ve önceden eklenmiş belgeler varsa)
                cursor = self.fts_conn.execute("SELECT count(*) as c FROM bm25_index")
                if cursor.fetchone()["c"] == 0 and self._index:
                    logger.info("Mevcut belgeler SQLite FTS5 disk motoruna aktarılıyor...")
                    for doc_id, meta in self._index.items():
                        doc_file = self.store_dir / f"{doc_id}.txt"
                        try:
                            content = doc_file.read_text(encoding="utf-8")
                            session_id = meta.get("session_id", "global")
                            self.fts_conn.execute(
                                "INSERT INTO bm25_index (doc_id, session_id, content) VALUES (?, ?, ?)",
                                (doc_id, session_id, content),
                            )
                        except Exception as exc:
                            logger.debug("Doküman FTS'e migrate edilemedi (%s): %s", doc_id, exc)
                self.fts_conn.commit()
            self._log_backend_init_status_once(
                "bm25_fts_init_success",
                "SQLite FTS5 (BM25) veritabanı disk üzerinde başarıyla başlatıldı.",
            )
        except Exception as exc:
            logger.error("FTS5 başlatma hatası: %s", exc)
            self._bm25_available = False

    @staticmethod
    def _normalize_pg_url(url: str) -> str:
        return url.replace("+asyncpg", "")

    @staticmethod
    def _format_vector_for_sql(values: builtins.list[float]) -> str:
        return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"

    def _init_pgvector(self) -> None:
        """PostgreSQL + pgvector tablosunu başlatır."""
        db_url = str(getattr(self.cfg, "DATABASE_URL", "") or "")
        if not db_url.startswith("postgresql"):
            logger.warning(
                _pgvector_failure_action_message(RuntimeError("DATABASE_URL is not PostgreSQL"))
            )
            return

        if not self._check_import("sqlalchemy") or not self._check_import("pgvector"):
            logger.warning(
                _pgvector_failure_action_message(RuntimeError("pgvector dependencies missing"))
            )
            return

        try:
            from sqlalchemy import create_engine, text

            self.pg_engine = create_engine(self._normalize_pg_url(db_url), pool_pre_ping=True)
            engine = self._require_pg_engine()
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                create_table_sql = f"""
                    CREATE TABLE IF NOT EXISTS {self._pg_table} (
                        doc_id TEXT NOT NULL,
                        parent_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        title TEXT,
                        source TEXT,
                        chunk_content TEXT,
                        embedding vector({self._pg_embedding_dim}),
                        PRIMARY KEY (doc_id, chunk_index)
                    )
                """
                conn.execute(text(create_table_sql))  # nosec B608
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS idx_{self._pg_table}_session ON {self._pg_table}(session_id)"
                    )
                )
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS idx_{self._pg_table}_parent ON {self._pg_table}(parent_id)"
                    )
                )
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS idx_{self._pg_table}_embedding_hnsw ON {self._pg_table} USING hnsw (embedding vector_cosine_ops)"
                    )
                )

            self._pg_embedding_model = get_sentence_transformer_model(
                self._pg_embedding_model_name, self.cfg
            )
            self._pg_embedding_device = "cuda" if bool(getattr(self, "_use_gpu", False)) else "cpu"
            self._pgvector_available = True
            self._log_backend_init_status_once(
                "pgvector_init_success",
                "pgvector backend başlatıldı: table=%s model=%s",
                self._pg_table,
                self._pg_embedding_model_name,
            )
        except Exception as exc:
            logger.warning(_pgvector_failure_action_message(exc))
            logger.debug("pgvector backend devre dışı bırakıldı: error_type=%s", type(exc).__name__)
            self._pgvector_available = False

    def _pgvector_embed_texts(
        self, texts: builtins.list[str]
    ) -> builtins.list[builtins.list[float]]:
        if not self._pg_embedding_model or not texts:
            return []
        try:
            try:
                vectors = self._pg_embedding_model.encode(
                    texts, normalize_embeddings=True, show_progress_bar=False
                )
            except TypeError:
                vectors = self._pg_embedding_model.encode(texts, normalize_embeddings=True)
            if hasattr(vectors, "tolist"):
                raw_vectors = vectors.tolist()
                return [list(map(float, row)) for row in raw_vectors]
            return [list(map(float, v)) for v in vectors]
        except Exception as exc:
            logger.warning("pgvector embedding üretilemedi: %s", exc)
            return []

    def _upsert_pgvector_chunks(
        self,
        doc_id: str,
        parent_id: str,
        session_id: str,
        title: str,
        source: str,
        chunks: builtins.list[str],
    ) -> None:
        if (
            not getattr(self, "_pgvector_available", False)
            or not getattr(self, "pg_engine", None)
            or not chunks
        ):
            return
        try:
            from sqlalchemy import text

            vectors = self._pgvector_embed_texts(chunks)
            if not vectors:
                return

            engine = self._require_pg_engine()
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"DELETE FROM {self._pg_table} WHERE parent_id = :parent_id AND session_id = :session_id"  # nosec B608
                    ),
                    {"parent_id": parent_id, "session_id": session_id},
                )
                rows = [
                    {
                        "doc_id": doc_id,
                        "parent_id": parent_id,
                        "session_id": session_id,
                        "chunk_index": idx,
                        "title": title,
                        "source": source,
                        "chunk_content": chunk,
                        "embedding": self._format_vector_for_sql(vec),
                    }
                    for idx, (chunk, vec) in enumerate(zip(chunks, vectors, strict=False))
                ]
                upsert_sql = """
                        INSERT INTO __TABLE__
                        (doc_id, parent_id, session_id, chunk_index, title, source, chunk_content, embedding)
                        VALUES
                        (:doc_id, :parent_id, :session_id, :chunk_index, :title, :source, :chunk_content, CAST(:embedding AS vector))
                        ON CONFLICT (doc_id, chunk_index)
                        DO UPDATE SET
                            parent_id = EXCLUDED.parent_id,
                            session_id = EXCLUDED.session_id,
                            title = EXCLUDED.title,
                            source = EXCLUDED.source,
                            chunk_content = EXCLUDED.chunk_content,
                            embedding = EXCLUDED.embedding
                    """.replace("__TABLE__", self._pg_table)  # nosec B608
                conn.execute(text(upsert_sql), rows)
        except Exception as exc:
            logger.error("pgvector belge ekleme hatası: %s", exc)

    def _delete_pgvector_parent(self, parent_id: str, session_id: str) -> None:
        if not getattr(self, "_pgvector_available", False) or not getattr(self, "pg_engine", None):
            return
        try:
            from sqlalchemy import text

            engine = self._require_pg_engine()
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"DELETE FROM {self._pg_table} WHERE parent_id = :parent_id AND session_id = :session_id"  # nosec B608
                    ),
                    {"parent_id": parent_id, "session_id": session_id},
                )
        except Exception as exc:
            logger.error("pgvector silme hatası: %s", exc)

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if self.index_file.exists():
            try:
                loaded = json.loads(self.index_file.read_text(encoding="utf-8"))
                return loaded if isinstance(loaded, dict) else {}
            except Exception as exc:
                logger.warning("RAG index okunamadı: %s", exc)
        return {}

    def _save_index(self) -> None:
        self.index_file.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _entity_slug(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
        normalized = normalized.strip("-")
        if normalized:
            return normalized[:80]
        return hashlib.md5(str(value).encode(), usedforsecurity=False).hexdigest()[:12]

    @classmethod
    def _entity_id(cls, label: str, name: str) -> str:
        return f"{label.lower()}:{cls._entity_slug(name)}"

    @staticmethod
    def _clean_entity_value(value: Any) -> str:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n-–—:|,.;")
        return cleaned[:180]

    def _load_entity_graph(self) -> dict[str, Any]:
        graph_file = getattr(self, "entity_graph_file", self.store_dir / "entity_graph.json")
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

    def _save_entity_graph(self) -> None:
        graph_file = getattr(self, "entity_graph_file", self.store_dir / "entity_graph.json")
        graph_file.write_text(
            json.dumps(self._ensure_entity_graph(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _ensure_entity_graph(self) -> dict[str, Any]:
        graph = getattr(self, "_entity_graph", None)
        if not isinstance(graph, dict):
            graph = {"nodes": {}, "edges": []}
            self._entity_graph = graph
        if not isinstance(graph.get("nodes"), dict):
            graph["nodes"] = {}
        if not isinstance(graph.get("edges"), list):
            graph["edges"] = []
        return graph

    def _extract_json_entities(
        self, payload: Any, prefix: str = ""
    ) -> builtins.list[ExtractedKnowledgeEntity]:
        key_to_label = {
            "campaign": "Campaign",
            "campaign_name": "Campaign",
            "name": "Campaign" if prefix.endswith("campaign") else "",
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
        entities: builtins.list[ExtractedKnowledgeEntity] = []
        if isinstance(payload, dict):
            for raw_key, raw_value in payload.items():
                key = str(raw_key).strip().lower().replace("-", "_").replace(" ", "_")
                label = key_to_label.get(key, "")
                if label and isinstance(raw_value, str | int | float):
                    name = self._clean_entity_value(raw_value)
                    if name:
                        entities.append(
                            ExtractedKnowledgeEntity(
                                id=self._entity_id(label, name),
                                label=label,
                                name=name,
                                properties={"source_field": key},
                            )
                        )
                if isinstance(raw_value, dict | list):
                    child_prefix = f"{prefix}.{key}" if prefix else key
                    entities.extend(self._extract_json_entities(raw_value, child_prefix))
        elif isinstance(payload, list):
            for item in payload[:20]:
                entities.extend(self._extract_json_entities(item, prefix))
        return entities

    def extract_document_entities(
        self,
        title: str,
        content: str,
        *,
        tags: builtins.list[str] | None = None,
        source: str = "",
    ) -> tuple[builtins.list[ExtractedKnowledgeEntity], builtins.list[ExtractedKnowledgeRelation]]:
        """RAG belgesinden deterministik pazarlama/kurumsal entity ilişkileri çıkarır."""
        text = f"{title}\n{content}"
        tag_values = tags or []
        patterns: dict[str, builtins.list[str]] = {
            "Campaign": [
                r"(?:kampanya(?: adı)?|campaign(?: name)?)\s*[:：=-]\s*([^\n;|]+)",
            ],
            "Brand": [
                r"(?:marka|brand(?: name)?)\s*[:：=-]\s*([^\n;|]+)",
            ],
            "Audience": [
                r"(?:hedef kitle|target audience|audience|persona)\s*[:：=-]\s*([^\n;|]+)",
            ],
            "Tone": [
                r"(?:marka dili|brand voice|tone|üslup|dil)\s*[:：=-]\s*([^\n;|]+)",
            ],
            "Channel": [
                r"(?:kanal|channel|platform)\s*[:：=-]\s*([^\n;|]+)",
            ],
        }

        by_id: dict[str, ExtractedKnowledgeEntity] = {}

        def add_entity(label: str, raw_name: Any, **properties: Any) -> None:
            name = self._clean_entity_value(raw_name)
            if not name:
                return
            entity_id = self._entity_id(label, name)
            current = dict(
                by_id.get(entity_id, ExtractedKnowledgeEntity(entity_id, label, name)).properties
            )
            current.update(
                {key: value for key, value in properties.items() if value not in (None, "")}
            )
            by_id[entity_id] = ExtractedKnowledgeEntity(
                id=entity_id,
                label=label,
                name=name,
                properties=current,
            )

        for label, label_patterns in patterns.items():
            for pattern in label_patterns:
                for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                    value = self._clean_entity_value(match.group(1))
                    if value:
                        add_entity(label, value, extraction="regex")

        for tag in tag_values:
            if ":" not in str(tag):
                continue
            key, value = [part.strip() for part in str(tag).split(":", 1)]
            tag_label = {
                "campaign": "Campaign",
                "brand": "Brand",
                "audience": "Audience",
                "target_audience": "Audience",
                "tone": "Tone",
                "channel": "Channel",
            }.get(key.lower())
            if tag_label:
                add_entity(tag_label, value, extraction="tag", tag=tag)

        stripped = content.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                for entity in self._extract_json_entities(json.loads(stripped)):
                    add_entity(entity.label, entity.name, **entity.properties, extraction="json")
            except json.JSONDecodeError:
                pass

        if "kampanya" in title.lower() or "campaign" in title.lower():
            add_entity("Campaign", title, extraction="title")
        if source:
            add_entity("Source", source, extraction="source")

        entities = list(by_id.values())[: max(1, getattr(self, "_entity_max_per_doc", 24))]
        ids_by_label: dict[str, builtins.list[str]] = {}
        for entity in entities:
            ids_by_label.setdefault(entity.label, []).append(entity.id)

        relations: builtins.list[ExtractedKnowledgeRelation] = []
        campaign_ids = ids_by_label.get("Campaign", [])
        for campaign_id in campaign_ids:
            for audience_id in ids_by_label.get("Audience", []):
                relations.append(
                    ExtractedKnowledgeRelation(campaign_id, audience_id, "TARGETS_AUDIENCE")
                )
            for tone_id in ids_by_label.get("Tone", []):
                relations.append(ExtractedKnowledgeRelation(campaign_id, tone_id, "USES_TONE"))
            for brand_id in ids_by_label.get("Brand", []):
                relations.append(
                    ExtractedKnowledgeRelation(campaign_id, brand_id, "PROMOTES_BRAND")
                )
            for channel_id in ids_by_label.get("Channel", []):
                relations.append(ExtractedKnowledgeRelation(campaign_id, channel_id, "RUNS_ON"))

        for brand_id in ids_by_label.get("Brand", []):
            for tone_id in ids_by_label.get("Tone", []):
                relations.append(ExtractedKnowledgeRelation(brand_id, tone_id, "HAS_BRAND_VOICE"))

        return entities, relations

    def _upsert_document_entities(
        self,
        doc_id: str,
        title: str,
        content: str,
        *,
        source: str = "",
        tags: builtins.list[str] | None = None,
        session_id: str = "global",
    ) -> None:
        if not getattr(self, "_entity_extraction_enabled", True):
            return
        graph = self._ensure_entity_graph()
        nodes: dict[str, dict[str, Any]] = graph["nodes"]
        edges: builtins.list[dict[str, Any]] = graph["edges"]
        doc_node_id = f"doc:{doc_id}"

        edges[:] = [
            edge
            for edge in edges
            if edge.get("source") != doc_node_id and edge.get("doc_id") != doc_id
        ]
        nodes[doc_node_id] = {
            "id": doc_node_id,
            "label": "Document",
            "name": title or doc_id,
            "properties": {"doc_id": doc_id, "session_id": session_id, "source": source},
        }

        entities, relations = self.extract_document_entities(
            title, content, tags=tags, source=source
        )
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

        self._save_entity_graph()

    def _delete_document_entities(self, doc_id: str) -> None:
        graph = self._ensure_entity_graph()
        nodes: dict[str, dict[str, Any]] = graph["nodes"]
        doc_node_id = f"doc:{doc_id}"
        nodes.pop(doc_node_id, None)
        graph["edges"] = [edge for edge in graph["edges"] if edge.get("doc_id") != doc_id]
        referenced = {
            str(edge.get("source"))
            for edge in graph["edges"]
            if str(edge.get("source", "")).startswith(
                ("campaign:", "brand:", "audience:", "tone:", "channel:", "source:")
            )
        } | {
            str(edge.get("target"))
            for edge in graph["edges"]
            if str(edge.get("target", "")).startswith(
                ("campaign:", "brand:", "audience:", "tone:", "channel:", "source:")
            )
        }
        for node_id in list(nodes):
            if (
                node_id.startswith(
                    ("campaign:", "brand:", "audience:", "tone:", "channel:", "source:")
                )
                and node_id not in referenced
            ):
                nodes.pop(node_id, None)
        self._save_entity_graph()

    def search_entity_graph(
        self, query: str, *, session_id: str = "global", top_k: int = 5
    ) -> builtins.list[dict[str, Any]]:
        graph = self._ensure_entity_graph()
        tokens = [token for token in re.split(r"[\s/_.:-]+", query.lower()) if token]
        if not tokens:
            return []
        scored: builtins.list[tuple[str, int]] = []
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

        results: builtins.list[dict[str, Any]] = []
        for node_id, score in scored[:top_k]:
            relations = [
                edge
                for edge in graph["edges"]
                if edge.get("source") == node_id or edge.get("target") == node_id
            ][:8]
            results.append({"node": nodes[node_id], "score": score, "relations": relations})
        return results

    # ─────────────────────────────────────────────
    #  BELGE YÖNETİMİ & CHUNKING
    # ─────────────────────────────────────────────

    def _recursive_chunk_text(self, text: str, size: int, overlap: int) -> builtins.list[str]:
        """
        Metni kod yapısına uygun ayırıcılarla (separators) mantıksal parçalara böler.
        LangChain'in RecursiveCharacterTextSplitter mantığını simüle eder.
        """
        if not text or size <= 0:
            return []
        overlap = max(0, int(overlap or 0))
        if overlap >= size:
            overlap = max(0, size - 1)

        # Öncelik sırasına göre ayırıcılar (Python ve genel metin için optimize)
        separators = ["\nclass ", "\ndef ", "\n\n", "\n", " ", ""]

        def _split(text_part: str, sep_idx: int) -> builtins.list[str]:
            """Recursive bölme fonksiyonu"""
            if len(text_part) <= size:
                return [text_part]

            if sep_idx >= len(separators):
                # Hiçbir ayırıcı ile bölünemiyorsa zorla böl (character limit)
                step = max(1, size - overlap)
                return [text_part[i : i + size] for i in range(0, len(text_part), step)]

            sep = separators[sep_idx]
            # Ayırıcıya göre böl (ayırıcı başta kalsın diye lookahead simülasyonu yapılabilir ama basit split yeterli)
            # Not: Python split ayırıcıyı yutar, tekrar eklemek gerekebilir.
            # Burada basit split kullanıyoruz, bağlam kaybı olmaması için overlap önemli.
            if sep == "":
                parts = list(text_part)  # Karakter karakter
            else:
                parts = text_part.split(sep)
                # Ayırıcıyı parçalara geri ekleyelim (özellikle class/def için önemli)
                parts = [parts[0]] + [sep + p for p in parts[1:]] if parts else []

            new_chunks = []
            current_chunk = ""

            for part in parts:
                # Eğer parça tek başına bile çok büyükse, bir sonraki ayırıcı ile böl
                if len(part) > size:
                    if current_chunk:
                        new_chunks.append(current_chunk)
                        current_chunk = ""
                    sub_chunks = _split(part, sep_idx + 1)
                    new_chunks.extend(sub_chunks)
                    continue

                # Mevcut parça ile limiti aşıyor mu?
                if len(current_chunk) + len(part) > size:
                    new_chunks.append(current_chunk)
                    # Overlap mekanizması: Bir önceki chunk'ın sonundan biraz al
                    overlap_len = min(len(current_chunk), overlap)
                    current_chunk = current_chunk[-overlap_len:] + part
                else:
                    current_chunk += part

            if current_chunk:
                new_chunks.append(current_chunk)

            return new_chunks

        return _split(text, 0)

    def _chunk_text(
        self,
        text: str,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> builtins.list[str]:
        """Chunking ayarlarını Config'den çözerek recursive parçalama yap."""
        size_raw = (
            chunk_size
            if chunk_size is not None
            else getattr(self.cfg, "RAG_CHUNK_SIZE", self._chunk_size)
        )
        overlap_raw = (
            chunk_overlap
            if chunk_overlap is not None
            else getattr(self.cfg, "RAG_CHUNK_OVERLAP", self._chunk_overlap)
        )
        c_size = int(size_raw or 0)
        c_overlap = int(overlap_raw or 0)
        if c_size <= 0:
            return []
        if c_overlap < 0:
            c_overlap = 0
        return self._recursive_chunk_text(text, c_size, c_overlap)

    def _add_document_sync(
        self,
        title: str,
        content: str,
        source: str = "",
        tags: builtins.list[str] | None = None,
        session_id: str = "global",
    ) -> str:
        doc_id = uuid.uuid4().hex[:12]
        parent_id = hashlib.md5(f"{title}{source}".encode(), usedforsecurity=False).hexdigest()[:12]
        tags = tags or []
        now = time.time()

        chunks = self._chunk_text(content)
        ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "source": source,
                "title": title,
                "tags": ",".join(tags),
                "parent_id": parent_id,
                "chunk_index": i,
                "session_id": session_id,
                "created_at": now,
                "last_accessed_at": now,
                "access_count": 0,
            }
            for i in range(len(chunks))
        ]

        with self._write_lock:
            doc_file = self.store_dir / f"{doc_id}.txt"
            doc_file.write_text(content, encoding="utf-8")

            self._index[doc_id] = {
                "title": title,
                "source": source,
                "tags": tags,
                "size": len(content),
                "preview": content[:300],
                "parent_id": parent_id,
                "session_id": session_id,
                "created_at": now,
                "last_accessed_at": now,
                "access_count": 0,
            }
            self._save_index()
            self._update_bm25_cache_on_add(doc_id, content)

            if self._chroma_available and self.collection:
                try:
                    self.collection.delete(where={"parent_id": parent_id})
                    if chunks:
                        self.collection.upsert(
                            ids=ids,
                            documents=chunks,
                            metadatas=metadatas,
                        )
                    if chunks:
                        logger.info(
                            "ChromaDB: %s belgesi (%s) %d parçaya ayrılarak eklendi. (Oturum: %s)",
                            doc_id,
                            parent_id,
                            len(chunks),
                            session_id,
                        )
                except Exception as exc:
                    logger.error("ChromaDB belge ekleme hatası: %s", exc)

            if getattr(self, "_pgvector_available", False):
                self._upsert_pgvector_chunks(doc_id, parent_id, session_id, title, source, chunks)

            self._upsert_document_entities(
                doc_id,
                title,
                content,
                source=source,
                tags=tags,
                session_id=session_id,
            )

        logger.debug(
            "RAG belge eklendi: [%s] %s (%d karakter) [Oturum: %s]",
            doc_id,
            title,
            len(content),
            session_id,
        )
        return doc_id

    async def add_document(
        self,
        title: str,
        content: str,
        source: str = "",
        tags: builtins.list[str] | None = None,
        session_id: str = "global",
    ) -> str:
        return await asyncio.to_thread(
            self._add_document_sync,
            title,
            content,
            source,
            tags,
            session_id,
        )

    @staticmethod
    def _validate_url_safe(url: str) -> None:
        """SSRF koruması: yalnızca public HTTP/HTTPS URL'lerine izin verir."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"Yalnızca http/https URL'lerine izin verilir, alınan: '{parsed.scheme}'"
            )
        hostname = parsed.hostname or ""
        if not hostname:
            raise ValueError("URL geçerli bir hostname içermiyor.")
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                raise ValueError(f"İç ağ adresine erişim engellendi: {hostname}")
        except ValueError as exc:
            # ip_address() hata fırlattıysa ama "İç ağ" mesajımız değilse → hostname (DNS adı)
            if "İç ağ" in str(exc):
                raise
        blocked_hosts = {"localhost", "metadata.google.internal", "169.254.169.254"}
        if hostname.lower() in blocked_hosts:
            raise ValueError(f"Engellenen hostname: {hostname}")

    async def add_document_from_url(
        self,
        url: str,
        title: str = "",
        tags: builtins.list[str] | None = None,
        session_id: str = "global",
    ) -> tuple[bool, str]:
        import httpx

        try:
            self._validate_url_safe(url)
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                max_redirects=5,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as client:
                resp = await client.get(url)
            resp.raise_for_status()
            content = self._clean_html(resp.text)

            if not title:
                m = re.search(r"<title[^>]*>([^<]+)</title>", resp.text, re.IGNORECASE)
                title = m.group(1).strip() if m else url.split("/")[-1] or url

            doc_id = await self.add_document(title, content, url, tags, session_id)
            return True, f"✓ Belge eklendi: [{doc_id}] {title} ({len(content)} karakter)"
        except Exception as exc:
            logger.error("URL belge çekme hatası: %s", exc)
            return False, f"[HATA] URL belge eklenemedi: {exc}"

    def add_document_from_file(
        self,
        path: str,
        title: str = "",
        tags: builtins.list[str] | None = None,
        session_id: str = "global",
    ) -> tuple[bool, str]:
        # Boş uzantı ("") kaldırıldı — uzantısız dosyalar ikili olabilir ve path traversal riski taşır
        _TEXT_EXTS = {
            ".py",
            ".txt",
            ".md",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".html",
            ".css",
            ".js",
            ".ts",
            ".sh",
            ".sql",
            ".csv",
            ".xml",
            ".rst",
            ".gitignore",
            ".dockerignore",
        }
        # Hassas yol kalıpları — proje kökü dışındaki kritik dosyalara erişimi engelle
        _BLOCKED_PARTS = {".env", ".git", "sessions", "__pycache__", "logs", "proc", "etc", "sys"}
        try:
            file = Path(path).resolve()
            if not file.exists():
                return False, f"✗ Dosya bulunamadı: {path}"
            if not file.is_file():
                return False, f"✗ Belirtilen yol bir dosya değil: {path}"
            # Base directory sınırı: proje kökü veya sistem geçici dizini altındaki dosyalara izin ver
            # (upload endpoint geçici dosyaları /tmp/ altında oluşturur)
            _allowed_roots = (Config.BASE_DIR, Path(tempfile.gettempdir()).resolve())
            if not any(file.is_relative_to(root) for root in _allowed_roots):
                return False, f"✗ Erişim engellendi: dosya proje dizini dışında: {path}"
            # Path traversal koruması: dosyanın hassas dizinler içermediğini doğrula
            if _BLOCKED_PARTS.intersection(set(file.parts)):
                return (
                    False,
                    f"✗ Erişim engellendi: güvenlik politikası bu yola izin vermiyor: {path}",
                )
            if file.suffix.lower() not in _TEXT_EXTS:
                return False, f"✗ Desteklenmeyen dosya türü: {file.suffix}"

            content = file.read_text(encoding="utf-8", errors="replace")
            if not content.strip():
                return False, f"✗ Dosya boş: {path}"
            if not title:
                title = file.name

            source = f"file://{file}"
            doc_id = self._add_document_sync(
                title, content, source=source, tags=tags or [], session_id=session_id
            )
            return (
                True,
                f"✓ Dosya RAG deposuna eklendi: [{doc_id}] {title} ({len(content):,} karakter)",
            )
        except Exception as exc:
            logger.error("Dosya belge ekleme hatası (%s): %s", path, exc)
            return False, f"[HATA] Dosya eklenemedi: {exc}"

    def get_index_info(self, session_id: str | None = None) -> builtins.list[dict[str, Any]]:
        return [
            {
                "id": doc_id,
                "title": meta.get("title", "?"),
                "source": meta.get("source", ""),
                "size": meta.get("size", 0),
                "preview": meta.get("preview", "")[:120],
                "tags": meta.get("tags", []),
                "session_id": meta.get("session_id", "global"),
                "access_count": int(meta.get("access_count", 0) or 0),
            }
            for doc_id, meta in self._index.items()
            if session_id is None or meta.get("session_id", "global") == session_id
        ]

    @property
    def doc_count(self) -> int:
        """Dizindeki belge sayısını döndürür."""
        return len(self._index)

    def delete_document(self, doc_id: str, session_id: str = "global") -> str:
        """Belgeyi tüm depolardan sil (İzolasyon Korumalı)."""
        if doc_id not in self._index:
            return f"✗ Belge bulunamadı: {doc_id}"

        # İzolasyon yetki kontrolü
        meta = self._index[doc_id]
        if meta.get("session_id", "global") != session_id and session_id != "global":
            return "✗ HATA: Bu belgeye erişim yetkiniz yok (Farklı bir sohbete ait)."

        with self._write_lock:
            if doc_id not in self._index:
                return f"✗ Belge zaten silinmiş: {doc_id}"

            title = self._index[doc_id].get("title", doc_id)

            # 1. Dosya sil
            doc_file = self.store_dir / f"{doc_id}.txt"
            if doc_file.exists():
                doc_file.unlink()

            # 2. ChromaDB'den sil
            if self._chroma_available and self.collection:
                try:
                    parent_id = self._index[doc_id].get("parent_id", doc_id)
                    self.collection.delete(where={"parent_id": parent_id})
                except Exception as exc:
                    logger.error("ChromaDB silme hatası: %s", exc)

            if getattr(self, "_pgvector_available", False):
                parent_id = self._index[doc_id].get("parent_id", doc_id)
                self._delete_pgvector_parent(parent_id, meta.get("session_id", "global"))

            # 3. Index'ten, BM25'ten ve ilişkisel entity graph'tan sil
            self._delete_document_entities(doc_id)
            del self._index[doc_id]
            self._save_index()
            self._update_bm25_cache_on_delete(doc_id)

        return f"✓ Belge silindi: [{doc_id}] {title}"

    def _touch_document(self, doc_id: str) -> None:
        meta = self._index.get(doc_id)
        if not meta:
            return
        meta["last_accessed_at"] = time.time()
        meta["access_count"] = int(meta.get("access_count", 0) or 0) + 1
        self._save_index()

    def get_document(self, doc_id: str, session_id: str = "global") -> tuple[bool, str]:
        """Belge ID ile tam içerik getir (İzolasyon Korumalı)."""
        if doc_id not in self._index:
            return False, f"✗ Belge bulunamadı: {doc_id}"

        meta = self._index[doc_id]
        if meta.get("session_id", "global") != session_id and session_id != "global":
            return False, "✗ HATA: Bu belgeye erişim yetkiniz yok (Farklı bir sohbete ait)."

        doc_file = self.store_dir / f"{doc_id}.txt"
        if not doc_file.exists():
            return False, f"✗ Belge dosyası eksik: {doc_id}"
        content = doc_file.read_text(encoding="utf-8")
        self._touch_document(doc_id)
        return True, f"[{doc_id}] {meta['title']}\nKaynak: {meta.get('source', '-')}\n\n{content}"

    # ─────────────────────────────────────────────
    #  ARAMA (HİBRİT)
    # ─────────────────────────────────────────────

    def rebuild_graph_index(self, root_dir: str | None = None) -> tuple[bool, str]:
        """Kod tabanı için modül bağımlılık grafiğini yeniden oluştur."""
        if not self._graph_rag_enabled:
            return False, "GraphRAG devre dışı."
        target_root = Path(root_dir).resolve() if root_dir else self._graph_root_dir
        summary = self._graph_index.rebuild(target_root)
        self._graph_ready = True
        return True, (
            f"GraphIndex hazırlandı: root={target_root} "
            f"nodes={summary['nodes']} edges={summary['edges']}"
        )

    def _ensure_graph_ready(self) -> None:
        if self._graph_ready or not self._graph_rag_enabled:
            return
        self.rebuild_graph_index()

    def search_graph(self, query: str, top_k: int = 5) -> tuple[bool, str]:
        """GraphRAG üzerinden modül ilişkilerini ve ilgili düğümleri arar."""
        if not self._graph_rag_enabled:
            return False, "GraphRAG devre dışı."

        self._ensure_graph_ready()
        normalized = query.strip()
        if not normalized:
            return False, "GraphRAG için boş sorgu gönderilemez."

        if normalized.lower().startswith("impact:"):
            return self.analyze_graph_impact(normalized.split(":", 1)[1].strip(), top_k=top_k)

        if "->" in normalized:
            source, target = [part.strip() for part in normalized.split("->", 1)]
            return self.explain_dependency_path(source, target)

        results = self._graph_index.search_related(normalized, top_k=top_k)
        entity_results = self.search_entity_graph(normalized, top_k=top_k)
        if not results and not entity_results:
            return (
                False,
                f"GraphRAG içinde '{query}' için ilgili modül bulunamadı veya entity eşleşmedi.",
            )

        lines = [f"[GraphRAG: {query}]", ""]
        if entity_results:
            lines.append("İlişkisel bellek entity sonuçları:")
            graph = self._ensure_entity_graph()
            graph_nodes = graph["nodes"]
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

        if results:
            lines.append("Kod bağımlılık grafı sonuçları:")
        for item in results:
            lines.append(f"- {item['id']} (score={item['score']})")
            neighbors_raw = item.get("neighbors") or []
            neighbors_iter = neighbors_raw if isinstance(neighbors_raw, list | tuple | set) else []
            neighbors = [str(n) for n in neighbors_iter]
            if neighbors:
                lines.append(f"  Komşular: {', '.join(neighbors)}")
            reverse_raw = item.get("reverse_neighbors") or []
            reverse_iter = reverse_raw if isinstance(reverse_raw, list | tuple | set) else []
            reverse_neighbors = [str(n) for n in reverse_iter]
            if reverse_neighbors:
                lines.append(f"  Ters Komşular: {', '.join(reverse_neighbors)}")
        return True, "\n".join(lines)

    def explain_dependency_path(self, source: str, target: str) -> tuple[bool, str]:
        """İki modül arasındaki en kısa bağımlılık yolunu açıklar."""
        if not self._graph_rag_enabled:
            return False, "GraphRAG devre dışı."

        self._ensure_graph_ready()
        path = self._graph_index.explain_dependency_path(source.strip(), target.strip())
        if not path:
            return False, f"Bağımlılık yolu bulunamadı: {source} -> {target}"

        lines = [f"[GraphRAG Path] {source} -> {target}", ""]
        for index, node_id in enumerate(path, start=1):
            lines.append(f"{index}. {node_id}")
        return True, "\n".join(lines)

    def analyze_graph_impact(self, target: str, top_k: int = 10) -> tuple[bool, str]:
        """Bir modül veya endpoint değişiminin olası etki alanını açıklar."""
        ok, analysis = self.graph_impact_details(target, top_k=top_k)
        if not ok:
            return False, str(analysis)

        if not isinstance(analysis, dict):
            return False, "Graph impact analizi beklenen formatta dönmedi."
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
            lines.append(
                f"- Etkilenen endpoint handler dosyaları: {', '.join(impacted_endpoint_handlers)}"
            )
        if caller_files:
            lines.append(f"- Çağıran dosyalar: {', '.join(caller_files)}")
        if review_targets:
            lines.append(f"- Reviewer için önerilen hedefler: {', '.join(review_targets)}")
        if dependency_paths:
            lines.append("- Örnek etki zincirleri:")
            for idx, path in enumerate(dependency_paths, start=1):
                lines.append(f"  {idx}. {' -> '.join(path)}")
        return True, "\n".join(lines)

    def graph_impact_details(
        self, target: str, top_k: int = 10
    ) -> tuple[bool, dict[str, Any] | str]:
        """GraphRAG etki analizini yapılandırılmış veri olarak döndürür."""
        if not self._graph_rag_enabled:
            return False, "GraphRAG devre dışı."

        self._ensure_graph_ready()
        normalized = target.strip()
        if not normalized:
            return False, "Etki analizi için hedef belirtilmedi."

        analysis = self._graph_index.impact_analysis(normalized, top_k=top_k)
        if not analysis:
            return False, f"GraphRAG içinde '{target}' için etki analizi üretilemedi."
        return True, analysis

    def build_knowledge_graph_projection(
        self,
        *,
        session_id: str = "global",
        include_code_graph: bool = True,
        limit: int = 100,
    ) -> dict[str, Any]:
        """pgvector/Chroma belge katmanını bilgi grafı düğüm/kenarlarına yansıtır.

        Neo4j gibi bir katmana doğrudan yazmak yerine, önce taşınabilir bir projection
        üretir. Böylece ileride GraphRAG için `MERGE` tabanlı sync işleri kolaylaşır.
        """
        max_items = max(1, min(int(limit or 100), 1000))
        nodes: builtins.list[KnowledgeGraphNode] = []
        edges: builtins.list[KnowledgeGraphEdge] = []

        doc_items = list(self._index.items())[:max_items]
        for doc_id, meta in doc_items:
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
                        "vector_backend": "pgvector"
                        if getattr(self, "_pgvector_available", False)
                        else getattr(self, "_vector_backend", "bm25"),
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

        entity_graph = self._ensure_entity_graph()
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

        if include_code_graph and self._graph_rag_enabled:
            self._ensure_graph_ready()
            for node_id, attrs in list(self._graph_index.nodes.items())[:max_items]:
                nodes.append(
                    KnowledgeGraphNode(
                        id=f"code:{node_id}",
                        label="CodeNode",
                        properties=dict(attrs),
                    )
                )
            edge_count = 0
            for source_id, targets in self._graph_index.edges.items():
                for target_id in sorted(targets):
                    edge_count += 1
                    if edge_count > max_items:
                        break
                    edge_kinds = sorted(
                        self._graph_index.edge_kinds.get((source_id, target_id), {"RELATED_TO"})
                    )
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

        unique_nodes = list({(node.id, node.label): node for node in nodes}.values())
        cypher_hint = (
            "UNWIND $nodes AS node MERGE (n:KG {id: node.id}) "
            "SET n += node.properties, n.label = node.label "
            "WITH n UNWIND $edges AS edge MATCH (s:KG {id: edge.source}), (t:KG {id: edge.target}) "
            "MERGE (s)-[r:RELATED {relation: edge.relation}]->(t) SET r += edge.properties"
        )
        return {
            "nodes": unique_nodes,
            "edges": edges,
            "cypher_hint": cypher_hint,
            "vector_backend": "pgvector"
            if getattr(self, "_pgvector_available", False)
            else getattr(self, "_vector_backend", "bm25"),
        }

    def build_graphrag_search_plan(
        self,
        query: str,
        *,
        session_id: str = "global",
        top_k: int = 5,
    ) -> GraphRAGSearchPlan:
        """Vektör sonuçlarını bilgi grafı düğümleri ve dağıtık ajan topic'leriyle eşler."""
        normalized = str(query or "").strip()
        vector_backend = (
            "pgvector"
            if getattr(self, "_pgvector_available", False)
            else ("chromadb" if self._chroma_available and self.collection else "bm25")
        )
        vector_results: builtins.list[dict[str, Any]] = []
        if normalized:
            if getattr(self, "_pgvector_available", False):
                vector_results = self._fetch_pgvector(normalized, top_k, session_id)
            elif self._chroma_available and self.collection:  # pragma: no cover
                vector_results = self._fetch_chroma(normalized, top_k, session_id)

        vector_candidates = [
            str(item.get("doc_id", "") or "")
            for item in vector_results
            if str(item.get("doc_id", "") or "")
        ]
        projection = self.build_knowledge_graph_projection(
            session_id=session_id, include_code_graph=True, limit=max(20, top_k * 10)
        )
        graph_nodes = list(projection["nodes"])
        graph_edges = list(projection["edges"])

        def _broker_topic(receiver: str, intent: str, namespace: str = "sidar.swarm") -> str:
            return f"{namespace}.{str(receiver or 'unknown').strip().lower() or 'unknown'}.{str(intent or 'mixed').strip().lower() or 'mixed'}"

        broker_topics = [
            _broker_topic(receiver="researcher", intent="rag_search"),
            _broker_topic(receiver="reviewer", intent="graph_review"),
        ]
        return GraphRAGSearchPlan(
            query=normalized,
            vector_backend=vector_backend,
            vector_candidates=vector_candidates[:top_k],
            graph_nodes=graph_nodes[: max(20, top_k * 4)],
            graph_edges=graph_edges[: max(20, top_k * 4)],
            broker_topics=broker_topics,
            cypher_hint=str(projection.get("cypher_hint", "")),
        )

    def _search_sync(
        self, query: str, top_k: int | None = None, mode: str = "auto", session_id: str = "global"
    ) -> tuple[bool, str]:
        if top_k is None:
            top_k = getattr(self.cfg, "RAG_TOP_K", self.default_top_k)

        session_docs = [
            k for k, v in self._index.items() if v.get("session_id", "global") == session_id
        ]
        if mode != "graph" and not session_docs:
            return (
                False,
                "⚠ Bu oturum için belge deposu boş. Belge eklemek için: TOOL:docs_add:<başlık>|<url>",
            )

        if mode == "graph":
            return self.search_graph(query, top_k)

        if mode == "vector":
            if getattr(self, "_pgvector_available", False):
                return self._pgvector_search(query, top_k, session_id)
            if self._chroma_available and self.collection:
                return self._chroma_search(query, top_k, session_id)
            return False, "Vektör arama kullanılamıyor — pgvector/ChromaDB hazır değil."

        if mode == "bm25":
            if self._bm25_available:
                return self._bm25_search(query, top_k, session_id)
            return False, "BM25 kullanılamıyor — SQLite FTS5 başlatılamadı."

        if mode == "keyword":
            return self._keyword_search(query, top_k, session_id)

        has_vector = getattr(self, "_pgvector_available", False) or (
            self._chroma_available and self.collection
        )
        preferred_vector_backend = str(getattr(self, "_vector_backend", "") or "").strip().lower()

        # Yerel LLM + RAG birlikte çalışırken default olarak hibrid sorguyu kapatıp
        # tek motorlu akışla CPU/SQLite baskısını azalt.
        if (
            mode == "auto"
            and getattr(self, "_is_local_llm_provider", False)
            and not getattr(self, "_local_hybrid_enabled", False)
        ):
            if has_vector:
                if getattr(self, "_pgvector_available", False):
                    return self._pgvector_search(query, top_k, session_id)
                if self._chroma_available and self.collection:  # pragma: no cover
                    return self._chroma_search(query, top_k, session_id)
            if self._bm25_available:
                return self._bm25_search(query, top_k, session_id)
            return self._keyword_search(query, top_k, session_id)

        if (
            mode == "auto"
            and preferred_vector_backend == "pgvector"
            and getattr(self, "_pgvector_available", False)
        ):
            try:
                return self._pgvector_search(query, top_k, session_id)
            except Exception as exc:
                logger.warning(
                    "Tercih edilen pgvector araması hatası (fallback yapılıyor): %s", exc
                )

        if (
            mode == "auto"
            and preferred_vector_backend == "chroma"
            and self._chroma_available
            and self.collection
        ):
            try:
                return self._chroma_search(query, top_k, session_id)
            except Exception as exc:
                logger.warning("Tercih edilen Chroma araması hatası (fallback yapılıyor): %s", exc)

        if has_vector and self._bm25_available:
            try:
                return self._rrf_search(query, top_k, session_id)
            except Exception as exc:
                logger.warning("RRF arama hatası (Fallback yapılıyor): %s", exc)

        if getattr(self, "_pgvector_available", False):
            try:
                return self._pgvector_search(query, top_k, session_id)
            except Exception as exc:
                logger.warning("pgvector arama hatası (BM25'e düşülüyor): %s", exc)

        if self._chroma_available and self.collection:
            try:
                return self._chroma_search(query, top_k, session_id)
            except Exception as exc:
                logger.warning("ChromaDB arama hatası (BM25'e düşülüyor): %s", exc)

        if self._bm25_available:
            return self._bm25_search(query, top_k, session_id)
        return self._keyword_search(query, top_k, session_id)

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        mode: str = "auto",
        session_id: str = "global",
    ) -> tuple[bool, str]:
        tracer = _otel_trace.get_tracer(__name__) if _otel_trace is not None else None
        if tracer is None:
            result = await asyncio.to_thread(self._search_sync, query, top_k, mode, session_id)
            self._schedule_judge(query, result[1])
            return result

        with tracer.start_as_current_span("rag.search") as span:
            span.set_attribute("sidar.rag.mode", mode)
            span.set_attribute("sidar.rag.session_id", session_id)
            span.set_attribute("sidar.rag.query_len", len(query))
            result = await asyncio.to_thread(self._search_sync, query, top_k, mode, session_id)
            span.set_attribute("sidar.rag.success", result[0])
            self._schedule_judge(query, result[1])
            return result

    @staticmethod
    def _schedule_judge(query: str, answer_text: str) -> None:
        """LLM-as-a-Judge değerlendirmesini arka planda zamanla."""
        try:
            from core.judge import get_llm_judge

            judge = get_llm_judge()
            if not judge.enabled:
                return
            # answer_text'ten kısa bir özet al; tam metin yerine ilk 600 karakter
            judge.schedule_background_evaluation(
                query=query,
                documents=[answer_text[:1200]] if answer_text else [],
                answer=answer_text[:600] if answer_text else None,
            )
        except Exception as exc:
            logger.debug("Judge zamanlama hatası: %s", exc)

    def _rrf_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        vector_results = (
            self._fetch_pgvector(query, top_k, session_id)
            if getattr(self, "_pgvector_available", False)
            else self._fetch_chroma(query, top_k, session_id)
        )
        bm25_results = self._fetch_bm25(query, top_k, session_id)

        if not vector_results and not bm25_results:
            return self._keyword_search(query, top_k, session_id)

        k = 60
        rrf_scores: dict[str, float] = {}
        docs_map: dict[str, dict[str, Any]] = {}

        for rank, res in enumerate(vector_results):
            doc_id = res["id"]
            docs_map[doc_id] = res
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

        for rank, res in enumerate(bm25_results):
            doc_id = res["id"]
            if doc_id not in docs_map:
                docs_map[doc_id] = res
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

        ranked_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        final_results = []
        for doc_id, score in ranked_docs:
            doc_info = docs_map[doc_id]
            doc_info["score"] = score
            final_results.append(doc_info)

        vector_name = "pgvector" if getattr(self, "_pgvector_available", False) else "ChromaDB"
        return self._format_results_from_struct(
            final_results, query, source_name=f"Hibrit RRF ({vector_name} + BM25)"
        )

    def _fetch_pgvector(self, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]:
        if not getattr(self, "_pgvector_available", False) or not getattr(self, "pg_engine", None):
            return []
        try:
            from sqlalchemy import text

            qvec = self._format_vector_for_sql(self._pgvector_embed_texts([query])[0])
            engine = self._require_pg_engine()
            with engine.begin() as conn:
                select_sql = """
                        SELECT doc_id, parent_id, title, source, chunk_content,
                               (embedding <=> CAST(:qvec AS vector)) AS distance
                        FROM __TABLE__
                        WHERE session_id = :session_id
                        ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                        LIMIT :lim
                    """.replace("__TABLE__", self._pg_table)  # nosec B608
                rows = conn.execute(
                    text(select_sql),
                    {
                        "qvec": qvec,
                        "session_id": session_id,
                        "lim": max(
                            top_k * (2 if getattr(self, "_is_local_llm_provider", False) else 3),
                            top_k,
                        ),
                    },
                ).fetchall()

            found_docs, seen_parents = [], set()
            for row in rows:
                parent_id = row.parent_id
                if parent_id in seen_parents:
                    continue
                seen_parents.add(parent_id)
                found_docs.append(
                    {
                        "id": parent_id,
                        "title": row.title or "?",
                        "source": row.source or "",
                        "snippet": row.chunk_content or "",
                        "score": max(0.0, 1.0 - float(row.distance)),
                    }
                )
                if len(found_docs) >= top_k:
                    break
            return found_docs
        except Exception as exc:
            logger.warning("pgvector arama hatası: %s", exc)
            return []

    def _pgvector_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        results = self._fetch_pgvector(query, top_k, session_id)
        return self._format_results_from_struct(
            results, query, source_name="Vektör Arama (pgvector)"
        )

    def _fetch_chroma(self, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]:
        collection = self._require_chroma_collection()
        try:
            collection_size = collection.count()
        except Exception:
            collection_size = top_k * 2

        local_multiplier = max(
            1, int(getattr(self.cfg, "RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER", 1) or 1)
        )
        default_multiplier = 2
        multiplier = (
            local_multiplier
            if getattr(self, "_is_local_llm_provider", False)
            else default_multiplier
        )
        n_results = min(top_k * multiplier, max(collection_size, 1))

        # Filtreleme ChromaDB düzeyinde Where parametresiyle yapılıyor
        results = collection.query(
            query_texts=[query], n_results=n_results, where={"session_id": session_id}
        )

        ids = results.get("ids") or []
        if not ids or not ids[0]:
            return []

        documents = results.get("documents") or [[]]
        metadatas = results.get("metadatas") or [[]]
        doc_ids = ids[0]
        doc_chunks = documents[0] if documents else []
        doc_metas = metadatas[0] if metadatas else []

        found_docs: list[dict[str, Any]] = []
        seen_parents: set[str] = set()
        for i, chunk_content in enumerate(doc_chunks):
            raw_meta = doc_metas[i] if i < len(doc_metas) else {}
            meta = raw_meta if isinstance(raw_meta, dict) else {}
            parent_id = str(meta.get("parent_id") or (doc_ids[i] if i < len(doc_ids) else "") or "")
            if not parent_id:
                continue
            if parent_id in seen_parents and len(seen_parents) >= top_k:  # pragma: no cover
                continue
            seen_parents.add(parent_id)
            found_docs.append(
                {
                    "id": parent_id,
                    "title": str(meta.get("title", "?") or "?"),
                    "source": str(meta.get("source", "") or ""),
                    "snippet": str(chunk_content or ""),
                    "score": 1.0,
                }
            )
            if len(found_docs) >= top_k:
                break
        return found_docs

    def _chroma_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        results = self._fetch_chroma(query, top_k, session_id)
        return self._format_results_from_struct(
            results, query, source_name="Vektör Arama (ChromaDB + Chunking)"
        )

    def _update_bm25_cache_on_add(self, doc_id: str, content: str) -> None:
        """Yeni belgeyi SQLite FTS5 disk tablosuna kaydet.
        Not: Bu metod zaten _write_lock tutan bir bloktan çağrılır — içeride kilit alınmaz.
        """
        if not self._bm25_available:
            return
        session_id = self._index.get(doc_id, {}).get("session_id", "global")
        self.fts_conn.execute("DELETE FROM bm25_index WHERE doc_id = ?", (doc_id,))
        self.fts_conn.execute(
            "INSERT INTO bm25_index (doc_id, session_id, content) VALUES (?, ?, ?)",
            (doc_id, session_id, content),
        )
        self.fts_conn.commit()

    def _update_bm25_cache_on_delete(self, doc_id: str) -> None:
        """Silinen belgeyi SQLite FTS5'ten kaldır.
        Not: Bu metod zaten _write_lock tutan bir bloktan çağrılır — içeride kilit alınmaz.
        """
        if not self._bm25_available:
            return
        self.fts_conn.execute("DELETE FROM bm25_index WHERE doc_id = ?", (doc_id,))
        self.fts_conn.commit()

    def _fetch_bm25(self, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]:
        """Diskteki FTS5 veritabanından milisaniyelik BM25 araması yap."""
        if not self._bm25_available:
            return []

        words = [w for w in query.replace('"', "").replace("'", "").split() if w.isalnum()]
        if not words:
            return []

        # Kelimelerden herhangi birini içerenleri bul (OR mantığı)
        match_query = " OR ".join(words)

        sql = """
            SELECT doc_id, bm25(bm25_index) as score
            FROM bm25_index
            WHERE bm25_index MATCH ? AND session_id = ?
            ORDER BY score
            LIMIT ?
        """

        try:
            with self._write_lock:
                cursor = self.fts_conn.execute(sql, (match_query, session_id, top_k))
                rows = cursor.fetchall()
        except Exception as exc:
            logger.warning("FTS5 Arama Hatası: %s", exc)
            return []

        results = []
        for row in rows:
            doc_id = row["doc_id"]
            # FTS5 bm25 fonksiyonu negatif değer döndürür (en negatif = en alakalı). Bunu pozitife çeviriyoruz.
            score = abs(row["score"])

            meta = self._index.get(doc_id, {})
            doc_file = self.store_dir / f"{doc_id}.txt"
            try:
                content = doc_file.read_text(encoding="utf-8")
            except FileNotFoundError:
                content = ""
            snippet = self._extract_snippet(content, query)
            results.append(
                {
                    "id": doc_id,
                    "title": meta.get("title", "?"),
                    "source": meta.get("source", ""),
                    "snippet": snippet,
                    "score": score,
                }
            )
        return results

    def _bm25_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        results = self._fetch_bm25(query, top_k, session_id)
        return self._format_results_from_struct(results, query, source_name="BM25")

    def _keyword_search(self, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
        keywords = query.lower().split()
        scored = []

        for doc_id, meta in list(self._index.items()):
            if meta.get("session_id", "global") != session_id:
                continue

            doc_file = self.store_dir / f"{doc_id}.txt"
            try:
                text = doc_file.read_text(encoding="utf-8").lower()
            except FileNotFoundError:
                text = ""

            title_lower = meta["title"].lower()
            tags_lower = " ".join(meta.get("tags", [])).lower()

            score = sum(
                text.count(kw) + title_lower.count(kw) * 5 + tags_lower.count(kw) * 3
                for kw in keywords
            )
            if score > 0:
                scored.append((doc_id, score))

        ranked = sorted(scored, key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for doc_id, score in ranked:
            doc_file = self.store_dir / f"{doc_id}.txt"
            try:
                content = doc_file.read_text(encoding="utf-8")
            except FileNotFoundError:
                content = ""
            meta = self._index.get(doc_id, {})
            snippet = self._extract_snippet(content, query)
            results.append(
                {
                    "id": doc_id,
                    "title": meta.get("title", "?"),
                    "source": meta.get("source", ""),
                    "snippet": snippet,
                    "score": score,
                }
            )

        return self._format_results_from_struct(results, query, source_name="Kelime Eşleşmesi")

    def _format_results_from_struct(
        self, results: list[dict[str, Any]], query: str, source_name: str
    ) -> tuple[bool, str]:
        """Ortak sonuç biçimlendirici."""
        if not results:
            return False, f"'{query}' için belge deposunda ilgili sonuç bulunamadı."

        lines = [f"[RAG Arama: {query}] (Motor: {source_name})", ""]
        for res in results:
            lines.append(f"**[{res['id']}] {res['title']}**")
            if res["source"]:
                lines.append(f"  Kaynak: {res['source']}")

            # Snippet uzunluğunu sınırla ve satır sonlarını temizle
            snippet = res["snippet"].replace("\n", " ").strip()
            if len(snippet) > 400:
                snippet = snippet[:400] + "..."

            lines.append(f"  {snippet}")
            lines.append("")

        return True, "\n".join(lines)

    @staticmethod
    def _extract_snippet(content: str, query: str, window: int = 400) -> str:
        """Sorgudaki ilk anahtar kelimenin etrafındaki metni çıkar (BM25 ve Keyword için)."""
        keywords = query.lower().split()
        content_lower = content.lower()

        # Önce tam eşleşme ara
        for kw in keywords:
            idx = content_lower.find(kw)
            if idx != -1:
                start = max(0, idx - 100)
                end = min(len(content), idx + window)
                snippet = content[start:end].strip()
                return f"...{snippet}..." if start > 0 else snippet

        # Bulunamazsa baş tarafı döndür
        return content[:window] + ("..." if len(content) > window else "")

    # ─────────────────────────────────────────────
    #  LİSTELEME & STATÜ
    # ─────────────────────────────────────────────

    def consolidate_session_documents(
        self,
        session_id: str,
        *,
        keep_recent_docs: int = 2,
    ) -> dict[str, Any]:
        """Oturumdaki eski RAG belgelerini özetleyip düşük değerli embedding'leri temizler."""
        normalized_session = str(session_id or "").strip() or "global"
        docs = [
            (doc_id, dict(meta))
            for doc_id, meta in self._index.items()
            if meta.get("session_id", "global") == normalized_session
        ]
        keep_count = max(1, int(keep_recent_docs or 1))
        if len(docs) <= keep_count:
            return {
                "status": "skipped",
                "session_id": normalized_session,
                "removed_docs": 0,
                "summary_doc_id": "",
            }

        sorted_docs = sorted(
            docs,
            key=lambda item: (
                float(item[1].get("last_accessed_at", item[1].get("created_at", 0.0)) or 0.0),
                int(item[1].get("access_count", 0) or 0),
            ),
            reverse=True,
        )
        removable: builtins.list[tuple[str, dict[str, Any]]] = []
        for doc_id, meta in sorted_docs[keep_count:]:
            tags = {str(tag).strip().lower() for tag in list(meta.get("tags", []) or [])}
            if "pinned" in tags or "memory-summary" in tags:
                continue
            if int(meta.get("access_count", 0) or 0) > 1:
                continue
            removable.append((doc_id, meta))

        if not removable:
            return {
                "status": "skipped",
                "session_id": normalized_session,
                "removed_docs": 0,
                "summary_doc_id": "",
            }

        for doc_id, meta in list(docs):
            if str(meta.get("source", "") or "").startswith("memory://nightly-digest"):
                self.delete_document(doc_id, normalized_session)

        summary_lines = [
            f"Oturum: {normalized_session}",
            f"Konsolide edilen belge sayısı: {len(removable)}",
            "Öne çıkan eski belge özetleri:",
        ]
        for doc_id, meta in removable[:8]:
            summary_lines.append(
                f"- [{doc_id}] {meta.get('title', doc_id)} :: {str(meta.get('preview', '') or '')[:160]}"
            )
        summary_doc_id = self._add_document_sync(
            title=f"Nightly Memory Digest ({normalized_session})",
            content="\n".join(summary_lines),
            source="memory://nightly-digest",
            tags=["memory-summary", "nightly-consolidation"],
            session_id=normalized_session,
        )

        removed_docs = 0
        for doc_id, _meta in removable:
            self.delete_document(doc_id, normalized_session)
            removed_docs += 1

        return {
            "status": "completed",
            "session_id": normalized_session,
            "removed_docs": removed_docs,
            "summary_doc_id": summary_doc_id,
        }

    def list_documents(self, session_id: str | None = None) -> str:
        docs = {
            k: v
            for k, v in self._index.items()
            if session_id is None or v.get("session_id", "global") == session_id
        }
        if not docs:
            return "Belge deposu boş veya bu oturum için belge bulunamadı."

        backend_note = ""
        if getattr(self, "_vector_backend", "bm25") == "pgvector" and not getattr(self, "_pgvector_available", False):
            backend_note = " (pgvector pasif)"
        lines = [f"[Belge Deposu — {len(docs)} belge]{backend_note}", ""]
        for doc_id, meta in docs.items():
            tags = ", ".join(meta.get("tags", [])) or "-"
            size_kb = meta.get("size", 0) / 1024
            lines.append(f"  [{doc_id}] {meta['title']}")
            lines.append(
                f"    Kaynak: {meta.get('source', '-')} | Boyut: {size_kb:.1f} KB | Etiketler: {tags}"
            )
        return "\n".join(lines)

    # ─────────────────────────────────────────────
    #  YARDIMCILAR
    # ─────────────────────────────────────────────

    @staticmethod
    def _clean_html(html: str) -> str:
        """HTML'yi bleach ile temiz metne dönüştür."""
        clean = _bleach.clean(html, tags=[], attributes={}, strip=True, strip_comments=True)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    def status(self) -> str:
        engines = []
        if getattr(self, "_pgvector_available", False):
            engines.append("pgvector")
        elif self._chroma_available:
            gpu_tag = f"GPU cuda:{self._gpu_device}" if self._use_gpu else "CPU"
            engines.append(f"ChromaDB (Chunking + {gpu_tag})")
        elif self._vector_backend == "pgvector":
            engines.append("Vektör Arama (pgvector (pasif))")
        if self._bm25_available:
            engines.append("BM25 (SQLite FTS5)")
        engines.append("Anahtar Kelime")
        if self._graph_rag_enabled and self._graph_ready:  # pragma: no cover
            engines.append("GraphRAG (hazır)")

        return f"RAG: {len(self._index)} belge | Motorlar: {', '.join(engines)}"


def get_shared_document_store(
    *,
    store_dir: Path | str,
    cfg: Config,
    initialize_vector: bool,
) -> DocumentStore:
    """Process içi aynı RAG store'u tekrar kullanarak model init maliyetini düşür."""
    key = (
        str(Path(store_dir).resolve()),
        bool(initialize_vector),
        str(getattr(cfg, "RAG_VECTOR_BACKEND", "chroma") or "chroma").strip().lower(),
    )
    with _DOCUMENT_STORE_SINGLETONS_LOCK:
        store = _DOCUMENT_STORE_SINGLETONS.get(key)
        if store is None:
            store = DocumentStore(
                Path(store_dir),
                top_k=cfg.RAG_TOP_K,
                chunk_size=cfg.RAG_CHUNK_SIZE,
                chunk_overlap=cfg.RAG_CHUNK_OVERLAP,
                use_gpu=getattr(cfg, "USE_GPU", False),
                gpu_device=getattr(cfg, "GPU_DEVICE", 0),
                mixed_precision=getattr(cfg, "GPU_MIXED_PRECISION", False),
                cfg=cfg,
                initialize_vector=initialize_vector,
            )
            _DOCUMENT_STORE_SINGLETONS[key] = store
        return store
