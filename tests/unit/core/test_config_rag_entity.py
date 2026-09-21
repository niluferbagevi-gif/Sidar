"""Tests for RAG LLM-based entity extraction settings resolution."""

from core.config_rag_entity import load_rag_entity_settings

_ALL_KEYS = (
    "ENABLE_RAG_LLM_ENTITY_EXTRACTION",
    "RAG_LLM_ENTITY_PROVIDER",
    "RAG_LLM_ENTITY_MODEL",
    "RAG_LLM_ENTITY_REVIEW_TARGET",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_the_documented_values(monkeypatch):
    """With nothing configured, every field matches its documented default."""
    _clear_all(monkeypatch)

    settings = load_rag_entity_settings()

    assert settings.enable_rag_llm_entity_extraction is False
    assert settings.rag_llm_entity_provider == ""
    assert settings.rag_llm_entity_model == ""
    assert settings.rag_llm_entity_review_target == "2026-Q3"


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("ENABLE_RAG_LLM_ENTITY_EXTRACTION", "true")
    monkeypatch.setenv("RAG_LLM_ENTITY_PROVIDER", "openai")
    monkeypatch.setenv("RAG_LLM_ENTITY_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("RAG_LLM_ENTITY_REVIEW_TARGET", "2027-Q1")

    settings = load_rag_entity_settings()

    assert settings.enable_rag_llm_entity_extraction is True
    assert settings.rag_llm_entity_provider == "openai"
    assert settings.rag_llm_entity_model == "gpt-4o-mini"
    assert settings.rag_llm_entity_review_target == "2027-Q1"
