from __future__ import annotations

from typing import Any

from core.rag import facade


def test_public_embedding_function_wrapper_delegates_all_arguments(
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _fake_builder(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return kwargs

    monkeypatch.setattr(facade, "_build_embedding_function", _fake_builder)

    result = facade.build_embedding_function(
        use_gpu=True, gpu_device=2, mixed_precision=True, cfg="cfg"
    )

    assert result == {
        "use_gpu": True,
        "gpu_device": 2,
        "mixed_precision": True,
        "cfg": "cfg",
    }
    assert calls == [result]


def test_build_embedding_function_cached_does_not_remember_a_failed_attempt() -> None:
    """Regression proving lru_cache doesn't remember a failed builder call.

    A code review flagged the GPU→CPU embedding fallback as permanent for
    the process's lifetime and asked whether @functools.lru_cache was the
    cause. It is not: lru_cache never caches a raised exception, so calling
    _build_embedding_function_cached again with the exact same arguments
    re-executes the factory rather than replaying a cached failure. (The
    real reason the fallback is effectively permanent is that
    DocumentStore._init_chroma() only calls the builder once per singleton
    — see the docstring this test guards.) This locks in the cache-level
    claim with a real call, independent of DocumentStore's lifecycle and of
    any real GPU/torch availability (use_gpu=False exercises the exact same
    lru_cache mechanics without needing CUDA).
    """
    facade._build_embedding_function_cached.cache_clear()
    call_count = {"n": 0}

    def _flaky_factory(*, model_name: str, device: str, local_files_only: bool) -> str:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated transient failure")
        return f"ef:{device}"

    kwargs = {
        "use_gpu": False,
        "gpu_device": 0,
        "mixed_precision": False,
        "local_files_only": False,
        "embedding_function_factory": _flaky_factory,
        "embedding_function_factory_id": id(_flaky_factory),
    }

    try:
        try:
            facade._build_embedding_function_cached(**kwargs)
            raise AssertionError("expected the first (flaky) attempt to raise")
        except RuntimeError:
            pass

        result = facade._build_embedding_function_cached(**kwargs)
    finally:
        facade._build_embedding_function_cached.cache_clear()

    assert call_count["n"] == 2  # the second call actually re-ran the factory
    assert result == "ef:cpu"
