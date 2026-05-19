from types import SimpleNamespace

from core import embeddings


class _FakeSentenceTransformer:
    init_calls = 0

    def __init__(self, *_args, **_kwargs) -> None:
        _FakeSentenceTransformer.init_calls += 1


def test_clear_model_cache_resets_cached_models(monkeypatch) -> None:
    embeddings.clear_model_cache()
    _FakeSentenceTransformer.init_calls = 0
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer))
    cfg = SimpleNamespace(USE_GPU=False, HF_USE_LOCAL_CACHE_ONLY=True, HF_HUB_OFFLINE=False)

    embeddings.get_sentence_transformer_model("model-a", cfg)
    embeddings.get_sentence_transformer_model("model-a", cfg)
    assert _FakeSentenceTransformer.init_calls == 1

    embeddings.clear_model_cache()
    embeddings.get_sentence_transformer_model("model-a", cfg)
    assert _FakeSentenceTransformer.init_calls == 2


def test_model_cache_evicts_old_entries(monkeypatch) -> None:
    embeddings.clear_model_cache()
    _FakeSentenceTransformer.init_calls = 0
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer))
    cfg = SimpleNamespace(USE_GPU=False, HF_USE_LOCAL_CACHE_ONLY=True, HF_HUB_OFFLINE=False)

    for idx in range(5):
        embeddings.get_sentence_transformer_model(f"model-{idx}", cfg)

    assert len(embeddings._MODEL_CACHE) == 4
