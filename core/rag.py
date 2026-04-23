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
import hashlib
import importlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import asyncio
import ipaddress
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from config import Config
from opentelemetry import trace as _otel_trace
import bleach as _bleach
_BLEACH_AVAILABLE = True

logger = logging.getLogger(__name__)


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
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: Dict[str, Set[str]] = {}
        self.reverse_edges: Dict[str, Set[str]] = {}
        self.edge_kinds: Dict[Tuple[str, str], Set[str]] = {}

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

    def _iter_source_files(self, root_dir: Path) -> List[Path]:
        files: List[Path] = []
        for path in root_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                continue
            if any(part in {".git", "node_modules", "__pycache__", ".venv", "dist", "build"} for part in path.parts):
                continue
            files.append(path)
            if len(files) >= self.max_files:
                break
        return sorted(files)

    @staticmethod
    def _python_import_candidates(current_file: Path, module_name: str, level: int, root_dir: Path) -> List[Path]:
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
        return [candidate.resolve() for candidate in candidates if candidate.exists() and candidate.is_relative_to(root_dir)]

    @staticmethod
    def _script_import_candidates(current_file: Path, import_ref: str, root_dir: Path) -> List[Path]:
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
        return [candidate for candidate in candidates if candidate.exists() and candidate.is_file() and candidate.is_relative_to(root_dir)]

    @staticmethod
    def _extract_str_literal(node: Any) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value.strip()
        if isinstance(node, ast.Str):
            return node.s.strip()
        return None

    @staticmethod
    def _normalize_endpoint_path(raw_url: str) -> Optional[str]:
        value = (raw_url or "").strip().strip("'\"")
        if not value or "${" in value or "{" in value:
            return None
        if value.startswith(("ws://", "wss://", "http://", "https://")):
            parsed = urllib.parse.urlparse(value)
            hostname = (parsed.hostname or "").lower()
            if hostname and hostname not in {"localhost", "127.0.0.1", "0.0.0.0"}:
                return None
            value = parsed.path or "/"
        if not value.startswith("/"):
            return None
        return value or "/"

    def _parse_python_source(self, file_path: Path, content: str) -> Tuple[List[Path], List[Dict[str, str]], List[Dict[str, str]]]:
        deps: List[Path] = []
        endpoint_defs: List[Dict[str, str]] = []
        endpoint_calls: List[Dict[str, str]] = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return deps, endpoint_defs, endpoint_calls

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    deps.extend(self._python_import_candidates(file_path, alias.name, 0, self.root_dir))
                continue

            if isinstance(node, ast.ImportFrom):
                deps.extend(self._python_import_candidates(file_path, node.module or "", int(node.level or 0), self.root_dir))
                continue

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
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

    def _extract_script_endpoint_calls(self, content: str) -> List[Dict[str, str]]:
        calls: List[Dict[str, str]] = []
        seen: Set[Tuple[str, str]] = set()

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
            calls.append({"endpoint_id": self._endpoint_node_id(method, path), "method": method, "path": path})

        for match in re.finditer(r"""new\s+WebSocket\(\s*['"](?P<url>[^'"]+)['"]\s*\)""", content):
            path = self._normalize_endpoint_path(match.group("url"))
            if not path:
                continue
            key = ("WS", path)
            if key in seen:
                continue
            seen.add(key)
            calls.append({"endpoint_id": self._endpoint_node_id("WS", path), "method": "WS", "path": path})

        return calls

    def _extract_dependencies(self, file_path: Path, content: str) -> Tuple[List[Path], List[Dict[str, str]], List[Dict[str, str]]]:
        if file_path.suffix.lower() == ".py":
            return self._parse_python_source(file_path, content)

        deps: List[Path] = []
        import_refs = re.findall(r"""(?:from|import)\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)""", content)
        for pair in import_refs:
            ref = next((item for item in pair if item), "")
            deps.extend(self._script_import_candidates(file_path, ref, self.root_dir))
        return deps, [], self._extract_script_endpoint_calls(content)

    def rebuild(self, root_dir: Optional[Path] = None) -> Dict[str, int]:
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
            except Exception:
                continue
            dep_paths, endpoint_defs, endpoint_calls = self._extract_dependencies(file_path, content)
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

    def neighbors(self, node_id: str) -> List[str]:
        return sorted(self.edges.get(node_id, set()))

    def reverse_neighbors(self, node_id: str) -> List[str]:
        return sorted(self.reverse_edges.get(node_id, set()))

    def resolve_node_id(self, query: str) -> Optional[str]:
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
            node_id for node_id in self.nodes
            if node_id.lower().endswith(lowered) or lowered in node_id.lower()
        ]
        return sorted(suffix_matches, key=len)[0] if len(suffix_matches) == 1 else None

    def explain_dependency_path(self, source: str, target: str) -> List[str]:
        source_id = self.resolve_node_id(source) or source.strip()
        target_id = self.resolve_node_id(target) or target.strip()
        if source_id not in self.nodes or target_id not in self.nodes:
            return []
        queue: List[List[str]] = [[source_id]]
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

    def _collect_bfs(self, start: str, adjacency: Dict[str, Set[str]], max_depth: int) -> Dict[str, int]:
        if start not in adjacency:
            return {}
        queue: List[Tuple[str, int]] = [(start, 0)]
        seen = {start}
        distances: Dict[str, int] = {}
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

    def impact_analysis(self, target: str, *, max_depth: int = 4, top_k: int = 10) -> Dict[str, Any]:
        node_id = self.resolve_node_id(target)
        if not node_id or node_id not in self.nodes:
            return {}

        forward = self._collect_bfs(node_id, self.edges, max_depth)
        reverse = self._collect_bfs(node_id, self.reverse_edges, max_depth)
        direct_dependents = self.reverse_neighbors(node_id)
        endpoint_impacts = [item for item in reverse if str(item).startswith("endpoint:")]
        caller_files = [
            item for item in reverse
            if self.nodes.get(item, {}).get("node_type") == "file"
        ]
        impacted_endpoint_handlers: List[str] = []
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

        dependency_samples: List[List[str]] = []
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
            "transitive_dependents": sorted(reverse, key=lambda item: (reverse[item], item))[:top_k],
            "dependencies": sorted(forward, key=lambda item: (forward[item], item))[:top_k],
            "impacted_endpoints": sorted(endpoint_impacts)[:top_k],
            "impacted_endpoint_handlers": impacted_endpoint_handlers[:top_k],
            "caller_files": sorted(caller_files)[:top_k],
            "review_targets": review_targets,
            "dependency_paths": dependency_samples[:3],
        }

    def search_related(self, query: str, top_k: int = 5) -> List[Dict[str, object]]:
        tokens = [token for token in re.split(r"[\s/_.:-]+", query.lower()) if token]
        scored: List[Tuple[str, int]] = []
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
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeGraphEdge:
    source: str
    target: str
    relation: str
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphRAGSearchPlan:
    query: str
    vector_backend: str
    vector_candidates: List[str] = field(default_factory=list)
    graph_nodes: List[KnowledgeGraphNode] = field(default_factory=list)
    graph_edges: List[KnowledgeGraphEdge] = field(default_factory=list)
    broker_topics: List[str] = field(default_factory=list)
    cypher_hint: str = ""


