import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest


@contextmanager
def _temporary_config_module(config_module):
    prev = sys.modules.get("config")
    sys.modules["config"] = config_module
    try:
        yield
    finally:
        if prev is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = prev


def _load_main_module():
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        AI_PROVIDER = "ollama"
        ACCESS_LEVEL = "full"
        WEB_HOST = "0.0.0.0"
        WEB_PORT = 7860
        CODING_MODEL = "qwen2.5-coder:7b"
        GEMINI_API_KEY = ""
        OLLAMA_URL = "http://localhost:11434/api"
        BASE_DIR = "."

        @staticmethod
        def initialize_directories():
            return None

    cfg_mod.Config = _Cfg
    with _temporary_config_module(cfg_mod):
        spec = importlib.util.spec_from_file_location("main_under_test_improvements", Path("main.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod


def test_dummy_config_defaults_are_aligned():
    main_mod = _load_main_module()

    cfg = main_mod.DummyConfig()

    assert cfg.WEB_HOST == "0.0.0.0"
    assert cfg.WEB_PORT == 7860
    assert cfg.CODING_MODEL == "qwen2.5-coder:7b"
    assert cfg.OLLAMA_URL == "http://localhost:11434/api"


def test_quick_mode_normalizes_log_level_and_uses_config_fallbacks(monkeypatch):
    main_mod = _load_main_module()
    captured = {}

    def _fake_execute(cmd, capture_output=False, child_log_path=None):
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["child_log_path"] = child_log_path
        return 0

    monkeypatch.setattr(main_mod, "execute_command", _fake_execute)
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--quick", "web", "--log", "INFO", "--capture-output", "--child-log", "logs/child.log"],
    )

    with pytest.raises(SystemExit) as exc:
        main_mod.main()

    assert exc.value.code == 0
    assert captured["cmd"] == [
        sys.executable,
        "web_server.py",
        "--provider",
        "ollama",
        "--level",
        "full",
        "--log",
        "info",
        "--host",
        "0.0.0.0",
        "--port",
        "7860",
    ]
    assert captured["capture_output"] is True
    assert captured["child_log_path"] == "logs/child.log"


def test_main_rejects_invalid_port_value(monkeypatch):
    main_mod = _load_main_module()
    monkeypatch.setattr(sys, "argv", ["main.py", "--quick", "web", "--port", "70000"])

    with pytest.raises(SystemExit) as exc:
        main_mod.main()

    assert exc.value.code == 2
