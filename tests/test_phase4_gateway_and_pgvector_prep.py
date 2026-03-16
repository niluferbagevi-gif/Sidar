import asyncio
from types import SimpleNamespace

from core.llm_client import LLMClient, LiteLLMClient, build_provider_json_mode_config
from core.rag import DocumentStore


def test_llm_factory_supports_litellm_provider():
    cfg = SimpleNamespace(
        LITELLM_GATEWAY_URL="http://localhost:4000",
        LITELLM_API_KEY="",
        LITELLM_MODEL="gpt-4o-mini",
        LITELLM_FALLBACK_MODELS=[],
        LITELLM_TIMEOUT=10,
        OPENAI_MODEL="gpt-4o-mini",
        LLM_MAX_RETRIES=0,
        LLM_RETRY_BASE_DELAY=0.01,
        LLM_RETRY_MAX_DELAY=0.02,
    )
    fac = LLMClient("litellm", cfg)
    assert fac.provider == "litellm"
    assert isinstance(fac._client, LiteLLMClient)
    assert build_provider_json_mode_config("litellm") == {"response_format": {"type": "json_object"}}


def test_litellm_missing_gateway_returns_error_json():
    cfg = SimpleNamespace(
        LITELLM_GATEWAY_URL="",
        LITELLM_API_KEY="",
        LITELLM_MODEL="",
        LITELLM_FALLBACK_MODELS=[],
        LITELLM_TIMEOUT=10,
        OPENAI_MODEL="gpt-4o-mini",
        LLM_MAX_RETRIES=0,
        LLM_RETRY_BASE_DELAY=0.01,
        LLM_RETRY_MAX_DELAY=0.02,
    )
    cli = LiteLLMClient(cfg)
    out = asyncio.run(cli.chat([{"role": "user", "content": "merhaba"}], stream=False, json_mode=True))
    assert "LITELLM_GATEWAY_URL" in out


def test_rag_pgvector_backend_disables_chroma(tmp_path):
    cfg = SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=300,
        RAG_CHUNK_OVERLAP=40,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
        RAG_VECTOR_BACKEND="pgvector",
    )
    store = DocumentStore(tmp_path / "rag", cfg=cfg)
    assert store._vector_backend == "pgvector"
    assert store._chroma_available is False
    assert "pgvector" in store.status().lower()