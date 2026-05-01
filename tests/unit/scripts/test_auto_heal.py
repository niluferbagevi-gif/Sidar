from scripts.auto_heal import (
    MYPY_SELF_HEAL_REFERENCE,
    _build_attempt_diagnosis,
    _build_scope_queue,
    _extract_scope_error_lines,
    _parse_approval_value,
    _run_self_heal_attempt,
    _select_auto_heal_model,
)


class _DummyAgent:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    async def _attempt_autonomous_self_heal(self, **kwargs):  # noqa: SLF001
        self.calls.append(kwargs)
        return self._responses[len(self.calls) - 1]


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


def test_build_scope_queue_returns_empty_for_missing_paths() -> None:
    assert _build_scope_queue({}, batch_size=2) == []


def test_extract_scope_error_lines_filters_non_matching_and_duplicates() -> None:
    log_text = "\n".join(
        [
            "pkg/a.py:10: error: incompatible types",
            "pkg/a.py:10: error: incompatible types",
            "pkg/b.py:3: note: revealed type is \"int\"",
            "pkg/b.py:8: error: no-untyped-def",
            "other/c.py:1: error: nope",
        ]
    )
    lines = _extract_scope_error_lines(log_text, scope_paths=["pkg/a.py", "pkg/b.py"], limit=10)
    assert lines == [
        "pkg/a.py:10: error: incompatible types",
        "pkg/b.py:8: error: no-untyped-def",
    ]


def test_extract_scope_error_lines_respects_limit_and_windows_paths() -> None:
    log_text = "\n".join(
        [
            r"pkg\\a.py:10: error: incompatible types",
            "./pkg/a.py:12: mypy error",
            "pkg/a.py:14: error: invalid type",
        ]
    )
    lines = _extract_scope_error_lines(log_text, scope_paths=["./pkg/a.py"], limit=2)
    assert lines == [r"pkg\\a.py:10: error: incompatible types", "./pkg/a.py:12: mypy error"]


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


async def test_run_self_heal_attempt_returns_without_hitl() -> None:
    agent = _DummyAgent([{"status": "applied", "summary": "ok"}])
    args = type("Args", (), {"hitl_approve": None})()
    result = await _run_self_heal_attempt(
        agent=agent,
        context={"a": 1},
        diagnosis="diag",
        remediation={"r": 1},
        args=args,
    )
    assert result["status"] == "applied"
    assert len(agent.calls) == 1


async def test_run_self_heal_attempt_retries_with_manual_approval_flag() -> None:
    agent = _DummyAgent(
        [
            {"status": "awaiting_hitl", "summary": "need approval"},
            {"status": "applied", "summary": "done"},
        ]
    )
    args = type("Args", (), {"hitl_approve": "yes"})()
    result = await _run_self_heal_attempt(
        agent=agent,
        context={"a": 1},
        diagnosis="diag",
        remediation={"r": 1},
        args=args,
    )
    assert result["status"] == "applied"
    assert len(agent.calls) == 2
    assert agent.calls[1]["human_approval"] is True
