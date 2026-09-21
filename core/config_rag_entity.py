"""RAG LLM-based entity extraction settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env


@dataclass(frozen=True)
class RagEntitySettings:
    """``core/rag/__init__.py`` LLM-based entity extraction settings."""

    enable_rag_llm_entity_extraction: bool
    rag_llm_entity_provider: str
    rag_llm_entity_model: str
    rag_llm_entity_review_target: str


def load_rag_entity_settings() -> RagEntitySettings:
    """Load RAG LLM-based entity extraction settings from environment variables."""
    return RagEntitySettings(
        enable_rag_llm_entity_extraction=get_bool_env("ENABLE_RAG_LLM_ENTITY_EXTRACTION", False),
        rag_llm_entity_provider=os.getenv("RAG_LLM_ENTITY_PROVIDER", ""),
        rag_llm_entity_model=os.getenv("RAG_LLM_ENTITY_MODEL", ""),
        rag_llm_entity_review_target=os.getenv("RAG_LLM_ENTITY_REVIEW_TARGET", "2026-Q3"),
    )
