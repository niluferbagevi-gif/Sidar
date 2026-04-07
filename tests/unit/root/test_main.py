import pytest

import main


class _LauncherCfg:
    AI_PROVIDER = "ollama"
    ACCESS_LEVEL = "full"
    CODING_MODEL = "qwen2.5-coder:7b"
    WEB_HOST = "0.0.0.0"
    WEB_PORT = 7860

    def validate_critical_settings(self):
        return True



def test_launcher_main_quick_cli_executes_command(monkeypatch):
    captured = {}

    monkeypatch.setattr(main, "cfg", _LauncherCfg())
    monkeypatch.setattr(main, "validate_runtime_dependencies", lambda mode: (True, None))

    def _fake_execute(cmd, capture_output=False, child_log_path=None):
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["child_log_path"] = child_log_path
        return 0

    monkeypatch.setattr(main, "execute_command", _fake_execute)
    monkeypatch.setattr(
        main.sys,
        "argv",
        ["main.py", "--quick", "cli", "--provider", "ollama", "--level", "full", "--log", "info"],
    )

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0
    assert captured["cmd"][1] == "cli.py"
    assert "--provider" in captured["cmd"]



def test_launcher_main_without_quick_runs_wizard(monkeypatch):
    monkeypatch.setattr(main, "cfg", _LauncherCfg())
    monkeypatch.setattr(main, "run_wizard", lambda: 0)
    monkeypatch.setattr(main.sys, "argv", ["main.py"])

    with pytest.raises(SystemExit) as exc:
        main.main()

    assert exc.value.code == 0
