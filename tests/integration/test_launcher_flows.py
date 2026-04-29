import importlib
import sys
from types import SimpleNamespace


def _load_launcher_modules(monkeypatch):
    fake_config_mod = SimpleNamespace(
        Config=lambda: SimpleNamespace(
            AI_PROVIDER="openai",
            ACCESS_LEVEL="sandbox",
            CODING_MODEL="m",
            WEB_HOST="127.0.0.1",
            WEB_PORT=8080,
            BASE_DIR=".",
            initialize_directories=lambda: None,
            validate_critical_settings=lambda: True,
            init_telemetry=lambda **_kwargs: None,
        )
    )
    monkeypatch.setitem(sys.modules, "config", fake_config_mod)
    main_mod = importlib.reload(importlib.import_module("main"))
    gui_mod = importlib.reload(importlib.import_module("gui_launcher"))
    return main_mod, gui_mod


def test_main_quick_web_flow_executes_command(monkeypatch):
    launcher_main, _ = _load_launcher_modules(monkeypatch)
    calls = {}

    monkeypatch.setattr(
        launcher_main.argparse.ArgumentParser,
        "parse_args",
        lambda _self: SimpleNamespace(
            quick="web",
            provider="openai",
            level="sandbox",
            model=None,
            host="0.0.0.0",
            port="7860",
            log="info",
            capture_output=False,
            child_log=None,
        ),
    )
    monkeypatch.setattr(launcher_main, "validate_runtime_dependencies", lambda _mode: (True, None))
    monkeypatch.setattr(
        launcher_main,
        "build_command",
        lambda mode, provider, level, log, extra: ["python", mode, provider, level, log, extra["host"], extra["port"]],
    )

    def _exec(cmd, capture_output=False, child_log_path=None):
        calls["cmd"] = cmd
        return 0

    monkeypatch.setattr(launcher_main, "execute_command", _exec)
    monkeypatch.setattr(launcher_main.sys, "exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))

    try:
        launcher_main.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert calls["cmd"][:5] == ["python", "web", "openai", "sandbox", "info"]


def test_gui_launcher_end_to_end_success(monkeypatch):
    _, gui_launcher = _load_launcher_modules(monkeypatch)
    monkeypatch.setattr(gui_launcher, "preflight", lambda _provider: None)
    monkeypatch.setattr(gui_launcher, "build_command", lambda *args: ["python", "web_server.py"])
    monkeypatch.setattr(gui_launcher, "execute_command", lambda _cmd: 0)

    out = gui_launcher.launch_from_gui("web", "ollama", "full", "info")
    assert out["status"] == "success"
