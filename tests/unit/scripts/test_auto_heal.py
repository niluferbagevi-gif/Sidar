import argparse
import asyncio
import json
import types
from pathlib import Path

import pytest

import scripts.auto_heal as auto_heal
from scripts.auto_heal import (
    MYPY_SELF_HEAL_REFERENCE,
    _build_attempt_diagnosis,
    _build_scope_queue,
    _extract_scope_error_lines,
    _initialize_agent_soft_dependency,
    _parse_approval_value,
    _redact_database_url,
    _resolve_auto_heal_database_url,
    _run,
    _run_self_heal_attempt,
    _select_auto_heal_model,
    main,
)


def test_parse_args_reads_all_cli_options(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log_path = tmp_path / "mypy.log"
    monkeypatch.setattr(
        "sys.argv",
        [
            "auto_heal.py",
            "--log",
            str(log_path),
            "--source",
            "ruff",
            "--batch-size",
            "3",
            "--model",
            "qwen2.5-coder:14b",
            "--hitl-approve",
            "yes",
            "--batch-retries",
            "4",
            "--scope-log-lines",
            "12",
            "--database-url",
            "postgresql://u:p@db/sidar",
        ],
    )

    args = auto_heal._parse_args()

    assert args.log == str(log_path)
    assert args.source == "ruff"
    assert args.batch_size == 3
    assert args.model == "qwen2.5-coder:14b"
    assert args.hitl_approve == "yes"
    assert args.batch_retries == 4
    assert args.scope_log_lines == 12
    assert args.database_url == "postgresql://u:p@db/sidar"


def test_parse_args_applies_optional_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "mypy.log"
    monkeypatch.setattr("sys.argv", ["auto_heal.py", "--log", str(log_path)])

    args = auto_heal._parse_args()

    assert args.source == "mypy"
    assert args.batch_size == 1
    assert args.model is None
    assert args.hitl_approve is None
    assert args.batch_retries == 2
    assert args.scope_log_lines == 30
    assert args.database_url is None


def test_resolve_auto_heal_database_url_defaults_to_log_scoped_sqlite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SELF_HEAL_DATABASE_URL", raising=False)
    log_path = tmp_path / "artifacts" / "mypy.log"

    resolved = _resolve_auto_heal_database_url(log_path, None)

    assert resolved == f"sqlite+aiosqlite:///{(log_path.parent / 'auto_heal_memory.db').as_posix()}"


def test_resolve_auto_heal_database_url_honors_cli_and_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "mypy.log"
    monkeypatch.setenv("SELF_HEAL_DATABASE_URL", "sqlite+aiosqlite:///env.db")

    assert _resolve_auto_heal_database_url(log_path, None) == "sqlite+aiosqlite:///env.db"
    assert (
        _resolve_auto_heal_database_url(log_path, "postgresql://u:p@db/sidar")
        == "postgresql://u:p@db/sidar"
    )


def test_redact_database_url_masks_password() -> None:
    assert (
        _redact_database_url("postgresql+asyncpg://sidar:secret@localhost:5432/sidar")
        == "postgresql+asyncpg://sidar:***@localhost:5432/sidar"
    )
    assert _redact_database_url("sqlite+aiosqlite:///tmp/db.sqlite") == "sqlite+aiosqlite:///tmp/db.sqlite"


def test_prompt_hitl_approval_reprompts_until_value_is_parseable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = iter(["belki", "e"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert auto_heal._prompt_hitl_approval() is True
    assert "Lütfen" in capsys.readouterr().out


def test_initialize_agent_soft_dependency_continues_after_failure() -> None:
    class _Agent:
        async def initialize(self):
            raise RuntimeError("pgvector offline")

    warning = asyncio.run(_initialize_agent_soft_dependency(_Agent()))

    assert warning is not None
    assert "self-heal temel code/LLM yetenekleriyle devam edecek" in warning
    assert "pgvector offline" in warning


def test_initialize_agent_soft_dependency_returns_none_when_ready() -> None:
    class _Agent:
        async def initialize(self):
            return None

    assert asyncio.run(_initialize_agent_soft_dependency(_Agent())) is None


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
    assert _select_auto_heal_model("qwen2.5-coder:" "3b", "mypy", None) == "qwen2.5-coder:7b"


def test_select_auto_heal_model_honors_requested_model() -> None:
    assert (
        _select_auto_heal_model("qwen2.5-coder:" "3b", "mypy", "qwen2.5-coder:14b")
        == "qwen2.5-coder:14b"
    )



def test_build_scope_queue_returns_empty_when_scope_paths_are_blank() -> None:
    assert _build_scope_queue({"scope_paths": ["", "  "]}, batch_size=0) == []


def test_extract_scope_error_lines_empty_and_non_matching_inputs() -> None:
    assert _extract_scope_error_lines("   ", scope_paths=["pkg/a.py"], limit=1) == []
    assert _extract_scope_error_lines("pkg/a.py: ok", scope_paths=[], limit=1) == []
    assert (
        _extract_scope_error_lines(
            "other.py:1: error: ignored\npkg/a.py:2: note: informational",
            scope_paths=["./pkg/a.py"],
            limit=1,
        )
        == []
    )


def test_build_attempt_diagnosis_uses_default_scope_message_without_error_lines() -> None:
    diagnosis = _build_attempt_diagnosis(
        base_diagnosis="",
        scope_paths=["pkg/a.py"],
        scope_error_lines=[],
        attempt=2,
        total_attempts=2,
    )

    assert "Hedef kapsam için tip hataları düzeltilecek: pkg/a.py" in diagnosis
    assert "Batch retry 2/2" in diagnosis
    assert "Hedef hata satırları" not in diagnosis

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
    agent = _FakeAgent(
        [
            {"status": "awaiting_hitl", "summary": "needs approval"},
            {"status": "applied", "summary": "done"},
        ]
    )
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
    agent = _FakeAgent(
        [
            {"status": "awaiting_hitl", "summary": "needs approval"},
            {"status": "blocked", "summary": "cancelled"},
        ]
    )
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


def test_run_returns_1_when_log_file_missing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
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


def test_run_raises_when_failure_context_parser_crashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "mypy.log"
    log_path.write_text("bad log", encoding="utf-8")

    class _Cfg:
        CODING_MODEL = "qwen2.5-coder:7b"
        ENABLE_AUTONOMOUS_SELF_HEAL = False

    class _Agent:
        def __init__(self, config):
            self.config = config

        async def initialize(self):
            return None

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
            build_local_failure_context=lambda *_a, **_k: (_ for _ in ()).throw(
                SyntaxError("ast parse failed")
            ),
            build_ci_remediation_payload=lambda *_a, **_k: {
                "remediation_loop": {"scope_paths": []}
            },
        ),
    )
    args = argparse.Namespace(
        log=str(log_path),
        source="mypy",
        batch_size=1,
        model=None,
        hitl_approve=None,
        batch_retries=1,
        scope_log_lines=10,
    )

    with pytest.raises(SyntaxError, match="ast parse failed"):
        asyncio.run(_run(args))


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


def test_run_uses_isolated_sqlite_memory_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_path = tmp_path / "mypy.log"
    log_path.write_text("pkg/a.py:10: error: incompatible types", encoding="utf-8")
    monkeypatch.delenv("SELF_HEAL_DATABASE_URL", raising=False)

    class _Cfg:
        CODING_MODEL = "qwen2.5-coder:7b"
        ENABLE_AUTONOMOUS_SELF_HEAL = False
        DATABASE_URL = "postgresql+asyncpg://sidar:wrong@localhost:5432/sidar"

    class _Agent:
        seen_database_url = ""

        def __init__(self, config):
            self.config = config
            self.__class__.seen_database_url = config.DATABASE_URL

        async def initialize(self):
            return None

        async def _attempt_autonomous_self_heal(self, **kwargs):
            return {"status": "applied", "summary": "done"}

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
        hitl_approve=None,
        batch_retries=0,
        scope_log_lines=10,
        database_url=None,
    )

    rc = asyncio.run(_run(args))
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert _Agent.seen_database_url.startswith("sqlite+aiosqlite:///")
    assert _Agent.seen_database_url.endswith("/auto_heal_memory.db")
    assert payload["database_url"] == _Agent.seen_database_url