def embed_texts_for_semantic_cache(texts: List[str], cfg: Optional[Config] = None) -> List[List[float]]:
    """Semantic cache için metinleri normalize edilmiş embedding vektörlerine dönüştürür."""
    if not texts:
        return []

    cfg = cfg or Config()
    model_name = str(getattr(cfg, "PGVECTOR_EMBEDDING_MODEL", "all-MiniLM-L6-v2") or "all-MiniLM-L6-v2")
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name)
        vectors = model.encode(texts, normalize_embeddings=True)
        return vectors.tolist() if hasattr(vectors, "tolist") else [list(v) for v in vectors]
    except Exception as exc:
        logger.debug("Semantic cache embedding üretilemedi: %s", exc)
        return []


def _build_embedding_function(use_gpu: bool = False,
                               gpu_device: int = 0,
                               mixed_precision: bool = False):
    """
    ChromaDB için GPU-farkında embedding fonksiyonu oluşturur.

    use_gpu=True  →  sentence-transformers all-MiniLM-L6-v2  CUDA üzerinde çalışır.
    use_gpu=False →  ChromaDB varsayılan CPU embedding'i kullanılır (None).

    Döndürülen nesne None ise ChromaDB kendi varsayılanını kullanır.
    """
    if not use_gpu:
        return None  # ChromaDB varsayılan (CPU) embedding fonksiyonu

    try:
        embedding_module = sys.modules.get("chromadb.utils.embedding_functions")
        if embedding_module is None:
            embedding_module = importlib.import_module("chromadb.utils.embedding_functions")
        SentenceTransformerEmbeddingFunction = getattr(embedding_module, "SentenceTransformerEmbeddingFunction")
        import torch

        device = f"cuda:{gpu_device}" if torch.cuda.is_available() else "cpu"

        ef = SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2",
            device=device,
        )

        # Mixed precision: sentence-transformers encode sırasında half() uygula
        if mixed_precision and device.startswith("cuda"):
            if hasattr(torch, "autocast"):
                _orig_call = ef.__call__

                def _fp16_call(input):
                    with torch.autocast(device_type="cuda", dtype=torch.float16):
                        return _orig_call(input)

                ef.__call__ = _fp16_call
            else:
                logging.warning(
                    "⚠️  mixed_precision istendi ancak torch.autocast bulunamadı; FP16 devre dışı."
                )

        logger.info(
            "🚀 ChromaDB GPU Embedding: device=%s  mixed_precision=%s",
            device, mixed_precision,
        )
        return ef

    except Exception as exc:
        logger.warning(
            "⚠️  GPU embedding başlatılamadı, CPU'ya dönülüyor: %s", exc
        )
        return None


