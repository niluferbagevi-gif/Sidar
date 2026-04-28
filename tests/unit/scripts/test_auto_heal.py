from types import SimpleNamespace

from scripts.auto_heal import (
    _build_scope_queue,
    _count_error_lines,
    _parse_approval_value,
    _select_auto_heal_model,
    _select_cloud_fallback,
)


def test_parse_approval_value_accepts_short_and_tr_aliases() -> None:
    assert _parse_approval_value("e") is True
    assert _parse_approval_value("evet") is True
    assert _parse_approval_value("h") is False
    assert _parse_approval_value("hayır") is False


def test_parse_approval_value_accepts_en_boolean_aliases() -> None:
    assert _parse_approval_value("yes") is True
    assert _parse_approval_value("true") is True
    assert _parse_approval_value("1") is True
    assert _parse_approval_value("no") is False
    assert _parse_approval_value("false") is False
    assert _parse_approval_value("0") is False


def test_parse_approval_value_returns_none_for_unknown() -> None:
    assert _parse_approval_value(None) is None
    assert _parse_approval_value("") is None
    assert _parse_approval_value("maybe") is None


def test_select_auto_heal_model_promotes_3b_for_mypy() -> None:
    assert _select_auto_heal_model("qwen2.5-coder:3b", "mypy", None) == "qwen2.5-coder:7b"


def test_select_auto_heal_model_honors_requested_model() -> None:
    assert _select_auto_heal_model("qwen2.5-coder:3b", "mypy", "qwen2.5-coder:14b") == "qwen2.5-coder:14b"


def test_build_scope_queue_chunks_paths_by_batch_size() -> None:
    queue = _build_scope_queue(
        {"scope_paths": ["a.py", "b.py", "c.py", "d.py"]},
        batch_size=2,
    )
    assert queue == [["a.py", "b.py"], ["c.py", "d.py"]]


def test_count_error_lines_counts_mypy_error_rows_only() -> None:
    log = (
        "agent/a.py:1: error: missing type annotation  [no-untyped-def]\n"
        "agent/a.py:2: note: hinted type\n"
        "agent/b.py:9: error: Incompatible types  [assignment]\n"
    )
    assert _count_error_lines(log, "mypy") == 2
    assert _count_error_lines(log, "pytest") == 0


def test_select_cloud_fallback_uses_openai_when_threshold_exceeded(monkeypatch) -> None:
    class _RouterStub:
        def __init__(self, _cfg: SimpleNamespace) -> None:
            pass

        def select(
            self, messages: list[dict[str, str]], default_provider: str, default_model: str | None
        ) -> tuple[str, str | None]:
            assert messages and "Mypy self-heal" in messages[0]["content"]
            assert default_provider == "ollama"
            assert default_model == "qwen2.5-coder:7b"
            return "openai", "gpt-4o"

    monkeypatch.setattr("core.router.CostAwareRouter", _RouterStub)
    cfg = SimpleNamespace(
        AI_PROVIDER="ollama",
        CODING_MODEL="qwen2.5-coder:7b",
        COST_ROUTING_LOCAL_PROVIDER="ollama",
        COST_ROUTING_CLOUD_PROVIDER="",
        COST_ROUTING_CLOUD_MODEL="",
        OPENAI_API_KEY="k",
        OPENAI_MODEL="gpt-4o",
        ANTHROPIC_API_KEY="",
        ANTHROPIC_MODEL="",
    )

    provider, model = _select_cloud_fallback(
        cfg,
        source="mypy",
        error_count=24,
        diagnosis="type errors",
        threshold=10,
    )
    assert provider == "openai"
    assert model == "gpt-4o"


def test_select_cloud_fallback_skips_when_below_threshold() -> None:
    cfg = SimpleNamespace(
        AI_PROVIDER="ollama",
        CODING_MODEL="qwen2.5-coder:7b",
        COST_ROUTING_LOCAL_PROVIDER="ollama",
        COST_ROUTING_CLOUD_PROVIDER="",
        COST_ROUTING_CLOUD_MODEL="",
        OPENAI_API_KEY="k",
        OPENAI_MODEL="gpt-4o",
        ANTHROPIC_API_KEY="",
        ANTHROPIC_MODEL="",
    )
    assert _select_cloud_fallback(
        cfg,
        source="mypy",
        error_count=3,
        diagnosis="",
        threshold=10,
    ) == ("", None)
