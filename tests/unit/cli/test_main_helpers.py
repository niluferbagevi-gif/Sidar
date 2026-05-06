"""Unit tests for launcher helper functions in main.py."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

import main
from main import _safe_choice, _safe_port, _safe_text, build_command


class _FakeStreamingPipe(io.StringIO):
    """StringIO pipe double that records close without breaking getvalue assertions."""

    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.closed_by_streamer = False

    def close(self) -> None:  # pragma: no cover - behavior asserted through flag
        self.closed_by_streamer = True


class _FakeStreamingProcess:
    def __init__(
        self,
        *,
        stdout: _FakeStreamingPipe | None = None,
        stderr: _FakeStreamingPipe | None = None,
        return_code: int = 0,
        running_after_wait: bool = False,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code
        self.running_after_wait = running_after_wait
        self.terminated = False
        self.wait_calls: list[float | None] = []

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        return self.return_code

    def poll(self) -> int | None:
        return None if self.running_after_wait and not self.terminated else self.return_code

    def terminate(self) -> None:
        self.terminated = True


@pytest.fixture(autouse=True)
def _mock_critical_config_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid real critical-config validation side effects in unit tests."""
    fake_cfg = SimpleNamespace(
        validate_critical_settings=lambda: True,
        init_telemetry=lambda **_kwargs: None,
    )
    monkeypatch.setattr(main, "cfg", fake_cfg)


def test_safe_choice_falls_back_for_invalid_inputs() -> None:
    allowed = {"web", "cli"}

    assert _safe_choice("web", default="cli", allowed=allowed) == "web"
    assert _safe_choice("unknown", default="cli", allowed=allowed) == "cli"
    assert _safe_choice(None, default="cli", allowed=allowed) == "cli"


def test_safe_text_and_port_normalization() -> None:
    assert _safe_text("  hello  ", default="x") == "hello"
    assert _safe_text("", default="x") == "x"

    assert _safe_port("7860") == "7860"
    assert _safe_port("70000") == "7860"
    assert _safe_port("abc") == "7860"


def test_build_command_for_web_and_cli_modes() -> None:
    web_cmd = build_command(
        mode="web",
        provider="ollama",
        level="full",
        log="info",
        extra_args={"host": "0.0.0.0", "port": "9000"},
    )
    assert web_cmd[-4:] == ["--host", "0.0.0.0", "--port", "9000"]

    cli_cmd = build_command(
        mode="cli",
        provider="ollama",
        level="full",
        log="debug",
        extra_args={"model": "qwen2.5-coder:7b"},
    )
    assert "--model" in cli_cmd
    assert "qwen2.5-coder:7b" in cli_cmd


def test_build_command_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError):
        build_command(
            mode="invalid",
            provider="ollama",
            level="full",
            log="info",
            extra_args={},
        )


def test_main_quick_mode_executes_built_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--quick", "cli", "--provider", "ollama", "--level", "full"],
    )
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (True, None))

    seen: dict[str, object] = {}

    def fake_execute(
        cmd: list[str], capture_output: bool = False, child_log_path: str | None = None
    ) -> int:
        seen["cmd"] = cmd
        seen["capture"] = capture_output
        seen["child_log"] = child_log_path
        return 0

    monkeypatch.setattr(main, "execute_command", fake_execute)

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0
    assert isinstance(seen["cmd"], list)
    assert "cli.py" in seen["cmd"]
    assert seen["capture"] is False
    assert seen["child_log"] is None


def test_main_quick_mode_rejects_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", "--quick", "web", "--port", "70000"])

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 2


def test_main_quick_mode_rejects_nonnumeric_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", "--quick", "web", "--port", "abc"])

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 2


def test_main_exits_when_runtime_dependencies_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", "--quick", "web", "--provider", "openai"])
    monkeypatch.setattr(
        main, "validate_runtime_dependencies", lambda _mode: (False, "runtime error")
    )

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 2


