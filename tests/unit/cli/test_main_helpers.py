"""Unit tests for launcher helper functions in main.py."""

from __future__ import annotations

import builtins
import importlib.util
import io
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from main import _safe_choice, _safe_host, _safe_port, _safe_text, build_command


class _FakeStreamingPipe(io.StringIO):
    """StringIO pipe double that records close without breaking getvalue assertions."""

    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.closed_by_streamer = False

    def close(self) -> None:  # pragma: no cover - behavior asserted through flag
        self.closed_by_streamer = True


def _load_main_module_with_config(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    config_module: types.ModuleType | None = None,
    *,
    fail_config_import: bool = False,
):
    """Load main.py under an isolated module name to exercise import-time config branches."""
    spec = importlib.util.spec_from_file_location(module_name, Path(main.__file__))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    if config_module is not None:
        monkeypatch.setitem(sys.modules, "config", config_module)
    elif fail_config_import:
        monkeypatch.delitem(sys.modules, "config", raising=False)
        real_import = builtins.__import__

        def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "config":
                raise ImportError("config intentionally unavailable")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", _guarded_import)

    spec.loader.exec_module(module)
    return module


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


def test_import_time_config_success_initializes_directories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_config = types.ModuleType("config")

    class _ConfigWithInit:
        def __init__(self) -> None:
            self.initialized = False

        def initialize_directories(self) -> None:
            self.initialized = True

    fake_config.Config = _ConfigWithInit

    loaded = _load_main_module_with_config(monkeypatch, "main_config_success", fake_config)

    assert loaded.CONFIG_IMPORT_OK is True
    assert loaded.cfg.initialized is True


def test_import_time_config_success_without_initialize_directories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_config = types.ModuleType("config")

    class _ConfigWithoutInit:
        pass

    fake_config.Config = _ConfigWithoutInit

    loaded = _load_main_module_with_config(monkeypatch, "main_config_no_init", fake_config)

    assert loaded.CONFIG_IMPORT_OK is True
    assert isinstance(loaded.cfg, _ConfigWithoutInit)


def test_import_time_config_failure_uses_dummy_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    loaded = _load_main_module_with_config(
        monkeypatch, "main_config_missing", fail_config_import=True
    )

    assert loaded.CONFIG_IMPORT_OK is False
    assert isinstance(loaded.cfg, loaded.DummyConfig)
    assert loaded.cfg.initialize_directories() is None
    assert "varsayılan ayarlar kullanılıyor" in capsys.readouterr().out


def test_print_banner_outputs_launcher_title(capsys: pytest.CaptureFixture[str]) -> None:
    main.print_banner()

    out = capsys.readouterr().out
    assert "SİDAR AKILLI BAŞLATICI" in out
    assert "Hoş geldiniz" in out


def test_ask_choice_reprompts_then_returns_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = iter(["bad", ""])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    result = main.ask_choice(
        "Mod seç",
        {"1": ("Web", "web"), "2": ("CLI", "cli")},
        "1",
    )

    assert result == "web"
    assert "Geçersiz seçim" in capsys.readouterr().out


def test_ask_choice_returns_selected_option(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "input", lambda _prompt: "2")

    assert main.ask_choice("Mod seç", {"1": ("Web", "web"), "2": ("CLI", "cli")}, "1") == "cli"


def test_ask_text_and_confirm_defaults_and_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["", "custom text", "", "n", "evet"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(answers))

    assert main.ask_text("Model", "qwen2.5-coder:7b") == "qwen2.5-coder:7b"
    assert main.ask_text("Model", "qwen2.5-coder:7b") == "custom text"
    assert main.confirm("Devam?", default_yes=False) is False
    assert main.confirm("Devam?", default_yes=True) is False
    assert main.confirm("Devam?", default_yes=False) is True


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


def test_safe_text_returns_default_for_none() -> None:
    assert _safe_text(None, default="fallback") == "fallback"


