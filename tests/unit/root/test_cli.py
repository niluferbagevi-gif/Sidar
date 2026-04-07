import importlib
import sys
import types

import pytest


def _load_cli_module_with_stubbed_agent(monkeypatch):
    fake_agent_module = types.ModuleType("agent.sidar_agent")

    class _ImportStubAgent:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("test should monkeypatch SidarAgent before use")

    fake_agent_module.SidarAgent = _ImportStubAgent
    monkeypatch.setitem(sys.modules, "agent.sidar_agent", fake_agent_module)

    sys.modules.pop("cli", None)
    return importlib.import_module("cli")


class _FakeConfig:
    ACCESS_LEVEL = "full"
    AI_PROVIDER = "ollama"
    CODING_MODEL = "qwen2.5-coder:7b"
    LOG_LEVEL = "INFO"

    def __init__(self):
        self.ACCESS_LEVEL = self.__class__.ACCESS_LEVEL
        self.AI_PROVIDER = self.__class__.AI_PROVIDER
        self.CODING_MODEL = self.__class__.CODING_MODEL

    def initialize_directories(self):
        return True

    def validate_critical_settings(self):
        return True


class _FakeAgent:
    initialized = False

    def __init__(self, cfg):
        self.cfg = cfg

    async def initialize(self):
        _FakeAgent.initialized = True

    def status(self):
        return "STATUS:OK"


def test_cli_main_status_mode_boots_agent(monkeypatch, capsys):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    monkeypatch.setattr(cli, "Config", _FakeConfig)
    monkeypatch.setattr(cli, "SidarAgent", _FakeAgent)
    monkeypatch.setattr(cli.sys, "argv", ["cli.py", "--status"])

    cli.main()

    out = capsys.readouterr().out
    assert _FakeAgent.initialized is True
    assert "STATUS:OK" in out


def test_cli_main_fails_fast_on_invalid_critical_settings(monkeypatch):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)

    class _InvalidConfig(_FakeConfig):
        def validate_critical_settings(self):
            return False

    monkeypatch.setattr(cli, "Config", _InvalidConfig)
    monkeypatch.setattr(cli.sys, "argv", ["cli.py"])

    with pytest.raises(SystemExit, match="Kritik yapılandırma doğrulaması başarısız"):
        cli.main()
