"""Installation/readiness doctor for Sidar.

The doctor intentionally performs lightweight, bounded checks so it can be used
both from `sidar doctor` and from installer subcommands without becoming another
opaque installation phase.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, unquote, urlparse

from core.config_secrets import DEFAULT_WEAK_SECRET_VALUES, is_weak_secret
from core.doctor.models import (
    DoctorCheck,
    DoctorCheckContract,
    validate_auto_fix_command,
    validate_doctor_check_contract,
)
from core.doctor.models import (
    redact_sensitive_text as _redact_sensitive_text,
)
from core.doctor.reporting import build_doctor_report, write_doctor_report
from core.rag.readiness import build_readiness_report
from core.utils.trusted_subprocess import run_trusted_command
from sidar_assets.paths import migrations_path

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = BASE_DIR / "artifacts" / "install" / "doctor.json"

__all__ = [
    "DoctorCheck",
    "DoctorCheckContract",
    "main",
    "run_doctor_report",
    "validate_auto_fix_command",
    "validate_doctor_check_contract",
]


WEAK_SECRET_VALUES = set(DEFAULT_WEAK_SECRET_VALUES)


def _run_command(cmd: list[str], *, timeout: int = 20) -> tuple[int, str]:
    try:
        proc = run_trusted_command(
            cmd,
            cwd=BASE_DIR,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return 124, f"timeout after {timeout}s\n{output}".strip()


def _status_from_bool(ok: bool, warn: bool = False) -> str:
    if ok:
        return "pass"
    return "warn" if warn else "fail"


def _is_weak_secret(value: str | None) -> bool:
    return is_weak_secret(value, known_weak_values=WEAK_SECRET_VALUES)


def check_uv() -> DoctorCheck:
    uv_path = shutil.which("uv")
    if not uv_path:
        return DoctorCheck("uv", "fail", "uv executable not found on PATH")

    version_rc, version_out = _run_command([uv_path, "--version"])
    lock_rc, lock_out = _run_command([uv_path, "lock", "--check"], timeout=60)
    status = "pass" if version_rc == 0 and lock_rc == 0 else "fail"
    return DoctorCheck(
        "uv",
        status,
        "uv and uv.lock are ready" if status == "pass" else "uv lock validation failed",
        {"path": uv_path, "version": version_out, "lock_check": lock_out},
    )


def check_prometheus_runtime() -> DoctorCheck:
    """Verify Prometheus runtime dependency for /metrics integrations."""
    prometheus_available = importlib.util.find_spec("prometheus_client") is not None
    details = {
        "required_by": [
            "web/routes/metrics.py",
            "core/judge.py",
            "managers/system_health.py",
        ],
        "install_commands": [
            "uv sync --all-extras",
            "uv sync --extra telemetry",
        ],
    }
    if prometheus_available:
        return DoctorCheck(
            "prometheus_runtime",
            "pass",
            "prometheus-client is installed; /metrics and telemetry exporters can run.",
            details,
        )
    return DoctorCheck(
        "prometheus_runtime",
        "warn",
        "prometheus-client is not installed; /metrics endpoints may degrade to limited output.",
        details,
    )


def _postgres_dsn_from_components(*, host: str | None = None) -> str:
    user = os.getenv("POSTGRES_USER", "sidar").strip() or "sidar"
    password = os.getenv("POSTGRES_PASSWORD", "sidar")
    resolved_host = (
        host if host is not None else os.getenv("POSTGRES_HOST") or "127.0.0.1"
    ).strip() or "127.0.0.1"
    port = os.getenv("POSTGRES_PORT", "5432").strip() or "5432"
    database = os.getenv("POSTGRES_DB", "sidar").strip() or "sidar"
    return (
        f"postgresql+asyncpg://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{resolved_host}:{port}/{quote(database, safe='')}"
    )


def _resolved_database_urls() -> tuple[str, str, bool, bool]:
    """Return effective database URLs and whether each one was explicit.

    Sidar intentionally allows DATABASE_URL and SIDAR_CONTAINER_DATABASE_URL to be
    absent from dotenv files. In that case config.py derives both DSNs from the
    normalized POSTGRES_* parts, which avoids password drift between local and
    Docker startup paths.
    """
    explicit_database_url = os.getenv("DATABASE_URL", "").strip()
    explicit_container_url = os.getenv("SIDAR_CONTAINER_DATABASE_URL", "").strip()
    postgres_password_set = bool(os.getenv("POSTGRES_PASSWORD", "").strip())
    database_url = explicit_database_url or (
        _postgres_dsn_from_components() if postgres_password_set else ""
    )
    container_url = explicit_container_url or (
        _postgres_dsn_from_components(host=os.getenv("POSTGRES_CONTAINER_HOST", "postgres"))
        if postgres_password_set
        else ""
    )
    return database_url, container_url, bool(explicit_database_url), bool(explicit_container_url)


def _normalize_postgres_dsn(database_url: str) -> str:
    return str(database_url or "").replace("postgresql+asyncpg://", "postgresql://", 1)


def _parse_url(database_url: str) -> tuple[Any, str]:
    """Parse a URL without allowing malformed DSNs to abort Doctor reporting."""
    if not database_url:
        return None, ""
    try:
        return urlparse(database_url), ""
    except ValueError as exc:
        return None, str(exc)


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _parse_env_file_values(path: Path) -> dict[str, str]:
    """Parse simple dotenv assignments for source attribution without exposing secrets."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _dotenv_source_report(keys: tuple[str, ...]) -> dict[str, Any]:
    """Return best-effort source files for effective env values loaded by config.py."""
    try:
        from config import get_dotenv_load_report
    except Exception:
        return {"sources": {}, "definitions": {key: [] for key in keys}}

    sources: dict[str, dict[str, str]] = {}
    definitions: dict[str, list[dict[str, str]]] = {key: [] for key in keys}
    for event in get_dotenv_load_report():
        if not event.get("loaded") or not event.get("path"):
            continue
        path = Path(str(event["path"]))
        values = _parse_env_file_values(path)
        for key in keys:
            if key not in values:
                continue
            source = {
                "label": str(event.get("label", "")),
                "path": str(path),
                "override": str(bool(event.get("override"))),
            }
            definitions[key].append(source)
            if values[key] == os.getenv(key, "") or bool(event.get("override")):
                sources[key] = source
    return {"sources": sources, "definitions": definitions}


