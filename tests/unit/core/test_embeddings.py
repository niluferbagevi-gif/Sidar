import os
from pathlib import Path
from types import SimpleNamespace

from core import embeddings


class _FakeSentenceTransformer:
    init_calls = 0

    def __init__(self, *_args, **_kwargs) -> None:
        _FakeSentenceTransformer.init_calls += 1


def test_clear_model_cache_resets_cached_models(mock_sentence_transformer_class) -> None:
    embeddings.clear_model_cache()
    _FakeSentenceTransformer.init_calls = 0
    mock_sentence_transformer_class(_FakeSentenceTransformer)
    cfg = SimpleNamespace(USE_GPU=False, HF_USE_LOCAL_CACHE_ONLY=True, HF_HUB_OFFLINE=False)

    embeddings.get_sentence_transformer_model("model-a", cfg)
    embeddings.get_sentence_transformer_model("model-a", cfg)
    assert _FakeSentenceTransformer.init_calls == 1

    embeddings.clear_model_cache()
    embeddings.get_sentence_transformer_model("model-a", cfg)
    assert _FakeSentenceTransformer.init_calls == 2


def test_model_cache_evicts_old_entries(mock_sentence_transformer_class) -> None:
    embeddings.clear_model_cache()
    _FakeSentenceTransformer.init_calls = 0
    mock_sentence_transformer_class(_FakeSentenceTransformer)
    cfg = SimpleNamespace(USE_GPU=False, HF_USE_LOCAL_CACHE_ONLY=True, HF_HUB_OFFLINE=False)

    for idx in range(5):
        embeddings.get_sentence_transformer_model(f"model-{idx}", cfg)

    assert len(embeddings._MODEL_CACHE) == 4


_HF_CACHE_ENV_KEYS = (
    "HF_HUB_CACHE",
    "HUGGINGFACE_HUB_CACHE",
    "TRANSFORMERS_CACHE",
    "HF_HOME",
)


def _clear_hf_cache_env(monkeypatch) -> None:
    for key in _HF_CACHE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_hf_hub_cache_roots_adds_hf_home_hub(monkeypatch, tmp_path) -> None:
    _clear_hf_cache_env(monkeypatch)
    hf_home = tmp_path / "hf-home"
    monkeypatch.setenv("HF_HOME", str(hf_home))

    assert embeddings._hf_hub_cache_roots() == [hf_home / "hub"]


def test_hf_hub_cache_roots_defaults_to_unique_standard_hub(monkeypatch) -> None:
    _clear_hf_cache_env(monkeypatch)

    assert embeddings._hf_hub_cache_roots() == [Path("~/.cache/huggingface/hub").expanduser()]


def test_hf_model_cache_exists_rejects_empty_name() -> None:
    assert embeddings.hf_model_cache_exists("") is False
    assert embeddings.hf_model_cache_exists("   ") is False


def test_hf_model_cache_exists_accepts_local_path(tmp_path) -> None:
    model_path = tmp_path / "local-model"
    model_path.mkdir()

    assert embeddings.hf_model_cache_exists(str(model_path)) is True


def test_scoped_hf_runtime_env_restores_unset_and_existing_values(monkeypatch) -> None:
    monkeypatch.delenv("HF_HUB_DISABLE_PROGRESS_BARS", raising=False)
    monkeypatch.delenv("TRANSFORMERS_NO_ADVISORY_WARNINGS", raising=False)
    monkeypatch.setenv("TRANSFORMERS_VERBOSITY", "warning")

    with embeddings._scoped_hf_runtime_env():
        assert os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"
        assert os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] == "1"
        assert os.environ["TRANSFORMERS_VERBOSITY"] == "error"

    assert "HF_HUB_DISABLE_PROGRESS_BARS" not in os.environ
    assert "TRANSFORMERS_NO_ADVISORY_WARNINGS" not in os.environ
    assert os.environ["TRANSFORMERS_VERBOSITY"] == "warning"


def test_embedding_load_timeout_ignores_malformed_values() -> None:
    assert embeddings._embedding_load_timeout_seconds(
        SimpleNamespace(RAG_EMBEDDING_LOAD_TIMEOUT_SECONDS="not-a-float")
    ) == 0.0
