import argparse
import asyncio
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


class _InteractiveAgent:
    VERSION = "2.0.0"

    def __init__(self) -> None:
        self.cfg = type(
            "Cfg",
            (),
            {
                "ACCESS_LEVEL": "sandbox",
                "AI_PROVIDER": "gemini",
                "GEMINI_MODEL": "gemini-pro",
                "CODING_MODEL": "unused-model",
                "USE_GPU": True,
                "GPU_INFO": "RTX",
                "CUDA_VERSION": "12.4",
                "GPU_COUNT": 2,
            },
        )()
        self.github = type("GitHub", (), {"is_available": lambda *_: True, "status": lambda *_: "gh-ok"})()
        self.web = type(
            "Web",
            (),
            {"is_available": lambda *_: True, "status": lambda *_: "web-ok"},
        )()
        self.pkg = type("Pkg", (), {"status": lambda *_: "pkg-ok"})()
        self.docs = type(
            "Docs",
            (),
            {"status": lambda *_: "docs-ok", "list_documents": lambda *_: "doc-list"},
        )()
        self.code = type("Code", (), {"audit_project": lambda *_: "audit-ok"})()
        self.health = type(
            "Health",
            (),
            {"full_report": lambda *_: "health-ok", "optimize_gpu_memory": lambda *_: "gpu-ok"},
        )()
        self.security = type("Sec", (), {"status_report": lambda *_: "sec-ok"})()
        self.set_level_calls = []
        self.respond_inputs = []

    def status(self) -> str:
        return "status-ok"

    async def clear_memory(self) -> str:
        return "memory-cleared"

    async def set_access_level(self, level: str) -> str:
        self.set_level_calls.append(level)
        return f"level:{level}"

    async def respond(self, user_input: str):
        self.respond_inputs.append(user_input)
        for part in ("yanit-", "ok"):
            yield part


def test_interactive_loop_covers_builtin_commands_and_normal_message(monkeypatch, capsys) -> None:
    agent = _InteractiveAgent()
    inputs = iter([
        "",
        ".help",
        ".status",
        ".clear",
        ".audit",
        ".health",
        ".gpu",
        ".github",
        ".level",
        ".level full",
        ".web",
        ".docs",
        "merhaba",
        ".exit",
    ])
    monkeypatch.setattr(cli.asyncio, "to_thread", lambda *_args, **_kwargs: asyncio.sleep(0, next(inputs)))
    asyncio.run(cli._interactive_loop_async(agent))

    out = capsys.readouterr().out
    assert "AI Sağlayıcı    : gemini (gemini-pro)" in out
    assert "GPU             : ✓ RTX  (CUDA 12.4, 2 GPU)" in out
    assert "status-ok" in out
    assert "memory-cleared" in out
    assert "audit-ok" in out
    assert "health-ok" in out
    assert "gpu-ok" in out
    assert "gh-ok" in out
    assert "sec-ok" in out
    assert "level:full" in out
    assert "web-ok" in out
    assert "doc-list" in out
    assert "Sidar > yanit-ok" in out
    assert agent.respond_inputs == ["merhaba"]
    assert agent.set_level_calls == ["full"]


def test_interactive_loop_handles_input_and_respond_exceptions(monkeypatch, capsys) -> None:
    class _RaisingAgent(_InteractiveAgent):
        async def respond(self, user_input: str):
            if user_input == "cancel":
                raise asyncio.CancelledError()
            raise RuntimeError("boom")
            yield  # pragma: no cover

    agent = _RaisingAgent()
    inputs = iter(["fail", "cancel"])
    monkeypatch.setattr(cli.asyncio, "to_thread", lambda *_args, **_kwargs: asyncio.sleep(0, next(inputs)))
    logged = []
    monkeypatch.setattr(cli.logging, "exception", lambda msg: logged.append(msg))
    asyncio.run(cli._interactive_loop_async(agent))
    out = capsys.readouterr().out
    assert "✗ Hata: boom" in out
    assert "İşlem iptal edildi" in out
    assert logged == ["Ajan yanıt hatası"]


def test_interactive_loop_handles_input_interrupt(monkeypatch, capsys) -> None:
    agent = _InteractiveAgent()
    monkeypatch.setattr(
        cli.asyncio,
        "to_thread",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(EOFError()),
    )
    asyncio.run(cli._interactive_loop_async(agent))
    assert "Görüşürüz. ✓" in capsys.readouterr().out


def test_interactive_loop_wrapper_calls_asyncio_run(monkeypatch) -> None:
    called = {}

    def _fake_run(coro):
        called["run"] = coro.cr_code.co_name
        coro.close()
        return None

    monkeypatch.setattr(cli.asyncio, "run", _fake_run)
    cli.interactive_loop(object())
    assert called["run"] == "_interactive_loop_async"


def test_main_calls_interactive_loop_without_command_or_status(monkeypatch) -> None:
    called = {"interactive": 0}

    class _AgentNoop(_FakeAgent):
        pass

    monkeypatch.setattr(cli, "SidarAgent", _AgentNoop)
    monkeypatch.setattr(cli, "interactive_loop", lambda _agent: called.__setitem__("interactive", called["interactive"] + 1))
    monkeypatch.setattr(cli.Config, "initialize_directories", staticmethod(lambda: True), raising=False)
    monkeypatch.setattr(cli.Config, "validate_critical_settings", staticmethod(lambda: True), raising=False)
    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self: argparse.Namespace(
            command=None,
            status=False,
            level="sandbox",
            provider="openai",
            model="gpt-4",
            log="WARNING",
        ),
    )
    cli.main()
    assert called["interactive"] == 1
