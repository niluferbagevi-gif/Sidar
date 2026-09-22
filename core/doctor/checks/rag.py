"""RAG and GraphRAG Doctor checks."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote

import core.doctor as _doctor
from core.doctor import DoctorCheck


def _ensure_rag_index_placeholder(rag_dir: Path) -> Path:
    """Create an empty doctor-facing RAG index placeholder when missing."""
    rag_dir.mkdir(parents=True, exist_ok=True)
    index_path = rag_dir / "index.json"
    if not index_path.exists():
        index_path.write_text("{}", encoding="utf-8")
    return index_path


def check_rag_index_ready() -> DoctorCheck:
    state = _doctor._rag_readiness_state()
    details = state["details"]
    blockers = state["blockers"]
    warnings = state["warnings"]
    document_count = int(state["document_count"])
    entity_memory_empty = bool(state["entity_memory_empty"])
    rag_dir = Path(str(details.get("rag_dir", _doctor.BASE_DIR / "data/rag")))
    if not rag_dir.is_absolute():
        rag_dir = _doctor.BASE_DIR / rag_dir
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
    state = _doctor._rag_readiness_state()
    details = state["details"]
    warnings = state["warnings"]
    entity_memory_empty = bool(state["entity_memory_empty"])
    graph_enabled = bool(details.get("graph_rag_enabled"))
    entity_warnings = [w for w in warnings if "GraphRAG entity memory is empty" in w]
    rag_dir = Path(str(details.get("rag_dir", _doctor.BASE_DIR / "data/rag")))
    if not rag_dir.is_absolute():
        rag_dir = _doctor.BASE_DIR / rag_dir
    store_counts = _doctor._query_entity_graph_counts_from_store(rag_dir)
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
    state = _doctor._rag_readiness_state()
    base_details = state.get("details", {}) if isinstance(state, dict) else {}
    vector_backend = str(base_details.get("vector_backend", "") or "").lower()
    database_url, _, _, _ = _doctor._resolved_database_urls()
    postgres_password = os.getenv("POSTGRES_PASSWORD", "").strip()
    parsed_database_url, _ = _doctor._parse_url(database_url)
    database_password = (
        unquote(str(parsed_database_url.password or "")) if parsed_database_url else ""
    )
    mismatch_block = (
        vector_backend == "pgvector"
        and bool(database_url)
        and bool(postgres_password)
        and database_password != postgres_password
    )
    index_check = _doctor.check_rag_index_ready()
    graph_check = _doctor.check_graphrag_entity_memory_ready()
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


__all__ = [
    "check_graphrag_entity_memory_ready",
    "check_rag_index_ready",
    "check_rag_readiness",
]
