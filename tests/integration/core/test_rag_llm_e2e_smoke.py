import pytest

from core import llm_client as llm
from core import rag


class _FakeOllamaClient:
    def __init__(self, _config):
        self.calls = []

    async def chat(self, messages, model=None, stream=False, json_mode=False):
        self.calls.append((messages, model, stream, json_mode))
        return '{"thought":"ok","tool":"final_answer","argument":"done"}'

    async def list_models(self):
        return ["qwen2.5-coder:7b", "llama3.1"]

    async def is_available(self):
        return True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_llm_client_ollama_listing_and_availability(monkeypatch):
    monkeypatch.setitem(llm.LLMClient.PROVIDER_REGISTRY, "ollama", _FakeOllamaClient)
    cfg = type("Cfg", (), {"OLLAMA_URL": "http://localhost:11434", "OLLAMA_TIMEOUT": 30})()

    client = llm.LLMClient("ollama", cfg)

    models = await client.list_ollama_models()
    available = await client.is_ollama_available()
    reply = await client.chat(
        [
            {"role": "system", "content": "json only"},
            {"role": "user", "content": "selam"},
        ]
    )

    assert available is True
    assert "qwen2.5-coder:7b" in models
    assert "final_answer" in reply


@pytest.mark.integration
def test_rag_search_prefers_pgvector_and_falls_back_to_bm25():
    ds = rag.DocumentStore.__new__(rag.DocumentStore)
    ds.cfg = type("Cfg", (), {"RAG_TOP_K": 5})()
    ds.default_top_k = 5
    ds._index = {"doc-1": {"session_id": "global"}}
    ds._pgvector_available = True
    ds._chroma_available = False
    ds.collection = None
    ds._bm25_available = True
    ds._is_local_llm_provider = False
    ds._local_hybrid_enabled = True
    ds._vector_backend = "pgvector"

    def _pg_fail(query, top_k, session_id):
        raise RuntimeError("pgvector down")

    ds._pgvector_search = _pg_fail
    ds._bm25_search = lambda query, top_k, session_id: (True, f"bm25:{query}:{top_k}:{session_id}")
    ds._keyword_search = lambda query, top_k, session_id: (True, "keyword")
    ds._rrf_search = lambda query, top_k, session_id: (_ for _ in ()).throw(RuntimeError("rrf fail"))

    ok, out = ds._search_sync("integration query", mode="auto", session_id="global")

    assert ok is True
    assert out.startswith("bm25:integration query")
