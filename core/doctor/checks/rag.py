"""RAG and GraphRAG Doctor checks."""

from __future__ import annotations

import core.doctor as _doctor
from core.doctor import DoctorCheck


def check_rag_index_ready() -> DoctorCheck:
    return _doctor.check_rag_index_ready()


def check_graphrag_entity_memory_ready() -> DoctorCheck:
    return _doctor.check_graphrag_entity_memory_ready()


def check_rag_readiness() -> DoctorCheck:
    return _doctor.check_rag_readiness()


__all__ = [
    "check_graphrag_entity_memory_ready",
    "check_rag_index_ready",
    "check_rag_readiness",
]