def test_run_wizard_returns_2_when_runtime_dependencies_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "print_banner", lambda: None)
    choices = iter(["web", "openai", "full", "info"])
    monkeypatch.setattr(main, "ask_choice", lambda *args, **kwargs: next(choices))
    monkeypatch.setattr(main, "ask_text", lambda *args, **kwargs: "7860")
    monkeypatch.setattr(main, "preflight", lambda _provider: None)
    monkeypatch.setattr(
        main, "validate_runtime_dependencies", lambda _mode: (False, "runtime boom")
    )

    rc = main.run_wizard()

    assert rc == 2


def test_execute_command_capture_output_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(main, "_run_with_streaming", lambda _cmd, _log: 7)

    rc = main.execute_command(["python", "cli.py"], capture_output=True)
    out = capsys.readouterr().out

    assert rc == 7
    assert "Program hata ile sonlandı (Çıkış Kodu: 7)" in out


def test_execute_command_handles_called_process_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise main.subprocess.CalledProcessError(returncode=9, cmd=["python", "cli.py"])

    monkeypatch.setattr(main.subprocess, "run", _raise)

    rc = main.execute_command(["python", "cli.py"])

    assert rc == 9


def test_main_without_quick_runs_wizard_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["main.py"])
    monkeypatch.setattr(main, "run_wizard", lambda: 5)

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 5


def test_validate_runtime_dependencies_reflects_config_import_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "CONFIG_IMPORT_OK", True)
    assert main.validate_runtime_dependencies("web") == (True, None)

    monkeypatch.setattr(main, "CONFIG_IMPORT_OK", False)
    ok, message = main.validate_runtime_dependencies("cli")
    assert ok is False
    assert "cli.py" in str(message)


def test_preflight_warns_when_env_missing_and_provider_keys_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = SimpleNamespace(
        BASE_DIR=str(tmp_path),
        DATABASE_URL="",
        GEMINI_API_KEY="",
        OPENAI_API_KEY="",
        ANTHROPIC_API_KEY="",
    )
    monkeypatch.setattr(main, "cfg", cfg)

    main.preflight("gemini")
    gemini_out = capsys.readouterr().out
    assert ".env bulunamadı" in gemini_out
    assert "GEMINI_API_KEY boş" in gemini_out

    main.preflight("openai")
    openai_out = capsys.readouterr().out
    assert "OPENAI_API_KEY boş" in openai_out

    main.preflight("anthropic")
    anthropic_out = capsys.readouterr().out
    assert "ANTHROPIC_API_KEY boş" in anthropic_out


def test_execute_command_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(main.subprocess, "run", _raise)
    assert main.execute_command(["python", "cli.py"]) == 0


def test_execute_command_capture_output_handles_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(main, "_run_with_streaming", _raise)
    assert main.execute_command(["python", "cli.py"], capture_output=True) == 0


def test_execute_command_handles_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(main.subprocess, "run", _raise)
    assert main.execute_command(["python", "cli.py"]) == 1


def test_main_propagates_unexpected_runtime_error_from_wizard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["main.py"])

    def _boom():
        raise RuntimeError("wizard crash")

    monkeypatch.setattr(main, "run_wizard", _boom)
    with pytest.raises(RuntimeError, match="wizard crash"):
        main.main()


def test_main_exits_when_critical_settings_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cfg = SimpleNamespace(
        validate_critical_settings=lambda: False,
        init_telemetry=lambda **_kwargs: None,
        AI_PROVIDER="ollama",
        ACCESS_LEVEL="full",
        CODING_MODEL="qwen2.5-coder:7b",
        WEB_HOST="0.0.0.0",
        WEB_PORT=7860,
    )
    monkeypatch.setattr(main, "cfg", fake_cfg)
    monkeypatch.setattr("sys.argv", ["main.py", "--quick", "cli"])

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 2