def test_safe_host_validates_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.delenv("SIDAR_ALLOW_PUBLIC_BIND", raising=False)

    assert _safe_host("127.0.0.1") == "127.0.0.1"
    assert _safe_host("0.0.0.0") == "0.0.0.0"
    assert _safe_host("bad host!") == "127.0.0.1"

    monkeypatch.setenv("SIDAR_ENV", "production")
    assert _safe_host("0.0.0.0") == "127.0.0.1"

    monkeypatch.setenv("SIDAR_ALLOW_PUBLIC_BIND", "true")
    assert _safe_host("0.0.0.0") == "0.0.0.0"


def test_build_command_rejects_invalid_provider_level_and_log() -> None:
    with pytest.raises(ValueError, match="provider"):
        build_command("web", "bad", "full", "info", {})
    with pytest.raises(ValueError, match="level"):
        build_command("web", "ollama", "bad", "info", {})
    with pytest.raises(ValueError, match="log"):
        build_command("web", "ollama", "full", "trace", {})


def test_build_command_cli_non_ollama_omits_model() -> None:
    cmd = build_command("cli", "openai", "sandbox", "warning", {"model": "ignored"})

    assert "cli.py" in cmd
    assert "--model" not in cmd


def test_launcher_doctor_preflight_prints_actionable_guidance(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import core.doctor as doctor

    monkeypatch.setattr(
        doctor,
        "check_database_env",
        lambda: SimpleNamespace(
            name="database_env", status="pass", message="db env ok", details={}
        ),
    )
    monkeypatch.setattr(
        doctor,
        "check_database_connectivity",
        lambda: SimpleNamespace(
            name="database_connectivity",
            status="warn",
            message="auth failed",
            details={
                "root_cause_hints": ["old volume password"],
                "remediation_steps": ["run ALTER USER"],
                "recommended_commands": ["docker compose ps postgres"],
            },
        ),
    )
    monkeypatch.setattr(
        doctor,
        "check_rag_readiness",
        lambda: SimpleNamespace(
            name="rag_readiness",
            status="warn",
            message="RAG empty",
            details={"recommended_commands": ["belge ekle <url>"]},
        ),
    )
    monkeypatch.setattr(
        doctor,
        "check_gpu_memory_config",
        lambda: SimpleNamespace(
            name="gpu_memory_config",
            status="warn",
            message="VRAM normalized",
            details={
                "recommended_commands": [
                    "uv run python -m scripts.bootstrap_env --profile development"
                ]
            },
        ),
    )

    main._run_launcher_doctor_preflight()

    output = capsys.readouterr().out
    assert "Doctor/database_connectivity" in output
    assert "old volume password" in output
    assert "run ALTER USER" in output
    assert "belge ekle <url>" in output
    assert "Doctor/gpu_memory_config" in output
    assert "scripts.bootstrap_env" in output


def test_launcher_doctor_preflight_revalidates_successful_auto_fix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import core.doctor as doctor

    calls = {"database_env": 0}

    def _database_check() -> SimpleNamespace:
        calls["database_env"] += 1
        if calls["database_env"] == 1:
            return SimpleNamespace(
                name="database_env",
                status="fail",
                message="password drift",
                details={"auto_fix": "uv run python -m scripts.sync_database_passwords"},
            )
        return SimpleNamespace(
            name="database_env",
            status="pass",
            message="database environment looks secure",
            details={},
        )

    monkeypatch.setattr(doctor, "check_database_env", _database_check)
    monkeypatch.setattr(
        doctor,
        "check_database_connectivity",
        lambda: SimpleNamespace(
            name="database_connectivity", status="pass", message="ok", details={}
        ),
    )
    monkeypatch.setattr(
        doctor,
        "check_rag_readiness",
        lambda: SimpleNamespace(name="rag_readiness", status="pass", message="ok", details={}),
    )
    monkeypatch.setattr(
        doctor,
        "check_gpu_memory_config",
        lambda: SimpleNamespace(name="gpu_memory_config", status="pass", message="ok", details={}),
    )

    def _auto_fix(check: SimpleNamespace, check_func=None) -> bool:
        if check.name != "database_env":
            return False
        main._revalidate_doctor_check_after_auto_fix(check_func)
        return True

    monkeypatch.setattr(main, "_run_doctor_auto_fix", _auto_fix)

    main._run_launcher_doctor_preflight()

    output = capsys.readouterr().out
    assert calls["database_env"] == 2
    assert "Auto-fix sonrası yeniden doğrulama" in output
    assert "Auto-fix Doctor/database_env kontrolünü düzeltti" in output


def test_launcher_doctor_preflight_reports_failed_revalidation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import core.doctor as doctor

    calls = {"database_env": 0}

    def _database_check() -> SimpleNamespace:
        calls["database_env"] += 1
        return SimpleNamespace(
            name="database_env",
            status="fail",
            message=f"password drift attempt {calls['database_env']}",
            details={"auto_fix": "uv run python -m scripts.sync_database_passwords"},
        )

    monkeypatch.setattr(doctor, "check_database_env", _database_check)
    monkeypatch.setattr(
        doctor,
        "check_database_connectivity",
        lambda: SimpleNamespace(
            name="database_connectivity", status="pass", message="ok", details={}
        ),
    )
    monkeypatch.setattr(
        doctor,
        "check_rag_readiness",
        lambda: SimpleNamespace(name="rag_readiness", status="pass", message="ok", details={}),
    )
    monkeypatch.setattr(
        doctor,
        "check_gpu_memory_config",
        lambda: SimpleNamespace(name="gpu_memory_config", status="pass", message="ok", details={}),
    )

    def _auto_fix(check: SimpleNamespace, check_func=None) -> bool:
        if check.name != "database_env":
            return False
        main._revalidate_doctor_check_after_auto_fix(check_func)
        return True

    monkeypatch.setattr(main, "_run_doctor_auto_fix", _auto_fix)

    main._run_launcher_doctor_preflight()

    output = capsys.readouterr().out
    assert calls["database_env"] == 2
    assert "Auto-fix sonrası yeniden doğrulama" in output
    assert "Auto-fix Doctor/database_env sorununu gideremedi" in output
    assert "password drift attempt 2" in output


def test_launcher_doctor_preflight_ignores_stale_revalidation_cache(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import core.doctor as doctor

    calls = {"database_env": 0, "connectivity": 0, "rag": 0, "gpu": 0}

    main._LAST_DOCTOR_AUTO_FIX_REVALIDATION = SimpleNamespace(
        name="database_env",
        status="pass",
        message="stale success from previous check",
        details={},
    )

    def _database_check() -> SimpleNamespace:
        calls["database_env"] += 1
        return SimpleNamespace(
            name="database_env",
            status="fail",
            message="password drift",
            details={"auto_fix": "uv run python -m scripts.sync_database_passwords"},
        )

    def _connectivity_check() -> SimpleNamespace:
        calls["connectivity"] += 1
        return SimpleNamespace(
            name="database_connectivity", status="pass", message="ok", details={}
        )

    def _rag_check() -> SimpleNamespace:
        calls["rag"] += 1
        return SimpleNamespace(name="rag_readiness", status="pass", message="ok", details={})

    def _gpu_check() -> SimpleNamespace:
        calls["gpu"] += 1
        return SimpleNamespace(name="gpu_memory_config", status="pass", message="ok", details={})

    monkeypatch.setattr(doctor, "check_database_env", _database_check)
    monkeypatch.setattr(doctor, "check_database_connectivity", _connectivity_check)
    monkeypatch.setattr(doctor, "check_rag_readiness", _rag_check)
    monkeypatch.setattr(doctor, "check_gpu_memory_config", _gpu_check)
    monkeypatch.setattr(main, "_run_doctor_auto_fix", lambda *_args, **_kwargs: True)

    main._run_launcher_doctor_preflight()

    output = capsys.readouterr().out
    assert calls == {"database_env": 1, "connectivity": 0, "rag": 0, "gpu": 1}
    assert "stale success from previous check" not in output
    assert "database_connectivity ve rag_readiness kontrolleri atlandı" in output


def test_launcher_doctor_preflight_skips_database_dependents_after_failed_database_env(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import core.doctor as doctor

    calls = {"database_env": 0, "connectivity": 0, "rag": 0, "gpu": 0}

    def _database_check() -> SimpleNamespace:
        calls["database_env"] += 1
        return SimpleNamespace(
            name="database_env",
            status="fail",
            message="password drift",
            details={},
        )

    def _connectivity_check() -> SimpleNamespace:
        calls["connectivity"] += 1
        return SimpleNamespace(
            name="database_connectivity", status="pass", message="ok", details={}
        )

    def _rag_check() -> SimpleNamespace:
        calls["rag"] += 1
        return SimpleNamespace(name="rag_readiness", status="pass", message="ok", details={})

    def _gpu_check() -> SimpleNamespace:
        calls["gpu"] += 1
        return SimpleNamespace(name="gpu_memory_config", status="pass", message="ok", details={})

    monkeypatch.setattr(doctor, "check_database_env", _database_check)
    monkeypatch.setattr(doctor, "check_database_connectivity", _connectivity_check)
    monkeypatch.setattr(doctor, "check_rag_readiness", _rag_check)
    monkeypatch.setattr(doctor, "check_gpu_memory_config", _gpu_check)
    monkeypatch.setattr(main, "_run_doctor_auto_fix", lambda *_args, **_kwargs: False)

    main._run_launcher_doctor_preflight()

    output = capsys.readouterr().out
    assert calls == {"database_env": 1, "connectivity": 0, "rag": 0, "gpu": 1}
    assert "database_connectivity ve rag_readiness kontrolleri atlandı" in output


def test_revalidate_doctor_auto_fix_reloads_doctor_source_definitions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql://sidar:new@localhost:5432/sidar\n", encoding="utf-8"
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:old@localhost:5432/sidar")
    monkeypatch.setattr(main, "_reload_config_environment", lambda **_kwargs: False)

    source_details = {
        "env_source_definitions": {
            "DATABASE_URL": [
                {"label": "base", "path": str(env_file), "override": "False"},
            ]
        }
    }

    def _database_check() -> SimpleNamespace:
        return SimpleNamespace(
            name="database_env",
            status="pass" if ":new@" in os.environ["DATABASE_URL"] else "fail",
            message=os.environ["DATABASE_URL"],
            details={},
        )

    updated = main._revalidate_doctor_check_after_auto_fix(_database_check, source_details)

    assert updated is not None
    assert updated.status == "pass"
    assert os.environ["DATABASE_URL"] == "postgresql://sidar:new@localhost:5432/sidar"


def test_revalidate_doctor_auto_fix_reloads_environment_before_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reload_calls: list[tuple[str | None, str]] = []
    monkeypatch.setattr(main, "cfg", SimpleNamespace(BASE_DIR=str(tmp_path)))
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:old@localhost:5432/sidar")

    def _reload_config_environment(*, profile: str | None, reason: str) -> bool:
        reload_calls.append((profile, reason))
        monkeypatch.setenv("DATABASE_URL", "postgresql://sidar:new@localhost:5432/sidar")
        return True

    def _database_check() -> SimpleNamespace:
        return SimpleNamespace(
            name="database_env",
            status="pass" if ":new@" in os.environ["DATABASE_URL"] else "fail",
            message=os.environ["DATABASE_URL"],
            details={},
        )

    monkeypatch.setattr(main, "_reload_config_environment", _reload_config_environment)

    updated = main._revalidate_doctor_check_after_auto_fix(_database_check)

    assert updated is not None
    assert updated.status == "pass"
    assert reload_calls == [(None, "Doctor auto-fix")]


def test_doctor_auto_fix_runs_seed_command_in_subprocess(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}
    check = SimpleNamespace(
        name="rag_readiness",
        status="warn",
        details={"auto_fix": "uv run python -m scripts.seed_rag --metadata-only"},
    )
    monkeypatch.setattr(main.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(main, "confirm", lambda *_args, **_kwargs: True)

    def _run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(main.subprocess, "run", _run)

    assert main._run_doctor_auto_fix(check) is True
    assert seen["cmd"] == ["uv", "run", "python", "-m", "scripts.seed_rag", "--metadata-only"]
    assert seen["kwargs"]["env"]["SIDAR_CONFIG_QUIET"] == "true"
    assert "Auto-fix tamamlandı" in capsys.readouterr().out


def test_doctor_auto_fix_uses_subprocess_for_other_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}
    check = SimpleNamespace(
        name="database_env",
        status="fail",
        details={"auto_fix": "uv run python -m scripts.sync_database_passwords"},
    )
    monkeypatch.setattr(main.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(main, "confirm", lambda *_args, **_kwargs: True)

    def _run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(main.subprocess, "run", _run)

    assert main._run_doctor_auto_fix(check) is True
    assert seen["cmd"] == ["uv", "run", "python", "-m", "scripts.sync_database_passwords"]
    assert seen["kwargs"]["env"]["SIDAR_CONFIG_QUIET"] == "true"
    assert "Auto-fix tamamlandı" in capsys.readouterr().out


def test_doctor_auto_fix_steps_revalidate_after_each_step_until_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    commands: list[list[str]] = []
    revalidation_calls = {"count": 0}
    check = SimpleNamespace(
        name="rag_readiness",
        status="warn",
        details={
            "auto_fix": "uv run python -m scripts.sync_database_passwords",
            "auto_fix_steps": [
                "uv run python -m scripts.sync_database_passwords",
                "uv run python -m scripts.seed_rag",
                "uv run python -m scripts.unused_follow_up",
            ],
        },
    )
    monkeypatch.setattr(main.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(main, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(main, "_reload_environment_after_auto_fix", lambda *_args: True)

    def _run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(cmd)
        return SimpleNamespace(returncode=0)

    def _check_func() -> SimpleNamespace:
        revalidation_calls["count"] += 1
        if revalidation_calls["count"] == 1:
            return SimpleNamespace(
                name="rag_readiness", status="warn", message="index still missing", details={}
            )
        return SimpleNamespace(name="rag_readiness", status="pass", message="ok", details={})

    monkeypatch.setattr(main.subprocess, "run", _run)

    assert main._run_doctor_auto_fix(check, _check_func) is True
    assert commands == [
        ["uv", "run", "python", "-m", "scripts.sync_database_passwords"],
        ["uv", "run", "python", "-m", "scripts.seed_rag"],
    ]
    assert revalidation_calls["count"] == 2
    output = capsys.readouterr().out
    assert "scripts.unused_follow_up" not in output
    assert "Auto-fix Doctor/rag_readiness kontrolünü düzeltti" in output


def test_doctor_auto_fix_skips_without_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    check = SimpleNamespace(
        name="rag_readiness",
        status="warn",
        details={"auto_fix": "uv run python -m scripts.seed_rag"},
    )
    monkeypatch.setattr(main.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(main, "confirm", lambda *_args, **_kwargs: pytest.fail("should not prompt"))

    assert main._run_doctor_auto_fix(check) is False


def test_preflight_offers_development_bootstrap_from_preflight_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("DATABASE_URL=sqlite:///x", encoding="utf-8")
    monkeypatch.setattr(
        main,
        "cfg",
        SimpleNamespace(
            BASE_DIR=str(tmp_path), DATABASE_URL="sqlite:///db", OLLAMA_URL="http://ollama"
        ),
    )
    called = {"bootstrap": 0}
    monkeypatch.setattr(
        main, "_maybe_bootstrap_development_env", lambda: called.__setitem__("bootstrap", 1) or True
    )
    monkeypatch.setattr(main, "_run_launcher_doctor_preflight", lambda: None)

    main.preflight("openai")

    assert called["bootstrap"] == 1


def test_preflight_reports_existing_env_and_database_url_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / ".env").write_text("DATABASE_URL=sqlite:///x", encoding="utf-8")
    monkeypatch.setattr(
        main,
        "cfg",
        SimpleNamespace(BASE_DIR=str(tmp_path), DATABASE_URL="not-a-url"),
    )

    main.preflight("gemini")

    assert "DATABASE_URL beklenen şema biçiminde değil" in caplog.text


def test_preflight_ollama_success_and_non_200(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class _Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    class _Client:
        statuses = [200, 503]

        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, url: str) -> _Response:
            assert url.endswith("/api/tags")
            return _Response(self.statuses.pop(0))

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = _Client
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    monkeypatch.setattr(
        main,
        "cfg",
        SimpleNamespace(
            BASE_DIR=str(tmp_path), DATABASE_URL="sqlite:///db", OLLAMA_URL="http://ollama"
        ),
    )

    main.preflight("ollama")
    main.preflight("ollama")

    out = capsys.readouterr().out
    assert "Ollama erişimi başarılı" in out
    assert "Ollama yanıt kodu: 503" in out


def test_preflight_ollama_import_error_and_runtime_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        main,
        "cfg",
        SimpleNamespace(
            BASE_DIR=str(tmp_path), DATABASE_URL="sqlite:///db", OLLAMA_URL="http://ollama"
        ),
    )
    real_import = builtins.__import__

    def _missing_httpx(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "httpx":
            raise ImportError("missing httpx")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _missing_httpx)
    main.preflight("ollama")
    assert "httpx" in capsys.readouterr().out

    class _BoomClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            raise RuntimeError("network down")

        def __exit__(self, *_args: object) -> None:
            return None

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = _BoomClient
    monkeypatch.setattr(builtins, "__import__", real_import)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    main.preflight("ollama")
    assert "Ollama erişimi doğrulanamadı" in capsys.readouterr().out


def test_run_wizard_cli_ollama_runs_without_extra_final_confirm(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(main, "print_banner", lambda: None)
    choices = iter(["cli", "ollama", "sandbox", "debug"])
    seen: dict[str, object] = {}
    monkeypatch.setattr(main, "ask_choice", lambda *args, **kwargs: next(choices))
    monkeypatch.setattr(main, "ask_text", lambda *args, **kwargs: "qwen2.5-coder:7b")
    monkeypatch.setattr(main, "preflight", lambda _provider: None)
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (True, None))
    monkeypatch.setattr(
        main, "confirm", lambda *_args, **_kwargs: pytest.fail("final confirm should not run")
    )
    monkeypatch.setattr(
        main, "_launcher_session_path", lambda _base_dir=None: tmp_path / ".sidar_session.json"
    )

    def _execute(cmd: list[str]) -> int:
        seen["cmd"] = cmd
        return 0

    monkeypatch.setattr(main, "execute_command", _execute)

    assert main.run_wizard() == 0
    assert "Başlatılacak komut" in capsys.readouterr().out
    assert seen["cmd"][-2:] == ["--model", "qwen2.5-coder:7b"]
    assert (tmp_path / ".sidar_session.json").exists()


def test_run_wizard_web_executes_confirmed_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "print_banner", lambda: None)
    choices = iter(["web", "openai", "full", "info"])
    text_answers = iter(["127.0.0.1", "9000"])
    seen: dict[str, object] = {}
    monkeypatch.setattr(main, "ask_choice", lambda *args, **kwargs: next(choices))
    monkeypatch.setattr(main, "ask_text", lambda *args, **kwargs: next(text_answers))
    monkeypatch.setattr(main, "preflight", lambda _provider: None)
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (True, None))
    monkeypatch.setattr(main, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(main, "_save_launcher_session", lambda _selection: Path("/tmp/session"))

    def _execute(cmd: list[str]) -> int:
        seen["cmd"] = cmd
        return 6

    monkeypatch.setattr(main, "execute_command", _execute)

    assert main.run_wizard() == 6
    assert seen["cmd"][-4:] == ["--host", "127.0.0.1", "--port", "9000"]


def test_launcher_session_save_load_normalizes_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        main,
        "cfg",
        SimpleNamespace(
            AI_PROVIDER="ollama",
            ACCESS_LEVEL="full",
            CODING_MODEL="qwen2.5-coder:7b",
            WEB_HOST="127.0.0.1",
            WEB_PORT=7860,
        ),
    )
    session_path = tmp_path / ".sidar_session.json"

    saved_path = main._save_launcher_session(
        {
            "mode": "web",
            "provider": "bad-provider",
            "level": "sandbox",
            "log": "debug",
            "extra_args": {"host": "127.0.0.1", "port": "9999"},
        },
        session_path,
    )
    loaded = main._load_launcher_session(saved_path)

    assert saved_path == session_path
    assert loaded is not None
    assert loaded["provider"] == "ollama"
    assert loaded["level"] == "sandbox"
    assert loaded["extra_args"]["port"] == "9999"


def test_launcher_child_env_quiets_config_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIDAR_CONFIG_QUIET", "false")
    monkeypatch.setenv("CUSTOM_ENV", "kept")

    child_env = main._launcher_child_env()

    assert child_env["SIDAR_CONFIG_QUIET"] == "true"
    assert child_env["SIDAR_LAUNCHED_BY_MAIN"] == "true"
    assert child_env["CUSTOM_ENV"] == "kept"


def test_maybe_bootstrap_development_env_runs_bootstrap_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}
    reload_calls: list[str] = []
    monkeypatch.setattr(main, "cfg", SimpleNamespace(BASE_DIR=str(tmp_path)))
    monkeypatch.setattr(main.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(main, "confirm", lambda *_args, **_kwargs: True)

    def _run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(main.subprocess, "run", _run)
    monkeypatch.setattr(
        main,
        "_reload_environment_after_bootstrap",
        lambda profile: reload_calls.append(profile) or True,
    )

    assert main._maybe_bootstrap_development_env() is True
    assert seen["cmd"] == [
        "uv",
        "run",
        "python",
        "-m",
        "scripts.bootstrap_env",
        "--profile",
        "development",
    ]
    assert seen["kwargs"]["env"]["SIDAR_CONFIG_QUIET"] == "true"
    assert seen["kwargs"]["env"]["SIDAR_LAUNCHED_BY_MAIN"] == "true"
    assert reload_calls == ["development"]
    assert "bootstrap tamamlandı" in capsys.readouterr().out


def test_maybe_bootstrap_development_env_skips_non_interactive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(main, "cfg", SimpleNamespace(BASE_DIR=str(tmp_path)))
    monkeypatch.setattr(main.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(main, "confirm", lambda *_args, **_kwargs: pytest.fail("should not prompt"))

    assert main._maybe_bootstrap_development_env() is False


def test_execute_command_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def _run(cmd: list[str], **kwargs: object) -> None:
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs

    monkeypatch.setattr(main.subprocess, "run", _run)

    assert main.execute_command(["python", "cli.py"]) == 0
    assert seen["cmd"] == ["python", "cli.py"]
    assert seen["kwargs"]["env"]["SIDAR_CONFIG_QUIET"] == "true"


def test_main_quick_mode_without_telemetry_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main,
        "cfg",
        SimpleNamespace(
            validate_critical_settings=lambda: True,
            AI_PROVIDER="openai",
            ACCESS_LEVEL="sandbox",
            CODING_MODEL="qwen2.5-coder:7b",
            WEB_HOST="127.0.0.1",
            WEB_PORT=7860,
        ),
    )
    monkeypatch.setattr("sys.argv", ["main.py", "--quick", "cli"])
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (True, None))
    monkeypatch.setattr(main, "execute_command", lambda *_args, **_kwargs: 0)

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0


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


def test_main_skip_wizard_uses_default_selection_with_cli_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "main.py",
            "--skip-wizard",
            "--capture-output",
            "--provider",
            "gemini",
            "--host",
            "127.0.0.1",
        ],
    )
    monkeypatch.setattr(
        main,
        "cfg",
        SimpleNamespace(
            validate_critical_settings=lambda: True,
            AI_PROVIDER="openai",
            ACCESS_LEVEL="sandbox",
            CODING_MODEL="qwen2.5-coder:7b",
            WEB_HOST="127.0.0.1",
            WEB_PORT=9001,
        ),
    )
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (True, None))
    seen: dict[str, object] = {}

    def _execute_selection(selection: dict[str, object], **kwargs: object) -> int:
        seen["selection"] = selection
        seen["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(main, "_execute_launch_selection", _execute_selection)

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0
    assert seen["selection"]["mode"] == "web"
    assert seen["selection"]["provider"] == "gemini"
    assert seen["selection"]["extra_args"]["port"] == "9001"
    assert seen["kwargs"]["capture_output"] is True


def test_main_last_replays_cached_session(monkeypatch: pytest.MonkeyPatch) -> None:
    cached = {
        "mode": "cli",
        "provider": "ollama",
        "level": "full",
        "log": "debug",
        "extra_args": {"model": "qwen2.5-coder:7b"},
    }
    monkeypatch.setattr("sys.argv", ["main.py", "--last", "--child-log", "logs/child.log"])
    monkeypatch.setattr(main, "_load_launcher_session", lambda: cached)
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (True, None))
    seen: dict[str, object] = {}

    def _execute_selection(selection: dict[str, object], **kwargs: object) -> int:
        seen["selection"] = selection
        seen["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(main, "_execute_launch_selection", _execute_selection)

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0
    assert seen["selection"] == cached
    assert seen["kwargs"]["child_log_path"] == "logs/child.log"


def test_main_rejects_conflicting_launch_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", "--quick", "web", "--last"])

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 2


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
    monkeypatch.setattr(main, "_save_launcher_session", lambda _selection: Path("/tmp/session"))
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
    assert popen_calls["kwargs"]["env"]["SIDAR_CONFIG_QUIET"] == "true"
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


def test_stream_pipe_writes_to_file_without_mirror(tmp_path) -> None:
    """Branch 265->261: mirror=False ise print atlanır ve döngü sonraki satıra geçer."""
    pipe = _FakeStreamingPipe("line1\nline2\n")
    log_path = tmp_path / "pipe.log"
    with open(log_path, "w", encoding="utf-8") as f:
        main._stream_pipe(pipe, f, "[stdout]", main.CYAN, mirror=False)
    contents = log_path.read_text(encoding="utf-8")
    assert "[stdout] line1" in contents
    assert "[stdout] line2" in contents
    assert pipe.closed_by_streamer is True


def test_run_wizard_cli_non_ollama_provider_skips_ollama_model_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Branch 392->405: mode=cli ama provider != ollama → elif (web) bloğu da atlanır."""
    monkeypatch.setattr(main, "print_banner", lambda: None)
    choices = iter(["cli", "openai", "sandbox", "info"])
    monkeypatch.setattr(main, "ask_choice", lambda *args, **kwargs: next(choices))
    ask_text_called = {"n": 0}

    def _ask_text(*_args, **_kwargs):
        ask_text_called["n"] += 1
        return ""

    monkeypatch.setattr(main, "ask_text", _ask_text)
    monkeypatch.setattr(main, "preflight", lambda _provider: None)
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (True, None))
    monkeypatch.setattr(
        main, "confirm", lambda *_args, **_kwargs: pytest.fail("final confirm should not run")
    )
    monkeypatch.setattr(main, "_save_launcher_session", lambda _selection: Path("/tmp/session"))
    monkeypatch.setattr(main, "execute_command", lambda _cmd: 0)

    assert main.run_wizard() == 0
    # cli + non-ollama → ne ollama prompt ne de web prompt çalışmalı
    assert ask_text_called["n"] == 0


def test_execute_command_capture_output_zero_returns_without_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Branch 433->435: capture_output ve return_code==0 ise hata mesajı yazılmaz."""
    monkeypatch.setattr(main, "_run_with_streaming", lambda _cmd, _log: 0)

    rc = main.execute_command(["python", "cli.py"], capture_output=True)
    out = capsys.readouterr().out

    assert rc == 0
    assert "Program hata ile sonlandı" not in out


def test_main_quick_mode_with_valid_port_continues_through_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Branch 493->501: --port geçerli aralıktaysa port doğrulamasından sorunsuz geçer."""
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--quick", "web", "--provider", "openai", "--port", "9001"],
    )
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda _mode: (True, None))

    captured: dict[str, object] = {}

    def fake_execute(cmd: list[str], capture_output=False, child_log_path=None):
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(main, "execute_command", fake_execute)

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0
    assert "9001" in captured["cmd"]