def check_database_env() -> DoctorCheck:
    """Real implementation lives in core.doctor.checks.database (thin pass-through)."""
    from core.doctor.checks.database import check_database_env as _impl

    return _impl()


def _run_coro_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def _target() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            result["error"] = exc

    thread = threading.Thread(target=_target, name="sidar-doctor-async-probe", daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


async def _probe_postgres_connectivity(
    database_url: str,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    import asyncpg

    conn = await asyncio.wait_for(
        asyncpg.connect(dsn=_normalize_postgres_dsn(database_url)),
        timeout=timeout_seconds,
    )
    try:
        one = await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout=timeout_seconds)
        vector_installed = await asyncio.wait_for(
            conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"),
            timeout=timeout_seconds,
        )
        return {"select_1": one == 1, "pgvector_extension_installed": bool(vector_installed)}
    finally:
        await conn.close()


def check_database_connectivity() -> DoctorCheck:
    """Real implementation lives in core.doctor.checks.database (thin pass-through)."""
    from core.doctor.checks.database import check_database_connectivity as _impl

    return _impl()


def check_pgvector_ready(
    database_connectivity: DoctorCheck | None = None,
) -> DoctorCheck:
    """Real implementation lives in core.doctor.checks.database (thin pass-through)."""
    from core.doctor.checks.database import check_pgvector_ready as _impl

    return _impl(database_connectivity=database_connectivity)


def _rag_readiness_state() -> dict[str, Any]:
    vector_backend = os.getenv("RAG_VECTOR_BACKEND", "chroma").strip().lower() or "chroma"
    graph_enabled = _get_bool_env("ENABLE_GRAPH_RAG", True)
    rag_dir = Path(os.getenv("RAG_DIR", "data/rag"))
    if not rag_dir.is_absolute():
        rag_dir = BASE_DIR / rag_dir

    index_path = rag_dir / "index.json"
    entity_graph_path = rag_dir / "entity_graph.json"
    index_exists = index_path.exists()
    entity_graph_exists = entity_graph_path.exists()
    index = _load_json_object(index_path)
    entity_graph = _load_json_object(entity_graph_path)
    entity_nodes = entity_graph.get("nodes", {}) if isinstance(entity_graph, dict) else {}
    entity_edges = entity_graph.get("edges", []) if isinstance(entity_graph, dict) else []
    document_count = len(index)
    entity_node_count = len(entity_nodes) if isinstance(entity_nodes, dict) else 0
    entity_edge_count = len(entity_edges) if isinstance(entity_edges, list) else 0

    details: dict[str, Any] = {
        "vector_backend": vector_backend,
        "graph_rag_enabled": graph_enabled,
        "rag_dir": str(rag_dir),
        "index_path": str(index_path),
        "index_exists": index_exists,
        "entity_graph_path": str(entity_graph_path),
        "entity_graph_exists": entity_graph_exists,
        "document_count": document_count,
        "entity_node_count": entity_node_count,
        "entity_edge_count": entity_edge_count,
        "bm25_fallback": "SQLite FTS5",
    }
    if vector_backend == "pgvector":
        details["rag_backend_probe_path"] = "pgvector_database_env"
        details["rag_backend_smoke_scope"] = "pgvector + database_env parity + BM25 fallback"
    elif vector_backend in {"chroma", "chromadb"}:
        details["rag_backend_probe_path"] = "chromadb_local_index"
        details["rag_backend_smoke_scope"] = "ChromaDB/local index + BM25 fallback"
    else:
        details["rag_backend_probe_path"] = "bm25_keyword_fallback"
        details["rag_backend_smoke_scope"] = "BM25/keyword fallback only"

    blockers: list[str] = []
    warnings: list[str] = []
    if vector_backend == "pgvector":
        database_url, _, _, _ = _resolved_database_urls()
        postgres_password = os.getenv("POSTGRES_PASSWORD", "").strip()
        parsed_database_password: str | None = None
        parsed_database_url, _ = _parse_url(database_url)
        if parsed_database_url:
            parsed_database_password = unquote(str(parsed_database_url.password or ""))
        password_matches_database_url = (
            bool(postgres_password) and parsed_database_password == postgres_password
        )
        database_env_ok = bool(database_url) and password_matches_database_url
        details["database_env_status"] = "pass" if database_env_ok else "fail"
        if not database_env_ok:
            blockers.append(
                "pgvector backend is configured but database environment parity failed; "
                "semantic RAG is blocked until database_env is fixed"
            )
            details["blocked_by"] = "database_env"
            details["database_env_message"] = (
                "DATABASE_URL and POSTGRES_PASSWORD must both be set and share the same password"
            )
            details["database_env_auto_fix"] = (
                "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
            )
    details.update(
        build_readiness_report(
            rag_dir=rag_dir,
            document_count=document_count,
            index_exists=index_exists,
            database_env_status=str(details.get("database_env_status", "pass")),
        )
    )
    if not graph_enabled:
        warnings.append("GraphRAG is disabled by ENABLE_GRAPH_RAG=false")
    if document_count == 0:
        if not index_exists:
            warnings.append(
                "RAG index file is missing at data/rag/index.json; run "
                "`uv run python -m scripts.seed_rag` to create the local seed index or add "
                'external sources with `uv run python cli.py -c "belge ekle <url>"`; '
                "searches will rely on code graph/keyword/BM25 only until then"
            )
        else:
            warnings.append(
                "RAG has no indexed documents yet; run `uv run python -m scripts.seed_rag` "
                'or add external sources with `uv run python cli.py -c "belge ekle <url>"`; '
                "searches will rely on code graph/keyword/BM25 only until then"
            )
    entity_memory_empty = entity_node_count == 0 and graph_enabled
    if entity_memory_empty:
        warnings.append(
            "GraphRAG entity memory is empty; documents are indexed but entity "
            "extraction/projection has not populated relational memory yet"
        )

    return {
        "details": details,
        "blockers": blockers,
        "warnings": warnings,
        "document_count": document_count,
        "entity_memory_empty": entity_memory_empty,
    }


def _ensure_rag_index_placeholder(rag_dir: Path) -> Path:
    """Create an empty doctor-facing RAG index placeholder when missing."""
    rag_dir.mkdir(parents=True, exist_ok=True)
    index_path = rag_dir / "index.json"
    if not index_path.exists():
        index_path.write_text("{}", encoding="utf-8")
    return index_path


def _query_entity_graph_counts_from_store(rag_dir: Path) -> dict[str, Any]:
    """Read GraphRAG entity counts from DocumentStore for post-fix verification."""
    try:
        from types import SimpleNamespace

        from config import Config
        from core.rag import DocumentStore

        cfg = SimpleNamespace(
            BASE_DIR=BASE_DIR,
            RAG_DIR=rag_dir,
            ENABLE_GRAPH_RAG=getattr(Config, "ENABLE_GRAPH_RAG", True),
            RAG_VECTOR_BACKEND=getattr(Config, "RAG_VECTOR_BACKEND", "chroma"),
            RAG_LOCAL_ENABLE_HYBRID=getattr(Config, "RAG_LOCAL_ENABLE_HYBRID", False),
            AI_PROVIDER=getattr(Config, "AI_PROVIDER", "ollama"),
            PGVECTOR_TABLE=getattr(Config, "PGVECTOR_TABLE", "rag_embeddings"),
            PGVECTOR_EMBEDDING_DIM=getattr(Config, "PGVECTOR_EMBEDDING_DIM", 384),
            PGVECTOR_EMBEDDING_MODEL=getattr(
                Config, "PGVECTOR_EMBEDDING_MODEL", "all-MiniLM-L6-v2"
            ),
            DATABASE_URL=getattr(Config, "DATABASE_URL", ""),
        )
        store = DocumentStore(rag_dir, cfg=cast(Any, cfg), initialize_vector=False)
        graph = store._ensure_entity_graph()  # noqa: SLF001 - doctor verification probe.
        nodes = graph.get("nodes", {})
        edges = graph.get("edges", [])
        return {
            "ok": True,
            "entity_node_count": len(nodes) if isinstance(nodes, dict) else 0,
            "entity_edge_count": len(edges) if isinstance(edges, list) else 0,
            "source": "document_store",
        }
    except Exception as exc:  # pragma: no cover - diagnostic fallback.
        return {"ok": False, "error": str(exc), "source": "document_store"}


def check_rag_index_ready() -> DoctorCheck:
    state = _rag_readiness_state()
    details = state["details"]
    blockers = state["blockers"]
    warnings = state["warnings"]
    document_count = int(state["document_count"])
    entity_memory_empty = bool(state["entity_memory_empty"])
    rag_dir = Path(str(details.get("rag_dir", BASE_DIR / "data/rag")))
    if not rag_dir.is_absolute():
        rag_dir = BASE_DIR / rag_dir
    index_path = rag_dir / "index.json"
    index_missing_before_fix = not index_path.exists()
    if index_missing_before_fix:
        _ensure_rag_index_placeholder(rag_dir)
        details["index_auto_placeholder_created"] = True
        details["index_exists"] = True
        details["index_path"] = str(index_path)
    else:
        details["index_auto_placeholder_created"] = False
    index_warnings = [w for w in warnings if "RAG index" in w or "indexed documents" in w]
    if index_missing_before_fix:
        index_warnings = [w for w in index_warnings if "RAG index file is missing" not in w]
        warnings = [w for w in warnings if "RAG index file is missing" not in w]

    if blockers:
        auto_fix_steps = [details["database_env_auto_fix"]]
        if document_count == 0:
            auto_fix_steps.append("uv run python -m scripts.seed_rag")
        details["auto_fix"] = auto_fix_steps[0]
        details["auto_fix_steps"] = auto_fix_steps
        details["recommended_commands"] = [
            *auto_fix_steps,
            'uv run python cli.py -c "belge ekle <url>"',
            "uv run python -m core.doctor artifacts/install/doctor.json",
            "docker compose ps postgres",
        ]
        status = "warn"
        message = "; ".join(blockers + index_warnings)
    elif document_count == 0:
        details["auto_fix"] = [
            "uv run python -m scripts.seed_rag",
            'uv run python cli.py -c "belge ekle <url>"',
        ]
        details["recommended_commands"] = [
            "uv run python -m scripts.seed_rag",
            'uv run python cli.py -c "belge ekle <url>"',
            "uv run python -m core.doctor artifacts/install/doctor.json",
        ]
        details["advisory_only"] = True
        status = "warn"
        message = (
            "; ".join(index_warnings)
            if index_warnings
            else "RAG index is empty; this is optional and can be seeded later"
        )
    else:
        if entity_memory_empty:
            details["graphrag_entity_memory_warning"] = True
        details["auto_fix"] = ""
        details["recommended_commands"] = [
            "uv run python -m core.doctor artifacts/install/doctor.json"
        ]
        status = "pass"
        message = "RAG index readiness looks healthy"
    return DoctorCheck("rag_index_ready", status, message, details)


def check_graphrag_entity_memory_ready() -> DoctorCheck:
    state = _rag_readiness_state()
    details = state["details"]
    warnings = state["warnings"]
    entity_memory_empty = bool(state["entity_memory_empty"])
    graph_enabled = bool(details.get("graph_rag_enabled"))
    entity_warnings = [w for w in warnings if "GraphRAG entity memory is empty" in w]
    rag_dir = Path(str(details.get("rag_dir", BASE_DIR / "data/rag")))
    if not rag_dir.is_absolute():
        rag_dir = BASE_DIR / rag_dir
    store_counts = _query_entity_graph_counts_from_store(rag_dir)
    details["entity_store_probe"] = store_counts
    if store_counts.get("ok"):
        details["entity_node_count_store"] = int(store_counts.get("entity_node_count", 0))
        details["entity_edge_count_store"] = int(store_counts.get("entity_edge_count", 0))
        if details["entity_node_count_store"] != int(details.get("entity_node_count", 0)):
            details["entity_count_mismatch"] = True
            details["entity_count_mismatch_note"] = (
                "entity_node_count (doctor state) and store probe node count differ; verify "
                "GraphRAG projection persistence"
            )
        entity_memory_empty = details["entity_node_count_store"] == 0
        if entity_memory_empty:
            entity_warnings = [
                "GraphRAG entity memory is empty after store probe; run metadata seed and verify "
                "real entity node count"
            ]

    if not graph_enabled:
        details["auto_fix"] = ""
        details["recommended_commands"] = [
            "uv run python -m core.doctor artifacts/install/doctor.json"
        ]
        return DoctorCheck(
            "graphrag_entity_memory_ready", "warn", "GraphRAG is disabled by configuration", details
        )

    if entity_memory_empty:
        details["auto_fix"] = "uv run python -m scripts.seed_rag --metadata-only"
        details["advisory_only"] = True
        details["recommended_commands"] = [
            "uv run python -m scripts.seed_rag --metadata-only",
            "uv run python -m core.doctor artifacts/install/doctor.json",
        ]
        return DoctorCheck(
            "graphrag_entity_memory_ready", "warn", "; ".join(entity_warnings), details
        )

    details["auto_fix"] = ""
    details["recommended_commands"] = ["uv run python -m core.doctor artifacts/install/doctor.json"]
    return DoctorCheck(
        "graphrag_entity_memory_ready", "pass", "GraphRAG entity memory looks healthy", details
    )


def check_rag_readiness() -> DoctorCheck:
    """Backward-compatible aggregate check; prefer split checks in launcher."""
    state = _rag_readiness_state()
    base_details = state.get("details", {}) if isinstance(state, dict) else {}
    vector_backend = str(base_details.get("vector_backend", "") or "").lower()
    database_url, _, _, _ = _resolved_database_urls()
    postgres_password = os.getenv("POSTGRES_PASSWORD", "").strip()
    parsed_database_url, _ = _parse_url(database_url)
    database_password = (
        unquote(str(parsed_database_url.password or "")) if parsed_database_url else ""
    )
    mismatch_block = (
        vector_backend == "pgvector"
        and bool(database_url)
        and bool(postgres_password)
        and database_password != postgres_password
    )
    index_check = check_rag_index_ready()
    graph_check = check_graphrag_entity_memory_ready()
    status = "pass"
    if "fail" in {index_check.status, graph_check.status}:
        status = "fail"
    elif "warn" in {index_check.status, graph_check.status}:
        status = "warn"
    details = {
        "rag_index_ready_status": index_check.status,
        "graphrag_entity_memory_ready_status": graph_check.status,
        "document_count": int(
            base_details.get("document_count", index_check.details.get("document_count", 0))
        ),
        "index_exists": bool(
            base_details.get("index_exists", index_check.details.get("index_exists", False))
        ),
        "blocked_by": (
            "database_env"
            if mismatch_block
            else base_details.get("blocked_by", index_check.details.get("blocked_by"))
        ),
        "auto_fix": index_check.details.get("auto_fix", ""),
        "recommended_commands": list(
            dict.fromkeys(
                [
                    *index_check.details.get("recommended_commands", []),
                    *graph_check.details.get("recommended_commands", []),
                ]
            )
        ),
    }
    if details.get("blocked_by") == "database_env":
        sync_cmd = "uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
        seed_cmd = "uv run python -m scripts.seed_rag"
        auto_fix_steps = [sync_cmd]
        if int(details.get("document_count", 0)) == 0:
            auto_fix_steps.append(seed_cmd)
        details["database_env_status"] = "fail"
        details["database_env_auto_fix"] = sync_cmd
        details["auto_fix"] = sync_cmd
        details["auto_fix_steps"] = auto_fix_steps
        details["follow_up_commands"] = [seed_cmd]
        details["recommended_commands"] = list(
            dict.fromkeys([*auto_fix_steps, *details.get("recommended_commands", [])])
        )
        if not details.get("index_exists", False):
            message = "RAG index file is missing; blocked until database_env is fixed"
        else:
            message = (
                "rag_index_ready=warn; graphrag_entity_memory_ready="
                f"{graph_check.status}; blocked until database_env is fixed"
            )
    elif details.get("document_count", 0) == 0:
        auto_fix_value = details.get("auto_fix")
        if isinstance(auto_fix_value, list) and auto_fix_value:
            details["auto_fix"] = auto_fix_value[0]
        # Preserve the split-check contract on the backward-compatible aggregate:
        # an empty, otherwise unblocked index means "not seeded yet", not a
        # production defect. Consumers that still call check_rag_readiness() can
        # therefore distinguish this advisory warning from a blocked backend.
        details["advisory_only"] = True
        if not details.get("index_exists", False):
            message = "RAG index file is missing; no indexed documents yet; entity memory is empty"
        else:
            message = (
                "RAG has no indexed documents; no indexed documents yet; entity memory is empty"
            )
    else:
        message = (
            f"rag_index_ready={index_check.status}; "
            f"graphrag_entity_memory_ready={graph_check.status}"
        )
    return DoctorCheck("rag_readiness", status, message, details)


def check_environment_profile() -> DoctorCheck:
    """Validate that the selected SIDAR_ENV profile has an isolated dotenv file.

    The real implementation lives in ``core.doctor.checks.security``; this
    thin pass-through keeps ``core.doctor.check_environment_profile`` valid as
    a monkeypatch target for ``run_doctor_report()`` (deferred import to avoid
    a circular import with ``core.doctor.checks.security``, which itself
    imports ``BASE_DIR``/``DoctorCheck`` from this module at import time).
    """
    from core.doctor.checks.security import check_environment_profile as _impl

    return _impl()


def _docker_image_exists_local(image: str) -> bool:
    """Best-effort local Docker image presence check for doctor hints."""
    safe_image = str(image or "").strip()
    if not safe_image:
        return False
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    try:
        result = run_trusted_command(  # Executable path and argument list are controlled.
            [docker_bin, "image", "inspect", safe_image],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(BASE_DIR),
        )
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def check_gpu_memory_config() -> DoctorCheck:
    """Report effective local model and VRAM budget settings."""
    from config import Config
    from core.config_gpu_detect import normalize_gpu_memory_fractions

    # Config.GPU_INFO/GPU_COUNT/etc. are lazy-loaded on first Config() instantiation
    # (see Config._ensure_hardware_info_loaded). Reading the class attribute below
    # before anything else in this process has constructed a Config() leaves
    # GPU_INFO frozen at its "Devre Dışı / CPU Modu" placeholder even when USE_GPU
    # is true, producing a self-contradictory report. Force the hardware probe so
    # both fields agree; suppress errors so a broken .env doesn't turn this
    # diagnostic check itself into a crash.
    with contextlib.suppress(Exception):
        Config._ensure_hardware_info_loaded()

    provider = str(getattr(Config, "AI_PROVIDER", "ollama") or "ollama").strip().lower()
    coding_model = str(getattr(Config, "CODING_MODEL", "") or "").strip()
    access_level = str(getattr(Config, "ACCESS_LEVEL", "") or "").strip().lower()
    use_gpu = bool(getattr(Config, "USE_GPU", False))
    gpu_info = str(getattr(Config, "GPU_INFO", "") or "").strip()
    docker_image = str(getattr(Config, "DOCKER_IMAGE", "") or "").strip()
    llm_fraction = float(getattr(Config, "LLM_GPU_MEMORY_FRACTION", 0.0) or 0.0)
    rag_fraction = float(getattr(Config, "RAG_GPU_MEMORY_FRACTION", 0.0) or 0.0)
    legacy_fraction = float(getattr(Config, "GPU_MEMORY_FRACTION", 0.0) or 0.0)
    budget = normalize_gpu_memory_fractions(llm_fraction, rag_fraction)
    total = llm_fraction + rag_fraction
    details: dict[str, Any] = {
        "ai_provider": provider,
        "coding_model": coding_model,
        "access_level": access_level,
        "use_gpu": use_gpu,
        "gpu_info": gpu_info,
        "docker_image": docker_image,
        "gpu_memory_fraction": legacy_fraction,
        "llm_gpu_memory_fraction": llm_fraction,
        "rag_gpu_memory_fraction": rag_fraction,
        "total_gpu_memory_fraction": round(total, 4),
        "effective_gpu_memory_fraction": budget["gpu"],
        "effective_llm_gpu_memory_fraction": budget["llm"],
        "effective_rag_gpu_memory_fraction": budget["rag"],
        "normalized": budget["normalized"],
        "recommended_commands": [
            "uv run python -m scripts.bootstrap_env --profile development",
            "uv run python -m core.doctor artifacts/install/doctor.json",
        ],
    }

    warnings: list[str] = []
    if budget["normalized"]:
        warnings.append(
            "LLM/RAG VRAM fractions exceed the safe 80% target or are non-positive; Sidar will "
            "normalize the effective GPU budget to 80%"
        )
    if provider == "ollama" and coding_model != "qwen2.5-coder:7b":
        warnings.append(
            "local Ollama coding model differs from the Sidar standard qwen2.5-coder:7b"
        )
    if not use_gpu and (docker_image and "gpu" in docker_image.lower()):
        warnings.append(
            "Docker image suggests GPU profile but runtime is CPU mode; verify NVIDIA Container "
            "Toolkit, CUDA visibility, and USE_GPU settings"
        )
    if access_level != "sandbox":
        warnings.append("CLI access level is not sandbox; verify this is intentional")
    status = "warn" if warnings else "pass"
    message = "; ".join(warnings or ["Local model and VRAM configuration look safe"])
    return DoctorCheck("gpu_memory_config", status, message, details)


def check_docker_test_image() -> DoctorCheck:
    """Report Docker test-image readiness independently from GPU configuration."""
    from config import Config

    docker_test_image = str(getattr(Config, "DOCKER_TEST_IMAGE", "") or "").strip()
    auto_build = os.getenv("AUTO_BUILD_DOCKER_TEST_IMAGE", "0") == "1"
    production_readiness = os.getenv("SIDAR_PRODUCTION_READINESS", "0") == "1"
    image_exists = _docker_image_exists_local(docker_test_image)
    details: dict[str, Any] = {
        "docker_test_image": docker_test_image,
        "image_exists": image_exists,
        "auto_build_docker_test_image": auto_build,
        "production_readiness": production_readiness,
        "recommended_commands": [],
    }

    if docker_test_image == "python:3.11-slim":
        message = (
            "DOCKER_TEST_IMAGE points to python:3.11-slim; Docker tests may miss Sidar test "
            "dependencies"
        )
        details["docker_image_container_note"] = (
            "Docker image is the reusable template, container is a running instance. Having a "
            "running sidar-* container does not prove sidar:latest exists locally."
        )
        details.setdefault("recommended_commands", []).extend(
            [
                "docker image ls | rg 'sidar|python'",
                "docker build -t sidar:latest .",
                "echo 'DOCKER_TEST_IMAGE=sidar:latest' >> .env.development",
            ]
        )
        return DoctorCheck("docker_test_image", "warn", message, details)
    if image_exists:
        return DoctorCheck("docker_test_image", "pass", "Docker test image is available", details)
    details["recommended_commands"] = [
        "AUTO_BUILD_DOCKER_TEST_IMAGE=1 DOCKER_TEST_IMAGE=sidar:latest bash run_tests.sh"
    ]
    if auto_build:
        return DoctorCheck(
            "docker_test_image",
            "pass",
            "Docker test image is missing; enabled auto-build will create it before tests",
            details,
        )
    if production_readiness:
        return DoctorCheck(
            "docker_test_image",
            "fail",
            "Docker test image is missing for production-readiness and auto-build is disabled",
            details,
        )
    return DoctorCheck(
        "docker_test_image",
        "pass",
        "Docker test image is not built yet; make dev-full enables its automatic build",
        {**details, "hint_level": "info"},
    )


def _parse_migration_revisions() -> tuple[list[str], list[str]]:
    revisions: list[str] = []
    down_revisions: list[str] = []
    versions_dir = migrations_path() / "versions"
    for file_path in sorted(versions_dir.glob("*.py")):
        text = file_path.read_text(encoding="utf-8")
        rev_match = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        down_match = re.search(r"^down_revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        if rev_match:
            revisions.append(rev_match.group(1))
        if down_match:
            down_revisions.append(down_match.group(1))
    return revisions, down_revisions


def check_migrations() -> DoctorCheck:
    revisions, down_revisions = _parse_migration_revisions()
    heads = sorted(set(revisions) - set(down_revisions))
    if not revisions:
        return DoctorCheck("migrations", "fail", "no Alembic migration revisions found")

    rc, output = _run_command([sys.executable, "-m", "alembic", "heads"], timeout=30)
    status = "pass" if rc == 0 and all(head in output for head in heads) else "warn"
    return DoctorCheck(
        "migrations",
        status,
        "Alembic heads are discoverable"
        if status == "pass"
        else "Alembic head command could not be fully verified",
        {"expected_heads": heads, "revision_count": len(revisions), "alembic_heads_output": output},
    )


def check_agent_catalog() -> DoctorCheck:
    required_roles = {"coder", "researcher", "reviewer", "poyraz", "qa", "coverage"}
    try:
        from agent.registry import AgentCatalog

        registered = {spec.role_name for spec in AgentCatalog.list_all()}
    except Exception as exc:  # pragma: no cover - defensive runtime path
        return DoctorCheck("agent_catalog", "fail", f"AgentCatalog failed to load: {exc}")

    missing = sorted(required_roles - registered)
    return DoctorCheck(
        "agent_catalog",
        _status_from_bool(not missing),
        "all built-in roles are registered"
        if not missing
        else f"missing roles: {', '.join(missing)}",
        {"required_roles": sorted(required_roles), "registered_roles": sorted(registered)},
    )


def check_supervisor_routing() -> DoctorCheck:
    try:
        from agent.core.supervisor import SupervisorAgent

        samples = {
            "research": "web kaynak araştır",
            "review": "pull request review incele",
            "marketing": "seo kampanya metni üret",
            "coverage": "pytest coverage eksik test yaz",
            "code": "dosyaya fonksiyon ekle",
        }
        observed = {
            expected: SupervisorAgent._intent(prompt) for expected, prompt in samples.items()
        }
    except Exception as exc:  # pragma: no cover - defensive runtime path
        return DoctorCheck("supervisor_routing", "fail", f"Supervisor routing check failed: {exc}")

    mismatches = {expected: actual for expected, actual in observed.items() if expected != actual}
    return DoctorCheck(
        "supervisor_routing",
        _status_from_bool(not mismatches),
        "Supervisor intent routing smoke checks passed"
        if not mismatches
        else f"routing mismatches: {mismatches}",
        {"observed": observed},
    )


def _iter_effective_routes(routes: Any) -> list[Any]:
    """Recursively flatten a FastAPI/Starlette route tree.

    FastAPI >=0.137 defers ``include_router`` by wrapping the included router in
    an internal ``_IncludedRouter`` node (exposing the original router via
    ``original_router``) instead of eagerly copying its routes onto
    ``app.routes``. Older FastAPI/Starlette shapes (plain ``Mount``/``APIRouter``
    with a ``.routes`` list) are walked the same way, so route discovery keeps
    working regardless of which FastAPI version is installed.
    """
    flattened: list[Any] = []
    for route in routes or []:
        nested_routes = getattr(getattr(route, "original_router", None), "routes", None)
        if nested_routes is None:
            nested_routes = getattr(route, "routes", None)
        if nested_routes is not None:
            flattened.extend(_iter_effective_routes(nested_routes))
        else:
            flattened.append(route)
    return flattened


def check_websocket_routes() -> DoctorCheck:
    try:
        from web_server import app

        websocket_paths = sorted(
            getattr(route, "path", "")
            for route in _iter_effective_routes(app.routes)
            if "WebSocket" in route.__class__.__name__
        )
    except Exception as exc:  # pragma: no cover - defensive runtime path
        required = {"/ws/chat", "/ws/voice"}
        static_paths = sorted(
            path
            for path in required
            if any(
                f'@router.websocket("{path}")' in (BASE_DIR / rel).read_text(encoding="utf-8")
                for rel in ("web/routes/ws_chat.py", "web/routes/ws_voice.py")
            )
        )
        missing_static = sorted(required - set(static_paths))
        return DoctorCheck(
            "websocket_routes",
            "warn" if not missing_static else "fail",
            "web_server import failed, but websocket decorators were found statically"
            if not missing_static
            else f"web_server import failed and static routes are missing: {missing_static}",
            {
                "required": sorted(required),
                "websocket_paths": static_paths,
                "import_error": str(exc),
            },
        )

    required = {"/ws/chat", "/ws/voice"}
    missing = sorted(required - set(websocket_paths))
    return DoctorCheck(
        "websocket_routes",
        _status_from_bool(not missing),
        "required websocket routes are mounted"
        if not missing
        else f"missing websocket routes: {missing}",
        {"required": sorted(required), "websocket_paths": websocket_paths},
    )


def check_gpu() -> DoctorCheck:
    details: dict[str, Any] = {"detected": False, "run_gpu_stress": False}
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        rc, output = _run_command(
            [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"], timeout=10
        )
        if rc == 0 and output:
            details.update(
                {"detected": True, "source": "nvidia-smi", "devices": output.splitlines()}
            )
    if not details["detected"]:
        try:
            import torch

            if torch.cuda.is_available():
                details.update(
                    {
                        "detected": True,
                        "source": "torch",
                        "devices": [
                            torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
                        ],
                    }
                )
        except Exception as exc:
            details["torch_error"] = str(exc)

    details["run_gpu_stress"] = bool(details["detected"])
    return DoctorCheck(
        "gpu",
        "pass" if details["detected"] else "warn",
        "GPU detected; RUN_GPU_STRESS should be enabled"
        if details["detected"]
        else "GPU not detected; GPU stress tests remain opt-in",
        details,
    )


def _ollama_base_url() -> str:
    raw = os.getenv("OLLAMA_URL", "http://localhost:11434/api").rstrip("/")
    return raw if raw.endswith("/api") else f"{raw}/api"


def check_model(coding_model: str | None = None, *, smoke: bool = True) -> DoctorCheck:
    model = (coding_model or os.getenv("CODING_MODEL") or "qwen2.5-coder:7b").strip()
    model_prefix = model.split(":", 1)[0]
    base = _ollama_base_url()
    details: dict[str, Any] = {
        "model": model,
        "ollama_url": base,
        "present": False,
        "json_smoke": False,
    }
    try:
        import httpx

        with httpx.Client(timeout=10) as client:
            tags = client.get(f"{base}/tags")
            tags.raise_for_status()
            models = tags.json().get("models", [])
            names = {str(item.get("name", "")) for item in models if isinstance(item, dict)}
            details["present"] = model in names or any(
                name.startswith(model_prefix) for name in names
            )
            details["available_models"] = sorted(names)[:20]
            if smoke and details["present"]:
                prompt = 'Return exactly this JSON and nothing else: {"sidar_doctor": true}'
                response = client.post(
                    f"{base}/generate",
                    json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
                    timeout=60,
                )
                response.raise_for_status()
                text = str(response.json().get("response", "")).strip()
                details["smoke_response"] = text[:500]
                parsed = json.loads(text)
                details["json_smoke"] = parsed.get("sidar_doctor") is True
    except Exception as exc:
        details["error"] = str(exc)
        return DoctorCheck("model", "warn", "Ollama/model check could not be completed", details)

    if not details["present"]:
        return DoctorCheck("model", "warn", f"coding model is not present: {model}", details)
    if smoke and not details["json_smoke"]:
        return DoctorCheck(
            "model", "fail", "coding model did not return valid JSON smoke output", details
        )
    return DoctorCheck("model", "pass", "coding model is present and JSON smoke passed", details)


def run_doctor_report(
    *,
    output_path: str | Path = DEFAULT_OUTPUT,
    include_model_smoke: bool = True,
) -> dict[str, Any]:
    from core.doctor.checks.gpu import check_docker_test_image as docker_test_image_check
    from core.doctor.checks.gpu import check_gpu as gpu_check
    from core.doctor.checks.gpu import check_gpu_memory_config as gpu_memory_config_check
    from core.doctor.checks.media import check_media_tools as media_tools_check
    from core.doctor.checks.rag import (
        check_graphrag_entity_memory_ready as graphrag_entity_memory_ready_check,
    )
    from core.doctor.checks.rag import check_rag_index_ready as rag_index_ready_check
    from core.doctor.checks.redis import check_redis as redis_check

    checks = [
        check_uv(),
        check_prometheus_runtime(),
        check_environment_profile(),
        gpu_memory_config_check(),
        docker_test_image_check(),
        check_database_env(),
    ]
    database_connectivity = check_database_connectivity()
    checks.extend(
        [
            database_connectivity,
            check_pgvector_ready(database_connectivity=database_connectivity),
        ]
    )
    checks.extend(
        [
            rag_index_ready_check(),
            graphrag_entity_memory_ready_check(),
            check_migrations(),
            check_agent_catalog(),
            check_supervisor_routing(),
            check_websocket_routes(),
            redis_check(),
            gpu_check(),
            media_tools_check(),
            check_model(smoke=include_model_smoke),
        ]
    )
    report = build_doctor_report(checks)
    write_doctor_report(report, output_path)
    return report


def _apply_database_env_fix() -> dict[str, Any]:
    """Apply the allowlisted database environment repair and return its audit record.

    The repair is deliberately limited to ``database_env``.  Doctor never starts
    services, runs migrations, or seeds user data implicitly; those operations stay
    visible as follow-up recommendations in the resulting report.
    """
    check = check_database_env()
    result: dict[str, Any] = {
        "check": check.name,
        "before_status": check.status,
        "attempted": False,
        "success": check.status == "pass",
    }
    if check.status == "pass":
        result["message"] = "database environment already healthy; no repair was needed"
        return result

    command = str(check.details.get("auto_fix", "") or "").strip()
    if not command:
        result["message"] = "database environment check did not publish an auto-fix"
        return result

    try:
        tokens = validate_auto_fix_command(command)
    except ValueError as exc:
        result["message"] = f"database environment auto-fix was rejected: {exc}"
        return result

    result["attempted"] = True
    result["command"] = command
    return_code, output = _run_command(tokens, timeout=120)
    result["return_code"] = return_code
    result["output"] = _redact_sensitive_text(output)
    result["success"] = return_code == 0
    result["message"] = (
        "database environment auto-fix completed"
        if return_code == 0
        else "database environment auto-fix failed"
    )

    # --remove-explicit-urls edits dotenv files in a subprocess. Remove only values
    # that Doctor proved came from those editable files, so the report in this same
    # process observes the newly derived POSTGRES_* DSNs. Inherited shell values are
    # intentionally preserved because the repair command cannot safely own them.
    if return_code == 0:
        for env_key, source_key in (
            ("DATABASE_URL", "database_url_source"),
            ("SIDAR_CONTAINER_DATABASE_URL", "container_database_url_source"),
        ):
            if check.details.get(source_key):
                os.environ.pop(env_key, None)
    return result


def _parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the standalone Doctor CLI while preserving its positional output path."""
    parser = argparse.ArgumentParser(description="Sidar installation/readiness Doctor")
    parser.add_argument("output", nargs="?", default=str(DEFAULT_OUTPUT), help="JSON report path")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Safely repair editable database environment drift before running checks",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_cli_args(argv)
    output = Path(args.output)
    repair = _apply_database_env_fix() if args.fix else None
    report = run_doctor_report(output_path=output)
    if repair is not None:
        report["repairs"] = [repair]
        write_doctor_report(report, output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    repair_failed = repair is not None and repair.get("attempted") and not repair.get("success")
    return 0 if report["overall_status"] in {"pass", "warn"} and not repair_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())  # pragma: no cover - module CLI entry point
