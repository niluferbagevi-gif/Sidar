import argparse
import importlib
import logging
import sys
import types
import pytest


_original_sidar_agent_module = sys.modules.get("agent.sidar_agent")
sidar_agent_mod = types.ModuleType("agent.sidar_agent")
sidar_agent_mod.SidarAgent = object
sys.modules["agent.sidar_agent"] = sidar_agent_mod

cli = importlib.import_module("cli")

if _original_sidar_agent_module is not None:
    sys.modules["agent.sidar_agent"] = _original_sidar_agent_module
else:
    sys.modules.pop("agent.sidar_agent", None)


class _FakeAgent:
    VERSION = "1.2.3"

    def __init__(self, _cfg) -> None:
        self.cfg = type(
            "Cfg",
            (),
            {
                "ACCESS_LEVEL": "full",
                "AI_PROVIDER": "ollama",
                "CODING_MODEL": "model-x",
                "USE_GPU": False,
                "GPU_INFO": "cpu",
            },
        )()
        self.memory = type(
            "Mem",
            (),
            {
                "initialize": self._initialize,
                "set_active_user": self._set_active_user,
                "db": type("DB", (), {"ensure_user": self._ensure_user})(),
            },
        )()
        self.active_user_calls = []
        self.initialize_calls = 0

    async def _initialize(self) -> None:
        return None

    async def initialize(self) -> None:
        self.initialize_calls += 1
        await self.memory.initialize()

    async def _ensure_user(self, username: str):
        return type("User", (), {"id": "u-cli", "username": username})()

    async def _set_active_user(self, user_id: str, username: str) -> None:
        self.active_user_calls.append((user_id, username))

    def status(self) -> str:
        return "OK"


def test_make_banner_includes_truncated_version() -> None:
    banner = cli._make_banner("x" * 40)
    assert "Yazılım Mimarı & Baş Mühendis AI" in banner
    assert "…" in banner


def test_setup_logging_sets_root_level() -> None:
    cli._setup_logging("debug")
    assert logging.getLogger().level == logging.DEBUG


def test_main_status_path_prints_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "SidarAgent", _FakeAgent)
    monkeypatch.setattr(cli.Config, "initialize_directories", staticmethod(lambda: True), raising=False)
    monkeypatch.setattr(cli.Config, "validate_critical_settings", staticmethod(lambda: True), raising=False)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: argparse.Namespace(
        command=None,
        status=True,
        level="full",
        provider="ollama",
        model="model-x",
        log="INFO",
    ))

    cli.main()
    assert "OK" in capsys.readouterr().out


def test_main_command_path_streams_response(monkeypatch, capsys) -> None:
    created_agents = []

    class _AgentWithRespond(_FakeAgent):
        def __init__(self, cfg) -> None:
            super().__init__(cfg)
            created_agents.append(self)

        async def respond(self, _command):
            for part in ("merhaba", " dünya"):
                yield part

    monkeypatch.setattr(cli, "SidarAgent", _AgentWithRespond)
    monkeypatch.setattr(cli.Config, "initialize_directories", staticmethod(lambda: True), raising=False)
    monkeypatch.setattr(cli.Config, "validate_critical_settings", staticmethod(lambda: True), raising=False)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: argparse.Namespace(
        command="selam",
        status=False,
        level="full",
        provider="ollama",
        model="model-x",
        log="INFO",
    ))

    cli.main()
    assert "Sidar > merhaba dünya" in capsys.readouterr().out
    assert created_agents[0].initialize_calls == 1
    assert created_agents[0].active_user_calls == [("u-cli", "cli")]


def test_main_exits_when_critical_validation_fails(monkeypatch) -> None:
    monkeypatch.setattr(cli.Config, "initialize_directories", staticmethod(lambda: True), raising=False)
    monkeypatch.setattr(cli.Config, "validate_critical_settings", staticmethod(lambda: False), raising=False)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: argparse.Namespace(
        command=None,
        status=False,
        level="full",
        provider="ollama",
        model="model-x",
        log="INFO",
    ))

    with pytest.raises(SystemExit):
        cli.main()
