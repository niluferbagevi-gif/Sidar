"""Doctor check groups split by operational domain."""

from __future__ import annotations

from core.doctor.checks.database import (
    check_database_connectivity,
    check_database_env,
    check_pgvector_ready,
)
from core.doctor.checks.gpu import check_gpu, check_gpu_memory_config
from core.doctor.checks.rag import (
    check_graphrag_entity_memory_ready,
    check_rag_index_ready,
    check_rag_readiness,
)
from core.doctor.checks.redis import check_redis
from core.doctor.checks.security import check_environment_profile

__all__ = [
    "check_database_connectivity",
    "check_database_env",
    "check_environment_profile",
    "check_gpu",
    "check_gpu_memory_config",
    "check_graphrag_entity_memory_ready",
    "check_pgvector_ready",
    "check_rag_index_ready",
    "check_rag_readiness",
    "check_redis",
]
