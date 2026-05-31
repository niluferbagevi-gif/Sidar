from types import SimpleNamespace

from core import embeddings


class _FakeSentenceTransformer:
    init_calls = 0

    def __init__(self, *_args, **_kwargs) -> None:
        _FakeSentenceTransformer.init_calls += 1


def test_clear_model_cache_resets_cached_models(monkeypatch) -> None:
    embeddings.clear_model_cache()
    _FakeSentenceTransformer.init_calls = 0
    monkeypatch.setitem(
        __import__("sys").modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer),
    )
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
    monkeypatch.setitem(
        __import__("sys").modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer),
    )
    cfg = SimpleNamespace(USE_GPU=False, HF_USE_LOCAL_CACHE_ONLY=True, HF_HUB_OFFLINE=False)

    for idx in range(5):
        embeddings.get_sentence_transformer_model(f"model-{idx}", cfg)

    assert len(embeddings._MODEL_CACHE) == 4


def test_hf_hub_cache_roots_add_defaults_and_deduplicate(monkeypatch) -> None:
    for env_name in (
        "HF_HUB_CACHE",
        "HUGGINGFACE_HUB_CACHE",
        "TRANSFORMERS_CACHE",
        "HF_HOME",
    ):
        monkeypatch.delenv(env_name, raising=False)

    default_hub = embeddings.Path("~/.cache/huggingface/hub").expanduser()
    assert embeddings._hf_hub_cache_roots() == [default_hub]

    monkeypatch.setenv("HF_HUB_CACHE", "/tmp/sidar-hf-cache")
    monkeypatch.setenv("TRANSFORMERS_CACHE", "/tmp/sidar-hf-cache")
    assert embeddings._hf_hub_cache_roots() == [embeddings.Path("/tmp/sidar-hf-cache")]


def test_hf_model_cache_exists_handles_empty_and_local_path(tmp_path) -> None:
    assert embeddings.hf_model_cache_exists("") is False

    local_model = tmp_path / "local-model"
    local_model.mkdir()
    assert embeddings.hf_model_cache_exists(str(local_model)) is True


def test_scoped_hf_runtime_env_removes_temporary_defaults(monkeypatch) -> None:
    keys = (
        "HF_HUB_DISABLE_PROGRESS_BARS",
        "TRANSFORMERS_NO_ADVISORY_WARNINGS",
        "TRANSFORMERS_VERBOSITY",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    with embeddings._scoped_hf_runtime_env():
        assert embeddings.os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"
        assert embeddings.os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] == "1"
        assert embeddings.os.environ["TRANSFORMERS_VERBOSITY"] == "error"

    assert all(key not in embeddings.os.environ for key in keys)
