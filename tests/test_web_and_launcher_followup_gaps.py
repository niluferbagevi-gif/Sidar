import asyncio
import sys
import types

import pytest

from tests.test_main_launcher_improvements import _load_main_module
from tests.test_web_server_runtime import _load_web_server


def test_main_quick_mode_exits_with_runtime_dependency_error(monkeypatch, capsys):
    main_mod = _load_main_module()

    monkeypatch.setattr(
        main_mod,
        "validate_runtime_dependencies",
        lambda mode: (False, f"{mode} runtime missing"),
    )
    monkeypatch.setattr(
        main_mod,
        "execute_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("execute_command should not run when runtime validation fails")
        ),
    )
    monkeypatch.setattr(sys, "argv", ["main.py", "--quick", "web"])

    with pytest.raises(SystemExit) as exc:
        main_mod.main()

    assert exc.value.code == 2
    assert "web runtime missing" in capsys.readouterr().out


def test_web_server_main_runs_async_initialize_and_uses_agent_version_banner(monkeypatch):
    mod = _load_web_server()
    captured = {"prints": [], "uvicorn": None, "initialized": 0}

    class _Agent:
        VERSION = "3.4.5"

        def __init__(self, cfg):
            self.cfg = cfg

        async def initialize(self):
            captured["initialized"] += 1

    def _run(app, host, port, log_level):
        captured["uvicorn"] = (app, host, port, log_level)

    def _print(*args, **_kwargs):
        captured["prints"].append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(mod, "SidarAgent", _Agent)
    monkeypatch.setattr(mod.uvicorn, "run", _run)
    monkeypatch.setattr("builtins.print", _print)
    monkeypatch.setattr(sys, "argv", ["web_server.py", "--host", "127.0.0.1", "--port", "9090", "--log", "WARNING"])

    mod.main()

    assert captured["initialized"] == 1
    assert captured["uvicorn"] == (mod.app, "127.0.0.1", 9090, "warning")
    assert any("http://127.0.0.1:9090" in line for line in captured["prints"])
    assert any("Sürüm: v3.4.5" in line for line in captured["prints"])


def test_web_server_main_warns_and_starts_when_agent_bootstrap_fails(monkeypatch):
    mod = _load_web_server()
    captured = {"warnings": [], "uvicorn": None, "prints": []}

    def _warning(msg, *args):
        captured["warnings"].append(msg % args if args else msg)

    class _Agent:
        def __init__(self, _cfg):
            raise RuntimeError("bootstrap failed")

    def _run(app, host, port, log_level):
        captured["uvicorn"] = (app, host, port, log_level)

    def _print(*args, **_kwargs):
        captured["prints"].append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr(mod, "SidarAgent", _Agent)
    monkeypatch.setattr(mod.logger, "warning", _warning)
    monkeypatch.setattr(mod.uvicorn, "run", _run)
    monkeypatch.setattr("builtins.print", _print)
    monkeypatch.setattr(sys, "argv", ["web_server.py", "--host", "0.0.0.0", "--port", "8081"])

    mod.main()

    assert captured["uvicorn"] == (mod.app, "0.0.0.0", 8081, "info")
    assert any("ön başlatması başarısız" in msg and "bootstrap failed" in msg for msg in captured["warnings"])
    assert any("http://localhost:8081" in line for line in captured["prints"])
    assert any("Sürüm: v?" in line for line in captured["prints"])