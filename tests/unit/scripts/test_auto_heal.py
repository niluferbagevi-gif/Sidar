from scripts.auto_heal import (
    MYPY_SELF_HEAL_REFERENCE,
    _build_attempt_diagnosis,
    _build_scope_queue,
    _parse_approval_value,
    _select_auto_heal_model,
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


def test_build_attempt_diagnosis_includes_mypy_reference() -> None:
    diagnosis = _build_attempt_diagnosis(
        base_diagnosis="root cause",
        scope_paths=["pkg/a.py"],
        scope_error_lines=["pkg/a.py:10: error: Library stubs not installed  [import-untyped]"],
        attempt=1,
        total_attempts=3,
    )
    assert "ignore[import-untyped]" in diagnosis
    assert MYPY_SELF_HEAL_REFERENCE in diagnosis
