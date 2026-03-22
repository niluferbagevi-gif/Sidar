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

def test_quick_mode_fails_fast_when_config_import_is_missing(monkeypatch, capsys):
    main_mod = _load_main_module()
    main_mod.CONFIG_IMPORT_OK = False

    def _unexpected_execute(*_args, **_kwargs):
        raise AssertionError("execute_command should not run when config import is missing")

    monkeypatch.setattr(main_mod, "execute_command", _unexpected_execute)
    monkeypatch.setattr(sys, "argv", ["main.py", "--quick", "web"])

    with pytest.raises(SystemExit) as exc:
        main_mod.main()

    out = capsys.readouterr().out
    assert exc.value.code == 2
    assert "config.py yüklenemediği için web_server.py güvenli şekilde başlatılamıyor" in out


def test_run_wizard_fails_fast_when_runtime_dependencies_are_missing(monkeypatch, capsys):
    main_mod = _load_main_module()
    main_mod.CONFIG_IMPORT_OK = False

    answers = iter(["1", "1", "1", "1", "127.0.0.1", "7860"])
    monkeypatch.setattr(main_mod, "print_banner", lambda: None)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(main_mod, "preflight", lambda _provider: None)

    def _unexpected_execute(*_args, **_kwargs):
        raise AssertionError("execute_command should not run when runtime dependencies are missing")

    monkeypatch.setattr(main_mod, "execute_command", _unexpected_execute)

    assert main_mod.run_wizard() == 2

    out = capsys.readouterr().out
    assert "config.py yüklenemediği için web_server.py güvenli şekilde başlatılamıyor" in out


def test_preflight_warns_for_malformed_database_url(monkeypatch, tmp_path):
    main_mod = _load_main_module()
    main_mod.cfg.BASE_DIR = str(tmp_path)
    main_mod.cfg.DATABASE_URL = object()
    main_mod.cfg.OPENAI_API_KEY = "set"

    records = []

    import logging

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Handler()
    main_mod.logger.addHandler(handler)
    try:
        main_mod.preflight("openai")
    finally:
        main_mod.logger.removeHandler(handler)

    assert any("DATABASE_URL beklenen şema biçiminde değil" in msg for msg in records)



def test_quick_mode_uses_safe_defaults_for_missing_or_invalid_config_types(monkeypatch):
    main_mod = _load_main_module()
    captured = {}

    main_mod.cfg.AI_PROVIDER = object()
    main_mod.cfg.ACCESS_LEVEL = 123
    main_mod.cfg.CODING_MODEL = None
    main_mod.cfg.WEB_HOST = "   "
    main_mod.cfg.WEB_PORT = "not-a-port"

    def _fake_execute(cmd, capture_output=False, child_log_path=None):
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["child_log_path"] = child_log_path
        return 0

    monkeypatch.setattr(main_mod, "execute_command", _fake_execute)
    monkeypatch.setattr(sys, "argv", ["main.py", "--quick", "web"])

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
    assert captured["capture_output"] is False
    assert captured["child_log_path"] is None



def test_run_wizard_uses_safe_defaults_for_invalid_web_config_values(monkeypatch):
    main_mod = _load_main_module()
    prompts = []

    main_mod.cfg.AI_PROVIDER = object()
    main_mod.cfg.ACCESS_LEVEL = ["sandbox"]
    main_mod.cfg.WEB_HOST = "   "
    main_mod.cfg.WEB_PORT = object()

    monkeypatch.setattr(main_mod, "print_banner", lambda: None)

    def _ask_choice(prompt, _options, default_key):
        prompts.append((prompt, default_key))
        if "arayüz" in prompt:
            return "web"
        if "Sağlayıcısı" in prompt:
            return "ollama"
        if "Güvenlik" in prompt:
            return "full"
        return "info"

    def _ask_text(prompt, default=""):
        prompts.append((prompt, default))
        return default

    monkeypatch.setattr(main_mod, "ask_choice", _ask_choice)
    monkeypatch.setattr(main_mod, "ask_text", _ask_text)
    monkeypatch.setattr(main_mod, "preflight", lambda _provider: None)
    monkeypatch.setattr(main_mod, "confirm", lambda *_args, **_kwargs: False)

    assert main_mod.run_wizard() == 0
    assert ("2. Hangi AI Sağlayıcısı kullanılsın?", "1") in prompts
    assert ("3. Güvenlik/Yetki seviyesi ne olsun?", "1") in prompts
    assert ("\nWeb Sunucu Host IP'si", "0.0.0.0") in prompts
    assert ("Web Sunucu Portu", "7860") in prompts


def test_run_with_streaming_terminates_lingering_process_before_join(monkeypatch):
    main_mod = _load_main_module()

    class _Pipe:
        def readline(self):
            return ""

        def close(self):
            return None

    class _Proc:
        def __init__(self):
            self.stdout = _Pipe()
            self.stderr = _Pipe()
            self.terminate_calls = 0
            self.kill_calls = 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            self.terminate_calls += 1

        def kill(self):
            self.kill_calls += 1

    proc = _Proc()
    monkeypatch.setattr(main_mod.subprocess, "Popen", lambda *a, **k: proc)

    rc = main_mod._run_with_streaming(["python", "cli.py"], None)

    assert rc == 0
    assert proc.terminate_calls == 1
    assert proc.kill_calls == 0