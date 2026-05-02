import argparse
import asyncio
import types
from pathlib import Path

import pytest

from scripts.auto_heal import (
    MYPY_SELF_HEAL_REFERENCE,
    _build_attempt_diagnosis,
    _build_scope_queue,
    _extract_scope_error_lines,
    _parse_approval_value,
    _run,
    _run_self_heal_attempt,
    _select_auto_heal_model,
    main,
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


def test_extract_scope_error_lines_filters_deduplicates_and_limits() -> None:
    log_text = """pkg/a.py:10: error: incompatible types
pkg/a.py:10: error: incompatible types
pkg/a.py:11: note: revealed type is str
pkg/b.py:3: error: mypy failure
other/c.py:2: error: should be ignored
"""
    lines = _extract_scope_error_lines(
        log_text,
        scope_paths=["pkg/a.py", "pkg/b.py"],
        limit=3,
    )

    assert len(lines) == 3
    assert "pkg/a.py:10: error: incompatible types" in lines
    assert "pkg/a.py:11: note: revealed type is str" in lines
    assert "pkg/b.py:3: error: mypy failure" in lines


class _FakeAgent:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def _attempt_autonomous_self_heal(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def test_run_self_heal_attempt_retries_with_human_approval(monkeypatch) -> None:
    agent = _FakeAgent([
        {"status": "awaiting_hitl", "summary": "needs approval"},
        {"status": "applied", "summary": "done"},
    ])
    args = argparse.Namespace(hitl_approve="yes")

    result = asyncio.run(
        _run_self_heal_attempt(
            agent=agent,
            context={"k": "v"},
            diagnosis="diag",
            remediation={"x": 1},
            args=args,
        )
    )

    assert result["status"] == "applied"
    assert len(agent.calls) == 2
    assert agent.calls[1]["human_approval"] is True


def test_run_self_heal_attempt_uses_prompt_for_unrecognized_cli_value(monkeypatch) -> None:
    agent = _FakeAgent([
        {"status": "awaiting_hitl", "summary": "needs approval"},
        {"status": "blocked", "summary": "cancelled"},
    ])
    args = argparse.Namespace(hitl_approve="unknown")
    monkeypatch.setattr("scripts.auto_heal._prompt_hitl_approval", lambda: False)

    result = asyncio.run(
        _run_self_heal_attempt(
            agent=agent,
            context={},
            diagnosis="diag",
            remediation={},
            args=args,
        )
    )

    assert result["status"] == "blocked"
    assert agent.calls[1]["human_approval"] is False


def test_run_returns_1_when_log_file_missing(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    args = argparse.Namespace(
        log=str(tmp_path / "missing.log"),
        source="mypy",
        batch_size=1,
        model=None,
        hitl_approve=None,
        batch_retries=2,
        scope_log_lines=30,
    )

    rc = asyncio.run(_run(args))
    out = capsys.readouterr().out

    assert rc == 1
    assert "Log dosyası bulunamadı" in out


def test_main_uses_asyncio_run(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = argparse.Namespace(
        log="x.log",
        source="mypy",
        batch_size=1,
        model=None,
        hitl_approve=None,
        batch_retries=2,
        scope_log_lines=30,
    )
    monkeypatch.setattr("scripts.auto_heal._parse_args", lambda: parsed)

    def _fake_asyncio_run(coro):
        coro.close()
        return 17

    monkeypatch.setattr("scripts.auto_heal.asyncio.run", _fake_asyncio_run)

    assert main() == 17


def test_run_returns_partial_when_later_retry_applies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log_path = tmp_path / "mypy.log"
    log_path.write_text("pkg/a.py:10: error: incompatible types", encoding="utf-8")

    class _Cfg:
        CODING_MODEL = "qwen2.5-coder:3b"
        ENABLE_AUTONOMOUS_SELF_HEAL = False

    class _Agent:
        def __init__(self, config):
            self.config = config
            self.calls = 0

        async def initialize(self):
            return None

        async def _attempt_autonomous_self_heal(self, **kwargs):
            self.calls += 1
            return {"status": "failed" if self.calls == 1 else "applied", "summary": "ok"}

    monkeypatch.setitem(__import__("sys").modules, "config", types.SimpleNamespace(Config=_Cfg))
    monkeypatch.setitem(
        __import__("sys").modules,
        "agent.sidar_agent",
        types.SimpleNamespace(SidarAgent=_Agent),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "core.ci_remediation",
        types.SimpleNamespace(
            build_local_failure_context=lambda *_args, **_kwargs: {
                "root_cause_hint": "type mismatch",
                "failure_summary": "summary",
            },
            build_ci_remediation_payload=lambda *_args, **_kwargs: {
                "remediation_loop": {"scope_paths": ["pkg/a.py"]}
            },
        ),
    )
    args = argparse.Namespace(
        log=str(log_path),
        source="mypy",
        batch_size=1,
        model=None,
        hitl_approve="yes",
        batch_retries=1,
        scope_log_lines=10,
    )

    rc = asyncio.run(_run(args))
    assert rc == 0


def test_run_returns_1_when_all_batches_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log_path = tmp_path / "mypy.log"
    log_path.write_text("pkg/a.py:10: error: incompatible types", encoding="utf-8")

    class _Cfg:
        CODING_MODEL = "qwen2.5-coder:7b"
        ENABLE_AUTONOMOUS_SELF_HEAL = False

    class _Agent:
        def __init__(self, config):
            self.config = config

        async def initialize(self):
            return None

        async def _attempt_autonomous_self_heal(self, **kwargs):
            return {"status": "failed", "summary": "still failing"}

    monkeypatch.setitem(__import__("sys").modules, "config", types.SimpleNamespace(Config=_Cfg))
    monkeypatch.setitem(
        __import__("sys").modules,
        "agent.sidar_agent",
        types.SimpleNamespace(SidarAgent=_Agent),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "core.ci_remediation",
        types.SimpleNamespace(
            build_local_failure_context=lambda *_args, **_kwargs: {
                "root_cause_hint": "type mismatch",
                "failure_summary": "summary",
            },
            build_ci_remediation_payload=lambda *_args, **_kwargs: {
                "remediation_loop": {"scope_paths": ["pkg/a.py", "pkg/b.py"]}
            },
        ),
    )
    args = argparse.Namespace(
        log=str(log_path),
        source="mypy",
        batch_size=2,
        model="qwen2.5-coder:14b",
        hitl_approve="no",
        batch_retries=0,
        scope_log_lines=5,
    )

    rc = asyncio.run(_run(args))
    assert rc == 1