def test_run_continues_when_agent_initialize_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_path = tmp_path / "mypy.log"
    log_path.write_text("pkg/a.py:10: error: incompatible types", encoding="utf-8")

    class _Cfg:
        CODING_MODEL = "qwen2.5-coder:7b"
        ENABLE_AUTONOMOUS_SELF_HEAL = False
        DATABASE_URL = "postgresql+asyncpg://sidar:wrong@localhost:5432/sidar"

    class _Agent:
        async def initialize(self):
            raise RuntimeError("PostgreSQL password authentication failed")

        def __init__(self, config):
            self.config = config

        async def _attempt_autonomous_self_heal(self, **kwargs):
            return {"status": "applied", "summary": "done"}

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
        hitl_approve=None,
        batch_retries=0,
        scope_log_lines=10,
        database_url=None,
    )

    rc = asyncio.run(_run(args))
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "applied"
    assert "PostgreSQL password authentication failed" in payload["initialization_warning"]


def test_run_returns_partial_when_later_retry_applies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "mypy.log"
    log_path.write_text("pkg/a.py:10: error: incompatible types", encoding="utf-8")

    class _Cfg:
        CODING_MODEL = "qwen2.5-coder:" "3b"
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


def test_run_returns_1_when_all_batches_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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


def test_run_skips_clean_mypy_output_without_targets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_path = tmp_path / "mypy-clean.log"
    log_path.write_text("Success: no issues found in 12 source files", encoding="utf-8")

    def _unexpected_payload_call(*_args, **_kwargs):
        raise AssertionError("clean mypy output should not build remediation payload")

    monkeypatch.setitem(__import__("sys").modules, "config", types.SimpleNamespace(Config=object))
    monkeypatch.setitem(
        __import__("sys").modules,
        "agent.sidar_agent",
        types.SimpleNamespace(SidarAgent=object),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "core.ci_remediation",
        types.SimpleNamespace(
            build_local_failure_context=lambda *_args, **_kwargs: {
                "failure_summary": "clean",
                "suspected_targets": [],
            },
            build_ci_remediation_payload=_unexpected_payload_call,
        ),
    )
    args = argparse.Namespace(
        log=str(log_path),
        source="mypy",
        batch_size=1,
        model=None,
        hitl_approve=None,
        batch_retries=2,
        scope_log_lines=30,
    )

    rc = asyncio.run(_run(args))
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "skipped"
    assert payload["queue_size"] == 0
    assert "mypy temiz" in payload["reason"]


