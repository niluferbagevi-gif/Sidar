"""
RAG (Retrieval-Augmented Generation) readiness checks for Sidar doctor.

These functions delegate to the original implementations in core.doctor so that
RAG-specific readiness is separated into its own module.
"""

from __future__ import annotations

from core.doctor import DoctorCheck
from core.doctor import (
    check_rag_index_ready as _orig_check_rag_index_ready,
    check_graphrag_entity_memory_ready as _orig_check_graphrag_entity_memory_ready,
)


def check_rag_index_ready() -> DoctorCheck:
    """
    Ensure that the RAG index and associated vector backends are ready.

    Delegates to core.doctor.check_rag_index_ready() to perform the actual checks.
    """
    return _orig_check_rag_index_ready()


def check_graphrag_entity_memory_ready() -> DoctorCheck:
    """
    Ensure that the GraphRAG entity memory has been populated.

    Delegates to core.doctor.check_graphrag_entity_memory_ready() to perform the actual checks.
    """
    return _orig_check_graphrag_entity_memory_ready()
