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
