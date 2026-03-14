# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

from pathlib import Path

import pytest

pytest.importorskip("pytest_benchmark")

from agent.auto_handle import AutoHandle
from core.rag import DocumentStore


class _FakeCollection:
    def count(self) -> int:
        return 32

    def query(self, query_texts, n_results, where):
        docs = [f"chunk-{i} match" for i in range(min(n_results, 8))]
        metas = [
            {
                "parent_id": f"doc-{i}",
                "title": f"Title {i}",
                "source": "benchmark",
            }
            for i in range(min(n_results, 8))
        ]
        return {
            "ids": [[f"chunk-{i}" for i in range(len(docs))]],
            "documents": [docs],
            "metadatas": [metas],
        }


@pytest.fixture
def doc_store(tmp_path: Path) -> DocumentStore:
    store = DocumentStore(tmp_path / "rag_benchmark", use_gpu=False)

    doc_id = "bm25-doc-1"
    content = "python regex benchmark query performance measurement " * 8
    (store.store_dir / f"{doc_id}.txt").write_text(content, encoding="utf-8")
    store._index[doc_id] = {
        "title": "Benchmark Doc",
        "source": "tests",
        "session_id": "global",
    }
    store._update_bm25_cache_on_add(doc_id, content)

    store.collection = _FakeCollection()
    store._chroma_available = True
    return store


def test_chromadb_query_baseline_under_200ms(benchmark, doc_store: DocumentStore):
    benchmark(lambda: doc_store._fetch_chroma("regex benchmark", top_k=3, session_id="global"))
    assert (benchmark.stats.stats.mean * 1000) < 200


def test_bm25_query_baseline_under_50ms(benchmark, doc_store: DocumentStore):
    benchmark(lambda: doc_store._fetch_bm25("regex benchmark", top_k=3, session_id="global"))
    assert (benchmark.stats.stats.mean * 1000) < 50


def test_autohandle_regex_baseline_under_5ms(benchmark):
    sample = (
        "Önce repository durumunu kontrol et, ardından testleri çalıştır ve "
        "sonrasında çıktı raporunu paylaş."
    )
    benchmark(lambda: AutoHandle._MULTI_STEP_RE.search(sample))
    assert (benchmark.stats.stats.mean * 1000) < 5