"""Seed Sidar's local RAG store with curated project documentation.

This command is intentionally small and deterministic so operators can clear the
``Doctor/rag_readiness`` warning without hand-entering many ``belge ekle``
commands.  It indexes local text documents into the same ``DocumentStore`` used
by the CLI, which updates the file index, BM25 cache, optional vector backend,
and GraphRAG entity projection.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, cast

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INCLUDE_PATTERNS = (
    # Operator-facing documentation.
    "README.md",
    "AGENTS.md",
    "docs/SIDAR.md",
    "docs/TEKNIK_REFERANS.md",
    "docs/PROJE_RAPORU.md",
    "docs/SIDAR_v5_0_MIMARI_RAPORU.md",
    "docs/SIDAR_v5_1_MIMARI_RAPORU.md",
    # Curated architecture/runtime code entry points.  This keeps the seed
    # deterministic and compact while giving local coding agents enough context
    # for self-healing, RAG/GraphRAG routing, coverage, and startup behavior.
    "config.py",
    "pyproject.toml",
    "run_tests.sh",
    "autonomous_loop.sh",
    "agent/registry.py",
    "agent/sidar_agent.py",
    "agent/core/supervisor.py",
    "agent/swarm.py",
    "agent/roles/__init__.py",
    "core/rag.py",
    "core/ci_remediation.py",
    "scripts/auto_heal.py",
    "scripts/coverage_hotspots.py",
    "scripts/seed_rag.py",
)
TEXT_EXTENSIONS = {
    ".md",
    ".rst",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".py",
    ".sh",
}


class SeedDocumentStore(Protocol):
    """Minimal DocumentStore protocol used by the seeding workflow."""

    def add_document_from_file(
        self,
        path: str,
        title: str = "",
        tags: list[str] | None = None,
        session_id: str = "global",
    ) -> tuple[bool, str]: ...

    def delete_document(self, doc_id: str, session_id: str = "global") -> str: ...

    def get_index_info(self, session_id: str | None = None) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


class SeedError(RuntimeError):
    """Raised for invalid seeding inputs."""


class DryRunStore:
    """Store shim that prevents filesystem/vector side effects during dry runs."""

    def add_document_from_file(
        self,
        path: str,
        title: str = "",
        tags: list[str] | None = None,
        session_id: str = "global",
    ) -> tuple[bool, str]:
        return True, f"dry-run {title or path}"

    def delete_document(self, doc_id: str, session_id: str = "global") -> str:
        return f"dry-run delete {doc_id}"

    def get_index_info(self, session_id: str | None = None) -> list[dict[str, Any]]:
        return []

    def close(self) -> None:
        return None


def _resolve_rag_dir(raw: str | None) -> Path:
    value = raw or os.getenv("RAG_DIR") or "data/rag"
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


def _is_safe_text_file(path: Path, *, max_bytes: int) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return False
    return path.stat().st_size <= max_bytes


def discover_seed_files(
    patterns: list[str] | tuple[str, ...],
    *,
    base_dir: Path = BASE_DIR,
    max_bytes: int = 750_000,
) -> list[Path]:
    """Resolve repo-relative file/glob patterns to safe text files."""
    resolved: list[Path] = []
    seen: set[Path] = set()
    base = base_dir.resolve()
    for raw_pattern in patterns:
        pattern = str(raw_pattern or "").strip()
        if not pattern:
            continue
        matches = (
            sorted(base.glob(pattern)) if any(ch in pattern for ch in "*?[]") else [base / pattern]
        )
        for match in matches:
            path = match.resolve()
            if not path.is_relative_to(base):
                raise SeedError(f"Repo dışı dosya indekslenemez: {match}")
            if path in seen or not _is_safe_text_file(path, max_bytes=max_bytes):
                continue
            seen.add(path)
            resolved.append(path)
    return resolved


def _existing_doc_ids_for_source(
    store: SeedDocumentStore, source: str, session_id: str
) -> list[str]:
    return [
        str(item.get("id"))
        for item in store.get_index_info(session_id=session_id)
        if str(item.get("source", "")) == source and item.get("id")
    ]


def _content_hash_tag(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"content_sha256:{digest}"


def _extract_content_hash(entry: dict[str, Any]) -> str | None:
    tags = entry.get("tags")
    if not isinstance(tags, list):
        return None
    for tag in tags:
        if isinstance(tag, str) and tag.startswith("content_sha256:"):
            return tag
    return None


def seed_files(
    store: SeedDocumentStore,
    files: list[Path],
    *,
    session_id: str = "global",
    replace_existing: bool = True,
    dry_run: bool = False,
    base_dir: Path = BASE_DIR,
) -> dict[str, Any]:
    """Index files and return a machine-readable summary."""
    added: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    deleted: list[str] = []
    for file_path in files:
        try:
            rel_path = file_path.relative_to(base_dir.resolve()).as_posix()
        except ValueError:
            rel_path = file_path.name
        source = f"file://{file_path}"
        content_hash_tag = _content_hash_tag(file_path)
        matching_entries = [
            item
            for item in store.get_index_info(session_id=session_id)
            if str(item.get("source", "")) == source and item.get("id")
        ]
        existing_ids = [str(item.get("id")) for item in matching_entries]
        if any(_extract_content_hash(item) == content_hash_tag for item in matching_entries):
            skipped.append({"path": rel_path, "reason": "unchanged_content"})
            continue
        if existing_ids and not replace_existing:
            skipped.append({"path": rel_path, "reason": "already_indexed"})
            continue
        if dry_run:
            added.append({"path": rel_path, "status": "dry_run"})
            continue
        for doc_id in existing_ids:
            store.delete_document(doc_id, session_id=session_id)
            deleted.append(doc_id)
        ok, message = store.add_document_from_file(
            str(file_path),
            title=rel_path,
            tags=[
                "source:repo-docs",
                "brand:Sidar",
                "audience:Sidar operators",
                content_hash_tag,
            ],
            session_id=session_id,
        )
        target = added if ok else skipped
        target.append({"path": rel_path, "message": message})
    return {
        "session_id": session_id,
        "added_count": len(added),
        "skipped_count": len(skipped),
        "deleted_count": len(deleted),
        "added": added,
        "skipped": skipped,
        "deleted": deleted,
    }


def _boolish(value: Any, *, default: bool = False) -> bool:
    """Normalize config/env booleans including external provider aliases."""
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        if normalized in {"1", "true", "yes", "y", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "disabled"}:
            return False
        raise SeedError(f"Invalid boolean value for seed_rag config: {value!r}")
    return bool(value)


def _build_store(rag_dir: Path, *, initialize_vector: bool) -> SeedDocumentStore:
    # Keep CLI stdout machine-readable: config/core imports may print dotenv or
    # startup diagnostics, so route those import-time notices to stderr before
    # emitting the final JSON summary on stdout.  RAG seeding should not be
    # blocked by unrelated web/API secrets such as JWT_SECRET_KEY, so use Config
    # class defaults without constructing Config(), whose runtime validation is
    # intentionally stricter for serving the application.
    with contextlib.redirect_stdout(sys.stderr):
        from config import Config
        from core.rag import DocumentStore

    rag_dir.mkdir(parents=True, exist_ok=True)
    cfg = SimpleNamespace(
        BASE_DIR=BASE_DIR,
        RAG_DIR=rag_dir,
        RAG_TOP_K=getattr(Config, "RAG_TOP_K", 3),
        RAG_CHUNK_SIZE=getattr(Config, "RAG_CHUNK_SIZE", 1000),
        RAG_CHUNK_OVERLAP=getattr(Config, "RAG_CHUNK_OVERLAP", 200),
        USE_GPU=getattr(Config, "USE_GPU", False),
        GPU_DEVICE=getattr(Config, "GPU_DEVICE", 0),
        GPU_MIXED_PRECISION=getattr(Config, "GPU_MIXED_PRECISION", False),
        ENABLE_RAG_ENTITY_EXTRACTION=getattr(Config, "ENABLE_RAG_ENTITY_EXTRACTION", True),
        RAG_ENTITY_MAX_PER_DOC=getattr(Config, "RAG_ENTITY_MAX_PER_DOC", 24),
        RAG_VECTOR_BACKEND=getattr(Config, "RAG_VECTOR_BACKEND", "chroma"),
        RAG_LOCAL_ENABLE_HYBRID=getattr(Config, "RAG_LOCAL_ENABLE_HYBRID", False),
        ENABLE_GRAPH_RAG=getattr(Config, "ENABLE_GRAPH_RAG", True),
        GRAPH_RAG_MAX_FILES=getattr(Config, "GRAPH_RAG_MAX_FILES", 5000),
        AI_PROVIDER=getattr(Config, "AI_PROVIDER", "ollama"),
        PGVECTOR_TABLE=getattr(Config, "PGVECTOR_TABLE", "rag_embeddings"),
        PGVECTOR_EMBEDDING_DIM=getattr(Config, "PGVECTOR_EMBEDDING_DIM", 384),
        PGVECTOR_EMBEDDING_MODEL=getattr(Config, "PGVECTOR_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        DATABASE_URL=getattr(Config, "DATABASE_URL", ""),
        HF_TOKEN=getattr(Config, "HF_TOKEN", ""),
        HF_HUB_OFFLINE=_boolish(getattr(Config, "HF_HUB_OFFLINE", False)),
        HF_USE_LOCAL_CACHE_ONLY=_boolish(getattr(Config, "HF_USE_LOCAL_CACHE_ONLY", False)),
    )
    return DocumentStore(
        rag_dir,
        use_gpu=bool(getattr(cfg, "USE_GPU", False)),
        gpu_device=int(getattr(cfg, "GPU_DEVICE", 0) or 0),
        mixed_precision=bool(getattr(cfg, "GPU_MIXED_PRECISION", False)),
        cfg=cast(Any, cfg),
        initialize_vector=initialize_vector,
    )


def _wait_for_pgvector_readiness() -> None:
    """Wait briefly for PostgreSQL+pgvector readiness to reduce startup race risk."""
    with contextlib.redirect_stdout(sys.stderr):
        from config import Config

    vector_backend = str(getattr(Config, "RAG_VECTOR_BACKEND", "chroma") or "").strip().lower()
    database_url = str(getattr(Config, "DATABASE_URL", "") or "").strip()
    if vector_backend != "pgvector" or not database_url.startswith("postgresql"):
        return

    max_retries = max(1, int(os.getenv("SEED_RAG_PGVECTOR_MAX_RETRIES", "10") or "10"))
    delay_seconds = max(0.1, float(os.getenv("SEED_RAG_PGVECTOR_RETRY_DELAY_SEC", "2.0") or "2.0"))

    with contextlib.redirect_stdout(sys.stderr):
        from sqlalchemy import create_engine, text

    last_error: BaseException | None = None
    for attempt in range(1, max_retries + 1):
        try:
            engine = create_engine(database_url, future=True, pool_pre_ping=True)
            with engine.connect() as conn:
                ready = bool(
                    conn.execute(
                        text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                    ).scalar()
                )
            engine.dispose()
            if ready:
                return
        except Exception as exc:  # pragma: no cover - integration guard.
            last_error = exc
        if attempt < max_retries:
            time.sleep(delay_seconds)

    if last_error is not None:
        print(
            f"⚠️ pgvector readiness probe timed out after {max_retries} attempts "
            f"(last_error={type(last_error).__name__}: {last_error}).",
            file=sys.stderr,
        )
    else:
        print(
            f"⚠️ pgvector extension not visible after {max_retries} attempts; proceeding with normal startup.",
            file=sys.stderr,
        )


def _summary_only_payload(summary: dict[str, Any]) -> dict[str, int]:
    """Return compact seeding output for interactive Doctor auto-fix runs."""
    return {
        "added_count": int(summary.get("added_count", 0) or 0),
        "skipped_count": int(summary.get("skipped_count", 0) or 0),
        "entity_nodes_before": int(summary.get("entity_nodes_before", 0) or 0),
        "entity_nodes_after": int(summary.get("entity_nodes_after", 0) or 0),
        "entity_nodes_added": int(summary.get("entity_nodes_added", 0) or 0),
        "entity_edges_before": int(summary.get("entity_edges_before", 0) or 0),
        "entity_edges_after": int(summary.get("entity_edges_after", 0) or 0),
        "entity_edges_added": int(summary.get("entity_edges_added", 0) or 0),
    }


def _ensure_index_placeholder(rag_dir: Path) -> None:
    """Ensure doctor-facing index.json exists even in metadata-only bootstrap flows."""
    rag_dir.mkdir(parents=True, exist_ok=True)
    index_path = rag_dir / "index.json"
    if index_path.exists():
        return
    index_path.write_text("{}", encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sidar RAG deposunu repo dokümantasyonu ile hazırla",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--rag-dir",
        default=None,
        help="RAG dizini; verilmezse RAG_DIR veya data/rag kullanılır",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        help="Repo göreli dosya veya glob. Birden fazla kez verilebilir.",
    )
    parser.add_argument("--session-id", default="global", help="RAG session_id değeri")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=750_000,
        help="Tek dosya için maksimum boyut",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Aynı source daha önce indekslendiyse eski kaydı silme",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Chroma/pgvector başlatmadan index, BM25 ve GraphRAG entity projection yaz",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Dosya keşfini raporla, indeks yazma"
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Yalnız added_count/skipped_count özetini yazdır",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="--summary-only alias; interaktif başlatıcı çıktısını kısa tutar",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return run(
        rag_dir=args.rag_dir,
        include=args.include,
        session_id=str(args.session_id or "global"),
        max_bytes=max(1, int(args.max_bytes or 1)),
        append=bool(args.append),
        metadata_only=bool(args.metadata_only),
        dry_run=bool(args.dry_run),
        summary_only=bool(args.summary_only or args.quiet),
    )


def run(
    *,
    rag_dir: str | None = None,
    include: list[str] | None = None,
    session_id: str = "global",
    max_bytes: int = 750_000,
    append: bool = False,
    metadata_only: bool = False,
    dry_run: bool = False,
    summary_only: bool = False,
) -> int:
    """In-process callable entrypoint for launcher/doctor integrations."""

    def _entity_graph_counts(path: Path) -> tuple[int, int]:
        entity_graph_path = path / "entity_graph.json"
        if not entity_graph_path.exists():
            return 0, 0
        try:
            parsed = json.loads(entity_graph_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0, 0
        nodes = parsed.get("nodes", {}) if isinstance(parsed, dict) else {}
        edges = parsed.get("edges", []) if isinstance(parsed, dict) else []
        node_count = len(nodes) if isinstance(nodes, dict) else 0
        edge_count = len(edges) if isinstance(edges, list) else 0
        return node_count, edge_count

    resolved_rag_dir = _resolve_rag_dir(rag_dir)
    patterns = include or list(DEFAULT_INCLUDE_PATTERNS)
    files = discover_seed_files(patterns, max_bytes=max(1, int(max_bytes or 1)))
    if not files:
        raise SystemExit("İndekslenecek güvenli metin dosyası bulunamadı.")

    if dry_run:
        store: SeedDocumentStore = DryRunStore()
    else:
        if not metadata_only:
            _wait_for_pgvector_readiness()
        store = _build_store(resolved_rag_dir, initialize_vector=not metadata_only)
    entity_nodes_before, entity_edges_before = _entity_graph_counts(resolved_rag_dir)
    try:
        summary = seed_files(
            store,
            files,
            session_id=str(session_id or "global"),
            replace_existing=not bool(append),
            dry_run=bool(dry_run),
        )
    finally:
        store.close()
    if not dry_run:
        _ensure_index_placeholder(resolved_rag_dir)
    entity_nodes_after, entity_edges_after = _entity_graph_counts(resolved_rag_dir)
    summary["entity_nodes_before"] = entity_nodes_before
    summary["entity_nodes_after"] = entity_nodes_after
    summary["entity_nodes_added"] = max(0, entity_nodes_after - entity_nodes_before)
    summary["entity_edges_before"] = entity_edges_before
    summary["entity_edges_after"] = entity_edges_after
    summary["entity_edges_added"] = max(0, entity_edges_after - entity_edges_before)
    output = _summary_only_payload(summary) if summary_only else summary
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