class DocumentStore:
    """
    Yerel belge deposu — ChromaDB ile semantik arama.

    Güncellemeler (v2.6.0):
    - Recursive Character Chunking ile büyük belgeleri mantıksal parçalara ayırır.
    - USE_GPU=true ise GPU hızlandırmalı embedding fonksiyonu kullanılır.
    - GPU_MIXED_PRECISION=true ise FP16 ile VRAM tasarrufu sağlanır.
    """

    def __init__(
        self,
        store_dir: Path,
        top_k: Optional[int] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        use_gpu: bool = False,
        gpu_device: int = 0,
        mixed_precision: bool = False,
        cfg: Optional[Config] = None,
        initialize_vector: bool = True,
    ) -> None:
        self.cfg = cfg or Config()
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.index_file    = self.store_dir / "index.json"
        self.default_top_k = top_k if top_k is not None else getattr(self.cfg, "RAG_TOP_K", 3)
        self._chunk_size = chunk_size if chunk_size is not None else getattr(self.cfg, "RAG_CHUNK_SIZE", 1000)
        self._chunk_overlap = (
            chunk_overlap
            if chunk_overlap is not None
            else getattr(self.cfg, "RAG_CHUNK_OVERLAP", 200)
        )

        # GPU embedding ayarları
        self._use_gpu          = use_gpu
        self._gpu_device       = gpu_device
        self._mixed_precision  = mixed_precision

        # ChromaDB delete+upsert atomikliği için lock
        self._write_lock = threading.Lock()

        # Meta verileri yükle
        self._index: Dict[str, Dict] = self._load_index()

        self._vector_backend = str(getattr(self.cfg, "RAG_VECTOR_BACKEND", "chroma") or "chroma").strip().lower()
        self._is_local_llm_provider = str(getattr(self.cfg, "AI_PROVIDER", "") or "").lower() == "ollama"
        self._local_hybrid_enabled = bool(getattr(self.cfg, "RAG_LOCAL_ENABLE_HYBRID", False))
        self._graph_rag_enabled = bool(getattr(self.cfg, "ENABLE_GRAPH_RAG", True))
        self._graph_root_dir = Path(getattr(self.cfg, "BASE_DIR", Path.cwd()) or Path.cwd()).resolve()
        self._graph_index = GraphIndex(
            self._graph_root_dir,
            max_files=int(getattr(self.cfg, "GRAPH_RAG_MAX_FILES", 5000) or 5000),
        )
        self._graph_ready = False

        # Arama motorlarını başlat
        self._chroma_available = self._check_import("chromadb")
        self._pgvector_available = False

        self.chroma_client = None
        self.collection    = None
        self.pg_engine = None
        self._pg_embedding_model = None
        self._pg_table = str(getattr(self.cfg, "PGVECTOR_TABLE", "rag_embeddings") or "rag_embeddings")
        self._pg_embedding_dim = int(getattr(self.cfg, "PGVECTOR_EMBEDDING_DIM", 384) or 384)
        self._pg_embedding_model_name = str(
            getattr(self.cfg, "PGVECTOR_EMBEDDING_MODEL", "all-MiniLM-L6-v2") or "all-MiniLM-L6-v2"
        )
        self._vector_initialization_enabled = bool(initialize_vector)

        if self._vector_initialization_enabled:
            if self._vector_backend == "pgvector":
                self._chroma_available = False
                self._init_pgvector()
            elif self._chroma_available:
                self._init_chroma()
        else:
            self._chroma_available = False
            logger.info("DocumentStore vektör başlatması devre dışı (initialize_vector=False).")

        # BM25 (SQLite FTS5) Başlatma
        self._bm25_available = True
        self._init_fts()

    def _apply_hf_runtime_env(self) -> None:
        """HF model yükleme davranışını Config üzerinden ortama uygula."""
        hf_token = getattr(self.cfg, "HF_TOKEN", "")
        if hf_token:
            os.environ["HF_TOKEN"] = hf_token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

        if getattr(self.cfg, "HF_HUB_OFFLINE", False):
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

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

            # Embedding modeli başlatılmadan önce HF runtime değişkenlerini uygula.
            self._apply_hf_runtime_env()

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
            )

            create_kwargs: Dict = {"metadata": {"hnsw:space": "cosine"}}
            if embedding_fn is not None:
                create_kwargs["embedding_function"] = embedding_fn

            self.collection = self.chroma_client.get_or_create_collection(
                name="sidar_knowledge_base",
                **create_kwargs,
            )

            device_info = (
                f"cuda:{self._gpu_device}" if self._use_gpu and embedding_fn else "cpu"
            )
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
                                (doc_id, session_id, content)
                            )
                        except Exception:
                            pass
                self.fts_conn.commit()
            logger.info("SQLite FTS5 (BM25) veritabanı disk üzerinde başarıyla başlatıldı.")
        except Exception as exc:
            logger.error("FTS5 başlatma hatası: %s", exc)
            self._bm25_available = False

    @staticmethod
    def _normalize_pg_url(url: str) -> str:
        return url.replace("+asyncpg", "")

    @staticmethod
    def _format_vector_for_sql(values: List[float]) -> str:
        return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"

    def _init_pgvector(self) -> None:
        """PostgreSQL + pgvector tablosunu başlatır."""
        db_url = str(getattr(self.cfg, "DATABASE_URL", "") or "")
        if not db_url.startswith("postgresql"):
            logger.warning("pgvector backend için PostgreSQL DATABASE_URL gerekli. Alınan: %s", db_url)
            return

        if not self._check_import("sqlalchemy") or not self._check_import("pgvector"):
            logger.warning("pgvector backend için sqlalchemy ve pgvector paketleri gerekli.")
            return

        try:
            from sentence_transformers import SentenceTransformer
            from sqlalchemy import create_engine, text

            self._apply_hf_runtime_env()
            self.pg_engine = create_engine(self._normalize_pg_url(db_url), pool_pre_ping=True)
            with self.pg_engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.execute(text(f"""
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
                """))
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{self._pg_table}_session ON {self._pg_table}(session_id)"))
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{self._pg_table}_parent ON {self._pg_table}(parent_id)"))
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{self._pg_table}_embedding_hnsw ON {self._pg_table} USING hnsw (embedding vector_cosine_ops)"))

            self._pg_embedding_model = SentenceTransformer(self._pg_embedding_model_name)
            self._pgvector_available = True
            logger.info("pgvector backend başlatıldı: table=%s model=%s", self._pg_table, self._pg_embedding_model_name)
        except Exception as exc:
            logger.error("pgvector başlatma hatası: %s", exc)
            self._pgvector_available = False

    def _pgvector_embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not self._pg_embedding_model or not texts:
            return []
        try:
            vectors = self._pg_embedding_model.encode(texts, normalize_embeddings=True)
            return vectors.tolist() if hasattr(vectors, "tolist") else [list(v) for v in vectors]
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
        chunks: List[str],
    ) -> None:
        if not getattr(self, "_pgvector_available", False) or not getattr(self, "pg_engine", None) or not chunks:
            return
        try:
            from sqlalchemy import text

            vectors = self._pgvector_embed_texts(chunks)
            if not vectors:
                return

            with self.pg_engine.begin() as conn:
                conn.execute(
                    text(f"DELETE FROM {self._pg_table} WHERE parent_id = :parent_id AND session_id = :session_id"),
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
                    for idx, (chunk, vec) in enumerate(zip(chunks, vectors))
                ]
                conn.execute(
                    text(f"""
                        INSERT INTO {self._pg_table}
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
                    """),
                    rows,
                )
        except Exception as exc:
            logger.error("pgvector belge ekleme hatası: %s", exc)

    def _delete_pgvector_parent(self, parent_id: str, session_id: str) -> None:
        if not getattr(self, "_pgvector_available", False) or not getattr(self, "pg_engine", None):
            return
        try:
            from sqlalchemy import text

            with self.pg_engine.begin() as conn:
                conn.execute(
                    text(f"DELETE FROM {self._pg_table} WHERE parent_id = :parent_id AND session_id = :session_id"),
                    {"parent_id": parent_id, "session_id": session_id},
                )
        except Exception as exc:
            logger.error("pgvector silme hatası: %s", exc)

    def _load_index(self) -> Dict[str, Dict]:
        if self.index_file.exists():
            try:
                return json.loads(self.index_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("RAG index okunamadı: %s", exc)
        return {}

    def _save_index(self) -> None:
        self.index_file.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ─────────────────────────────────────────────
    #  BELGE YÖNETİMİ & CHUNKING
    # ─────────────────────────────────────────────

    def _recursive_chunk_text(self, text: str, size: int, overlap: int) -> List[str]:
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

        def _split(text_part: str, sep_idx: int) -> List[str]:
            """Recursive bölme fonksiyonu"""
            if len(text_part) <= size:
                return [text_part]

            if sep_idx >= len(separators):
                # Hiçbir ayırıcı ile bölünemiyorsa zorla böl (character limit)
                step = max(1, size - overlap)
                return [text_part[i:i + size] for i in range(0, len(text_part), step)]

            sep = separators[sep_idx]
            # Ayırıcıya göre böl (ayırıcı başta kalsın diye lookahead simülasyonu yapılabilir ama basit split yeterli)
            # Not: Python split ayırıcıyı yutar, tekrar eklemek gerekebilir.
            # Burada basit split kullanıyoruz, bağlam kaybı olmaması için overlap önemli.
            if sep == "":
                parts = list(text_part) # Karakter karakter
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
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> List[str]:
        """Chunking ayarlarını Config'den çözerek recursive parçalama yap."""
        size_raw = chunk_size if chunk_size is not None else getattr(self.cfg, "RAG_CHUNK_SIZE", self._chunk_size)
        overlap_raw = chunk_overlap if chunk_overlap is not None else getattr(self.cfg, "RAG_CHUNK_OVERLAP", self._chunk_overlap)
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
        tags: Optional[List[str]] = None,
        session_id: str = "global"
    ) -> str:
        doc_id = uuid.uuid4().hex[:12]
        parent_id = hashlib.md5(f"{title}{source}".encode()).hexdigest()[:12]
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
                            doc_id, parent_id, len(chunks), session_id
                        )
                except Exception as exc:
                    logger.error("ChromaDB belge ekleme hatası: %s", exc)

            if getattr(self, "_pgvector_available", False):
                self._upsert_pgvector_chunks(doc_id, parent_id, session_id, title, source, chunks)

        logger.info("RAG belge eklendi: [%s] %s (%d karakter) [Oturum: %s]", doc_id, title, len(content), session_id)
        return doc_id

    async def add_document(
        self,
        title: str,
        content: str,
        source: str = "",
        tags: Optional[List[str]] = None,
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
            raise ValueError(f"Yalnızca http/https URL'lerine izin verilir, alınan: '{parsed.scheme}'")
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

    async def add_document_from_url(self, url: str, title: str = "", tags: Optional[List[str]] = None, session_id: str = "global") -> Tuple[bool, str]:
        import httpx
        try:
            self._validate_url_safe(url)
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, max_redirects=5, headers={"User-Agent": "Mozilla/5.0"}) as client:
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

    def add_document_from_file(self, path: str, title: str = "", tags: Optional[List[str]] = None, session_id: str = "global") -> Tuple[bool, str]:
        # Boş uzantı ("") kaldırıldı — uzantısız dosyalar ikili olabilir ve path traversal riski taşır
        _TEXT_EXTS = {".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".html", ".css", ".js", ".ts", ".sh", ".sql", ".csv", ".xml", ".rst", ".gitignore", ".dockerignore"}
        # Hassas yol kalıpları — proje kökü dışındaki kritik dosyalara erişimi engelle
        _BLOCKED_PARTS = {".env", ".git", "sessions", "__pycache__", "logs", "proc", "etc", "sys"}
        try:
            file = Path(path).resolve()
            if not file.exists(): return False, f"✗ Dosya bulunamadı: {path}"
            if not file.is_file(): return False, f"✗ Belirtilen yol bir dosya değil: {path}"
            # Base directory sınırı: proje kökü veya sistem geçici dizini altındaki dosyalara izin ver
            # (upload endpoint geçici dosyaları /tmp/ altında oluşturur)
            _allowed_roots = (Config.BASE_DIR, Path(tempfile.gettempdir()).resolve())
            if not any(file.is_relative_to(root) for root in _allowed_roots):
                return False, f"✗ Erişim engellendi: dosya proje dizini dışında: {path}"
            # Path traversal koruması: dosyanın hassas dizinler içermediğini doğrula
            if _BLOCKED_PARTS.intersection(set(file.parts)):
                return False, f"✗ Erişim engellendi: güvenlik politikası bu yola izin vermiyor: {path}"
            if file.suffix.lower() not in _TEXT_EXTS: return False, f"✗ Desteklenmeyen dosya türü: {file.suffix}"

            content = file.read_text(encoding="utf-8", errors="replace")
            if not content.strip(): return False, f"✗ Dosya boş: {path}"
            if not title: title = file.name

            source = f"file://{file}"
            doc_id = self._add_document_sync(title, content, source=source, tags=tags or [], session_id=session_id)
            return True, f"✓ Dosya RAG deposuna eklendi: [{doc_id}] {title} ({len(content):,} karakter)"
        except Exception as exc:
            logger.error("Dosya belge ekleme hatası (%s): %s", path, exc)
            return False, f"[HATA] Dosya eklenemedi: {exc}"

    def get_index_info(self, session_id: Optional[str] = None) -> List[Dict]:
        return [
            {
                "id":      doc_id,
                "title":   meta.get("title", "?"),
                "source":  meta.get("source", ""),
                "size":    meta.get("size", 0),
                "preview": meta.get("preview", "")[:120],
                "tags":    meta.get("tags", []),
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
            return f"✗ HATA: Bu belgeye erişim yetkiniz yok (Farklı bir sohbete ait)."

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

            # 3. Index'ten ve BM25'ten sil
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

    def get_document(self, doc_id: str, session_id: str = "global") -> Tuple[bool, str]:
        """Belge ID ile tam içerik getir (İzolasyon Korumalı)."""
        if doc_id not in self._index:
            return False, f"✗ Belge bulunamadı: {doc_id}"

        meta = self._index[doc_id]
        if meta.get("session_id", "global") != session_id and session_id != "global":
            return False, f"✗ HATA: Bu belgeye erişim yetkiniz yok (Farklı bir sohbete ait)."

        doc_file = self.store_dir / f"{doc_id}.txt"
        if not doc_file.exists():
            return False, f"✗ Belge dosyası eksik: {doc_id}"
        content = doc_file.read_text(encoding="utf-8")
        self._touch_document(doc_id)
        return True, f"[{doc_id}] {meta['title']}\nKaynak: {meta.get('source', '-')}\n\n{content}"

    # ─────────────────────────────────────────────
    #  ARAMA (HİBRİT)
    # ─────────────────────────────────────────────

    def rebuild_graph_index(self, root_dir: Optional[str] = None) -> Tuple[bool, str]:
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

    def search_graph(self, query: str, top_k: int = 5) -> Tuple[bool, str]:
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
        if not results:
            return False, f"GraphRAG içinde '{query}' için ilgili modül bulunamadı."

        lines = [f"[GraphRAG: {query}]", ""]
        for item in results:
            lines.append(f"- {item['id']} (score={item['score']})")
            neighbors = item.get("neighbors") or []
            if neighbors:
                lines.append(f"  Komşular: {', '.join(neighbors)}")
            reverse_neighbors = item.get("reverse_neighbors") or []
            if reverse_neighbors:
                lines.append(f"  Ters Komşular: {', '.join(reverse_neighbors)}")
        return True, "\n".join(lines)

    def explain_dependency_path(self, source: str, target: str) -> Tuple[bool, str]:
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

    def analyze_graph_impact(self, target: str, top_k: int = 10) -> Tuple[bool, str]:
        """Bir modül veya endpoint değişiminin olası etki alanını açıklar."""
        ok, analysis = self.graph_impact_details(target, top_k=top_k)
        if not ok:
            return False, str(analysis)

        assert isinstance(analysis, dict)
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
        return True, "\n".join(lines)

    def graph_impact_details(self, target: str, top_k: int = 10) -> Tuple[bool, Dict[str, Any] | str]:
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
    ) -> Dict[str, Any]:
        """pgvector/Chroma belge katmanını bilgi grafı düğüm/kenarlarına yansıtır.

        Neo4j gibi bir katmana doğrudan yazmak yerine, önce taşınabilir bir projection
        üretir. Böylece ileride GraphRAG için `MERGE` tabanlı sync işleri kolaylaşır.
        """
        max_items = max(1, min(int(limit or 100), 1000))
        nodes: List[KnowledgeGraphNode] = []
        edges: List[KnowledgeGraphEdge] = []

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
                        "vector_backend": "pgvector" if getattr(self, "_pgvector_available", False) else self._vector_backend,
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
                    edge_kinds = sorted(self._graph_index.edge_kinds.get((source_id, target_id), {"RELATED_TO"}))
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
            "vector_backend": "pgvector" if getattr(self, "_pgvector_available", False) else self._vector_backend,
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
        vector_backend = "pgvector" if getattr(self, "_pgvector_available", False) else (
            "chromadb" if self._chroma_available and self.collection else "bm25"
        )
        vector_results: List[Dict[str, Any]] = []
        if normalized:
            if getattr(self, "_pgvector_available", False):
                vector_results = self._fetch_pgvector(normalized, top_k, session_id)
            elif self._chroma_available and self.collection:  # pragma: no cover
                vector_results = self._fetch_chroma(normalized, top_k, session_id)

        vector_candidates = [str(item.get("doc_id", "") or "") for item in vector_results if str(item.get("doc_id", "") or "")]
        projection = self.build_knowledge_graph_projection(session_id=session_id, include_code_graph=True, limit=max(20, top_k * 10))
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

    def _search_sync(self, query: str, top_k: Optional[int] = None, mode: str = "auto", session_id: str = "global") -> Tuple[bool, str]:
        if top_k is None: top_k = getattr(self.cfg, "RAG_TOP_K", self.default_top_k)

        session_docs = [k for k, v in self._index.items() if v.get("session_id", "global") == session_id]
        if mode != "graph" and not session_docs:
            return False, "⚠ Bu oturum için belge deposu boş. Belge eklemek için: TOOL:docs_add:<başlık>|<url>"

        if mode == "graph":
            return self.search_graph(query, top_k)

        if mode == "vector":
            if getattr(self, "_pgvector_available", False): return self._pgvector_search(query, top_k, session_id)
            if self._chroma_available and self.collection: return self._chroma_search(query, top_k, session_id)
            return False, "Vektör arama kullanılamıyor — pgvector/ChromaDB hazır değil."

        if mode == "bm25":
            if self._bm25_available: return self._bm25_search(query, top_k, session_id)
            return False, "BM25 kullanılamıyor — SQLite FTS5 başlatılamadı."

        if mode == "keyword": return self._keyword_search(query, top_k, session_id)

        has_vector = getattr(self, "_pgvector_available", False) or (self._chroma_available and self.collection)
        preferred_vector_backend = str(getattr(self, "_vector_backend", "") or "").strip().lower()

        # Yerel LLM + RAG birlikte çalışırken default olarak hibrid sorguyu kapatıp
        # tek motorlu akışla CPU/SQLite baskısını azalt.
        if mode == "auto" and getattr(self, "_is_local_llm_provider", False) and not getattr(self, "_local_hybrid_enabled", False):
            if has_vector:
                if getattr(self, "_pgvector_available", False):
                    return self._pgvector_search(query, top_k, session_id)
                if self._chroma_available and self.collection:  # pragma: no cover
                    return self._chroma_search(query, top_k, session_id)
            if self._bm25_available:
                return self._bm25_search(query, top_k, session_id)
            return self._keyword_search(query, top_k, session_id)

        if mode == "auto" and preferred_vector_backend == "pgvector" and getattr(self, "_pgvector_available", False):
            try:
                return self._pgvector_search(query, top_k, session_id)
            except Exception as exc:
                logger.warning("Tercih edilen pgvector araması hatası (fallback yapılıyor): %s", exc)

        if mode == "auto" and preferred_vector_backend == "chroma" and self._chroma_available and self.collection:
            try:
                return self._chroma_search(query, top_k, session_id)
            except Exception as exc:
                logger.warning("Tercih edilen Chroma araması hatası (fallback yapılıyor): %s", exc)

        if has_vector and self._bm25_available:
            try: return self._rrf_search(query, top_k, session_id)
            except Exception as exc: logger.warning("RRF arama hatası (Fallback yapılıyor): %s", exc)

        if getattr(self, "_pgvector_available", False):
            try: return self._pgvector_search(query, top_k, session_id)
            except Exception as exc: logger.warning("pgvector arama hatası (BM25'e düşülüyor): %s", exc)

        if self._chroma_available and self.collection:
            try: return self._chroma_search(query, top_k, session_id)
            except Exception as exc: logger.warning("ChromaDB arama hatası (BM25'e düşülüyor): %s", exc)

        if self._bm25_available: return self._bm25_search(query, top_k, session_id)
        return self._keyword_search(query, top_k, session_id)

    async def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        mode: str = "auto",
        session_id: str = "global",
    ) -> Tuple[bool, str]:
        tracer = _otel_trace.get_tracer(__name__)
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

    def _rrf_search(self, query: str, top_k: int, session_id: str) -> Tuple[bool, str]:
        vector_results = self._fetch_pgvector(query, top_k, session_id) if getattr(self, "_pgvector_available", False) else self._fetch_chroma(query, top_k, session_id)
        bm25_results = self._fetch_bm25(query, top_k, session_id)

        if not vector_results and not bm25_results: return self._keyword_search(query, top_k, session_id)

        k = 60
        rrf_scores, docs_map = {}, {}

        for rank, res in enumerate(vector_results):
            doc_id = res["id"]
            docs_map[doc_id] = res
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

        for rank, res in enumerate(bm25_results):
            doc_id = res["id"]
            if doc_id not in docs_map: docs_map[doc_id] = res
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

        ranked_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        final_results = []
        for doc_id, score in ranked_docs:
            doc_info = docs_map[doc_id]
            doc_info["score"] = score
            final_results.append(doc_info)

        vector_name = "pgvector" if getattr(self, "_pgvector_available", False) else "ChromaDB"
        return self._format_results_from_struct(final_results, query, source_name=f"Hibrit RRF ({vector_name} + BM25)")

    def _fetch_pgvector(self, query: str, top_k: int, session_id: str) -> list:
        if not getattr(self, "_pgvector_available", False) or not getattr(self, "pg_engine", None):
            return []
        try:
            from sqlalchemy import text

            qvec = self._format_vector_for_sql(self._pgvector_embed_texts([query])[0])
            with self.pg_engine.begin() as conn:
                rows = conn.execute(
                    text(f"""
                        SELECT doc_id, parent_id, title, source, chunk_content,
                               (embedding <=> CAST(:qvec AS vector)) AS distance
                        FROM {self._pg_table}
                        WHERE session_id = :session_id
                        ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                        LIMIT :lim
                    """),
                    {
                        "qvec": qvec,
                        "session_id": session_id,
                        "lim": max(top_k * (2 if getattr(self, "_is_local_llm_provider", False) else 3), top_k),
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

    def _pgvector_search(self, query: str, top_k: int, session_id: str) -> Tuple[bool, str]:
        results = self._fetch_pgvector(query, top_k, session_id)
        return self._format_results_from_struct(results, query, source_name="Vektör Arama (pgvector)")

    def _fetch_chroma(self, query: str, top_k: int, session_id: str) -> list:
        try: collection_size = self.collection.count()
        except Exception: collection_size = top_k * 2

        local_multiplier = max(1, int(getattr(self.cfg, "RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER", 1) or 1))
        default_multiplier = 2
        multiplier = local_multiplier if getattr(self, "_is_local_llm_provider", False) else default_multiplier
        n_results = min(top_k * multiplier, max(collection_size, 1))

        # Filtreleme ChromaDB düzeyinde Where parametresiyle yapılıyor
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where={"session_id": session_id}
        )

        ids = results.get("ids") or []
        if not ids or not ids[0]:
            return []

        documents = results.get("documents") or [[]]
        metadatas = results.get("metadatas") or [[]]
        doc_ids = ids[0]
        doc_chunks = documents[0] if documents else []
        doc_metas = metadatas[0] if metadatas else []

        found_docs, seen_parents = [], set()
        for i, chunk_content in enumerate(doc_chunks):
            raw_meta = doc_metas[i] if i < len(doc_metas) else {}
            meta = raw_meta if isinstance(raw_meta, dict) else {}
            parent_id = str(meta.get("parent_id") or (doc_ids[i] if i < len(doc_ids) else "") or "")
            if not parent_id:
                continue
            if parent_id in seen_parents and len(seen_parents) >= top_k:  # pragma: no cover
                continue
            seen_parents.add(parent_id)
            found_docs.append({
                "id": parent_id,
                "title": str(meta.get("title", "?") or "?"),
                "source": str(meta.get("source", "") or ""),
                "snippet": str(chunk_content or ""),
                "score": 1.0,
            })
            if len(found_docs) >= top_k:
                break
        return found_docs

    def _chroma_search(self, query: str, top_k: int, session_id: str) -> Tuple[bool, str]:
        results = self._fetch_chroma(query, top_k, session_id)
        return self._format_results_from_struct(results, query, source_name="Vektör Arama (ChromaDB + Chunking)")

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
            (doc_id, session_id, content)
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

    def _fetch_bm25(self, query: str, top_k: int, session_id: str) -> list:
        """Diskteki FTS5 veritabanından milisaniyelik BM25 araması yap."""
        if not self._bm25_available:
            return []

        words = [w for w in query.replace('"', '').replace("'", "").split() if w.isalnum()]
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
            results.append({
                "id": doc_id, "title": meta.get("title", "?"),
                "source": meta.get("source", ""), "snippet": snippet, "score": score
            })
        return results

    def _bm25_search(self, query: str, top_k: int, session_id: str) -> Tuple[bool, str]:
        results = self._fetch_bm25(query, top_k, session_id)
        return self._format_results_from_struct(results, query, source_name="BM25")

    def _keyword_search(self, query: str, top_k: int, session_id: str) -> Tuple[bool, str]:
        keywords = query.lower().split()
        scored = []

        for doc_id, meta in list(self._index.items()):
            if meta.get("session_id", "global") != session_id: continue

            doc_file = self.store_dir / f"{doc_id}.txt"
            try: text = doc_file.read_text(encoding="utf-8").lower()
            except FileNotFoundError: text = ""

            title_lower = meta["title"].lower()
            tags_lower = " ".join(meta.get("tags", [])).lower()

            score = sum(text.count(kw) + title_lower.count(kw) * 5 + tags_lower.count(kw) * 3 for kw in keywords)
            if score > 0: scored.append((doc_id, score))

        ranked = sorted(scored, key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for doc_id, score in ranked:
            doc_file = self.store_dir / f"{doc_id}.txt"
            try: content = doc_file.read_text(encoding="utf-8")
            except FileNotFoundError: content = ""
            meta = self._index.get(doc_id, {})
            snippet = self._extract_snippet(content, query)
            results.append({
                "id": doc_id, "title": meta.get("title", "?"),
                "source": meta.get("source", ""), "snippet": snippet, "score": score
            })

        return self._format_results_from_struct(results, query, source_name="Kelime Eşleşmesi")

    def _format_results_from_struct(self, results: list, query: str, source_name: str) -> Tuple[bool, str]:
        """Ortak sonuç biçimlendirici."""
        if not results:
            return False, f"'{query}' için belge deposunda ilgili sonuç bulunamadı."

        lines = [f"[RAG Arama: {query}] (Motor: {source_name})", ""]
        for res in results:
            lines.append(f"**[{res['id']}] {res['title']}**")
            if res['source']:
                lines.append(f"  Kaynak: {res['source']}")

            # Snippet uzunluğunu sınırla ve satır sonlarını temizle
            snippet = res['snippet'].replace("\n", " ").strip()
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
    ) -> Dict[str, Any]:
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
        removable: List[Tuple[str, Dict[str, Any]]] = []
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

    def list_documents(self, session_id: Optional[str] = None) -> str:
        docs = {k: v for k, v in self._index.items() if session_id is None or v.get("session_id", "global") == session_id}
        if not docs:
            return "Belge deposu boş veya bu oturum için belge bulunamadı."

        lines = [f"[Belge Deposu — {len(docs)} belge]", ""]
        for doc_id, meta in docs.items():
            tags = ", ".join(meta.get("tags", [])) or "-"
            size_kb = meta.get("size", 0) / 1024
            lines.append(f"  [{doc_id}] {meta['title']}")
            lines.append(f"    Kaynak: {meta.get('source', '-')} | Boyut: {size_kb:.1f} KB | Etiketler: {tags}")
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
        elif self._vector_backend == "pgvector":
            engines.append("pgvector (pasif)")
        elif self._chroma_available:
            gpu_tag = f"GPU cuda:{self._gpu_device}" if self._use_gpu else "CPU"
            engines.append(f"ChromaDB (Chunking + {gpu_tag})")
        if self._bm25_available:
            engines.append("BM25 (SQLite FTS5)")
        engines.append("Anahtar Kelime")
        if self._graph_rag_enabled:  # pragma: no cover
            graph_state = "hazır" if self._graph_ready else "pasif"
            engines.append(f"GraphRAG ({graph_state})")

        return f"RAG: {len(self._index)} belge | Motorlar: {', '.join(engines)}"