def test_run_with_streaming_writes_stdout_stderr_and_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_stdout = _FakeStreamingPipe("hello stdout\n")
    fake_stderr = _FakeStreamingPipe("warn stderr\n")
    fake_process = _FakeStreamingProcess(stdout=fake_stdout, stderr=fake_stderr, return_code=0)
    popen_calls = {}

    def fake_popen(cmd, **kwargs):
        popen_calls["cmd"] = cmd
        popen_calls["kwargs"] = kwargs
        return fake_process

    monkeypatch.setattr(main.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(main, "cfg", SimpleNamespace(BASE_DIR=str(tmp_path)))

    rc = main._run_with_streaming(["python", "cli.py"], "logs/child.log")

    assert rc == 0
    assert popen_calls["cmd"] == ["python", "cli.py"]
    assert popen_calls["kwargs"]["stdout"] is main.subprocess.PIPE
    assert popen_calls["kwargs"]["stderr"] is main.subprocess.PIPE
    assert popen_calls["kwargs"]["text"] is True
    assert fake_stdout.closed_by_streamer is True
    assert fake_stderr.closed_by_streamer is True

    child_log = tmp_path / "logs" / "child.log"
    assert child_log.read_text(encoding="utf-8") == (
        "$ python cli.py\n\n"
        "[stdout] hello stdout\n"
        "[stderr] warn stderr\n"
        "\n[exit_code]\n0\n"
    )
    out = capsys.readouterr().out
    assert "[stdout]" in out
    assert "hello stdout" in out
    assert "[stderr]" in out
    assert "warn stderr" in out
    assert "Child process çıktısı kaydedildi" in out


def test_run_with_streaming_without_log_returns_child_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_process = _FakeStreamingProcess(
        stdout=_FakeStreamingPipe("only stdout\n"),
        stderr=_FakeStreamingPipe(""),
        return_code=3,
    )
    monkeypatch.setattr(main.subprocess, "Popen", lambda *_args, **_kwargs: fake_process)

    rc = main._run_with_streaming(["python", "cli.py"], None)

    assert rc == 3
    assert "only stdout" in capsys.readouterr().out


def test_run_with_streaming_rejects_missing_child_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_process = _FakeStreamingProcess(stdout=None, stderr=_FakeStreamingPipe(""))
    monkeypatch.setattr(main.subprocess, "Popen", lambda *_args, **_kwargs: fake_process)

    with pytest.raises(RuntimeError, match="stdout/stderr pipe"):
        main._run_with_streaming(["python", "cli.py"], None)


def test_run_with_streaming_terminates_process_still_running_after_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_process = _FakeStreamingProcess(
        stdout=_FakeStreamingPipe(""),
        stderr=_FakeStreamingPipe(""),
        return_code=0,
        running_after_wait=True,
    )
    monkeypatch.setattr(main.subprocess, "Popen", lambda *_args, **_kwargs: fake_process)

    assert main._run_with_streaming(["python", "cli.py"], None) == 0
    assert fake_process.terminated is True
    assert fake_process.wait_calls == [None, 3]


def test_run_with_streaming_kills_when_terminate_timeout_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TimeoutOnTerminateProcess(_FakeStreamingProcess):
        def __init__(self) -> None:
            super().__init__(
                stdout=_FakeStreamingPipe(""),
                stderr=_FakeStreamingPipe(""),
                return_code=4,
                running_after_wait=True,
            )
            self.kill_called = False

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls.append(timeout)
            if timeout is not None:
                raise TimeoutError("still running")
            return self.return_code

        def poll(self) -> int | None:
            return None

        def kill(self) -> None:
            self.kill_called = True

    fake_process = _TimeoutOnTerminateProcess()
    monkeypatch.setattr(main.subprocess, "Popen", lambda *_args, **_kwargs: fake_process)

    assert main._run_with_streaming(["python", "cli.py"], None) == 4
    assert fake_process.terminated is True
    assert fake_process.kill_called is True
    assert fake_process.wait_calls == [None, 3]
