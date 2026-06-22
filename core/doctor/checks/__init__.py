"""
Check module aggregator for Sidar doctor.

This package provides top-level functions for doctor checks, grouping
database, RAG, GPU, Redis and security environment checks into separate modules.
"""

from .database import check_database_env, check_database_connectivity, check_pgvector_ready
from .rag import check_rag_index_ready, check_graphrag_entity_memory_ready
from .gpu import check_gpu
from .redis import check_redis_connectivity
from .security import check_security_env

__all__ = [
    "check_database_env",
    "check_database_connectivity",
    "check_pgvector_ready",
    "check_rag_index_ready",
    "check_graphrag_entity_memory_ready",
    "check_gpu",
    "check_redis_connectivity",
    "check_security_env",
]