def test_run_does_not_retry_non_retryable_batch_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_path = tmp_path / "mypy.log"
    log_path.write_text("pkg/a.py:10: error: incompatible types", encoding="utf-8")

    class _Cfg:
        CODING_MODEL = "qwen2.5-coder:7b"
        ENABLE_AUTONOMOUS_SELF_HEAL = False

    class _Agent:
        instances = []

        def __init__(self, config):
            self.config = config
            self.calls = 0
            self.__class__.instances.append(self)

        async def initialize(self):
            return None

        async def _attempt_autonomous_self_heal(self, **kwargs):
            self.calls += 1
            return {"status": "reverted", "summary": "rollback kept tree clean"}

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
        hitl_approve=None,
        batch_retries=5,
        scope_log_lines=10,
    )

    rc = asyncio.run(_run(args))
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert _Agent.instances[0].calls == 1
    assert payload["status"] == "failed"
    assert payload["executions"][0]["status"] == "reverted"
    assert payload["executions"][0]["attempts"] == [
        {"attempt": 1, "status": "reverted", "summary": "rollback kept tree clean"}
    ]


def test_run_handles_targeted_context_without_scope_error_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_path = tmp_path / "mypy.log"
    log_path.write_text("pkg/a.py:10: note: informational only", encoding="utf-8")

    class _Cfg:
        CODING_MODEL = "qwen2.5-coder:7b"
        ENABLE_AUTONOMOUS_SELF_HEAL = False

    class _Agent:
        async def initialize(self):
            return None

        def __init__(self, config):
            self.config = config

        async def _attempt_autonomous_self_heal(self, **kwargs):
            return {"status": "applied", "summary": "done"}

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
                "root_cause_hint": "",
                "failure_summary": "",
                "suspected_targets": ["pkg/a.py"],
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
        hitl_approve=None,
        batch_retries=2,
        scope_log_lines=5,
    )

    rc = asyncio.run(_run(args))
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "applied"
    assert payload["executions"][0]["attempts"] == [
        {"attempt": 1, "status": "applied", "summary": "done"}
    ]
