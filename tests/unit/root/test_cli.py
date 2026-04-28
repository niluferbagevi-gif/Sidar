import importlib
import logging
import sys
import types
from types import SimpleNamespace

import pytest


def _load_cli_module_with_stubbed_agent(monkeypatch):
    fake_agent_module = types.ModuleType("agent.sidar_agent")

    class _ImportStubAgent:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("test should monkeypatch SidarAgent before use")

    with pytest.raises(RuntimeError, match="test should monkeypatch SidarAgent before use"):
        _ImportStubAgent()
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


class _InteractiveAgent:
    VERSION = "5.2.0"

    def __init__(
        self,
        *,
        provider="gemini",
        use_gpu=True,
        github_available=True,
        web_available=True,
        cuda_version="12.2",
        gpu_count=2,
    ):
        self.cfg = SimpleNamespace(
            ACCESS_LEVEL="full",
            AI_PROVIDER=provider,
            GEMINI_MODEL="gemini-test",
            CODING_MODEL="coder-test",
            USE_GPU=use_gpu,
            GPU_INFO="RTX",
            CUDA_VERSION=cuda_version,
            GPU_COUNT=gpu_count,
        )
        self.github = SimpleNamespace(
            is_available=lambda: github_available,
            status=lambda: "GITHUB:OK",
        )
        self.web = SimpleNamespace(
            is_available=lambda: web_available,
            status=lambda: "WEB:OK",
        )
        self.pkg = SimpleNamespace(status=lambda: "PKG:OK")
        self.docs = SimpleNamespace(
            status=lambda: "DOCS:OK",
            list_documents=lambda: "DOC_LIST",
        )
        self.code = SimpleNamespace(audit_project=lambda _path: "AUDIT:OK")
        self.health = SimpleNamespace(
            full_report=lambda: "HEALTH:OK",
            optimize_gpu_memory=lambda: "GPU:OPT",
        )
        self.security = SimpleNamespace(status_report=lambda: "SEC:OK")
        self._clear_called = 0
        self._level_calls = []
        self._respond_chunks = ["A", "B"]
        self._respond_error = None

    def status(self):
        return "STATUS:OK"

    async def clear_memory(self):
        self._clear_called += 1
        return "CLEARED"

    async def set_access_level(self, level):
        self._level_calls.append(level)
        return f"LEVEL:{level}"

    async def respond(self, prompt):
        _ = prompt
        if self._respond_error is not None:
            raise self._respond_error
        for item in self._respond_chunks:
            yield item


class _MainFlowAgent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.memory = SimpleNamespace(
            db=SimpleNamespace(ensure_user=self._ensure_user),
            set_active_user=self._set_active_user,
        )
        self.initialized = 0
        self.ensure_user_calls = []
        self.active_user_calls = []
        self.command_prompts = []

    async def initialize(self):
        self.initialized += 1

    async def _ensure_user(self, username):
        self.ensure_user_calls.append(username)
        return SimpleNamespace(id=42, username="cli")

    async def _set_active_user(self, user_id, username):
        self.active_user_calls.append((user_id, username))

    def status(self):
        return "STATUS:MAIN"

    async def respond(self, prompt):
        self.command_prompts.append(prompt)
        yield "OK"


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


def test_setup_logging_sets_root_level(monkeypatch):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    cli._setup_logging("debug")
    assert logging.getLogger().level == logging.DEBUG


def test_make_banner_formats_and_truncates_version(monkeypatch):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    short = cli._make_banner("1.0.0")
    long = cli._make_banner("12345678901234567890")
    assert "v1.0.0" in short
    assert "…" in long
    assert long.startswith("\n ╔")


@pytest.mark.asyncio
async def test_interactive_loop_covers_commands_and_standard_response(monkeypatch, capsys):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    agent = _InteractiveAgent(provider="gemini", use_gpu=True)
    inputs = iter(
        [
            "   ",
            ".help",
            ".status",
            ".clear",
            ".audit",
            ".health",
            ".gpu",
            ".github",
            ".level",
            ".level sandbox",
            ".web",
            ".docs",
            "normal prompt",
            ".q",
        ]
    )

    async def _fake_to_thread(_fn, _prompt):
        return next(inputs)

    monkeypatch.setattr(cli.asyncio, "to_thread", _fake_to_thread)
    await cli._interactive_loop_async(agent)
    output = capsys.readouterr().out

    assert "STATUS:OK" in output
    assert "CLEARED" in output
    assert "AUDIT:OK" in output
    assert "HEALTH:OK" in output
    assert "GPU:OPT" in output
    assert "GITHUB:OK" in output
    assert "SEC:OK" in output
    assert "LEVEL:sandbox" in output
    assert "WEB:OK" in output
    assert "DOC_LIST" in output
    assert "AB" in output
    assert agent._level_calls == ["sandbox"]


@pytest.mark.asyncio
async def test_interactive_loop_handles_provider_cpu_and_input_interrupt(monkeypatch, capsys):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    agent = _InteractiveAgent(
        provider="ollama",
        use_gpu=False,
        github_available=False,
        web_available=False,
    )

    async def _raise_interrupt(_fn, _prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.asyncio, "to_thread", _raise_interrupt)
    await cli._interactive_loop_async(agent)
    output = capsys.readouterr().out
    assert "CPU Modu" in output
    assert "coder-test" in output
    assert "Bağlı değil" in output
    assert "duckduckgo-search kurulu değil" in output
    assert "Görüşürüz. ✓" in output


@pytest.mark.asyncio
async def test_interactive_loop_handles_gpu_without_cuda_suffix(monkeypatch, capsys):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    agent = _InteractiveAgent(cuda_version="N/A", gpu_count=1)

    async def _raise_interrupt(_fn, _prompt):
        raise EOFError

    monkeypatch.setattr(cli.asyncio, "to_thread", _raise_interrupt)
    await cli._interactive_loop_async(agent)
    output = capsys.readouterr().out
    assert "GPU             : ✓ RTX" in output


@pytest.mark.asyncio
async def test_interactive_loop_handles_single_gpu_with_cuda(monkeypatch, capsys):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    agent = _InteractiveAgent(cuda_version="12.1", gpu_count=1)

    async def _raise_interrupt(_fn, _prompt):
        raise EOFError

    monkeypatch.setattr(cli.asyncio, "to_thread", _raise_interrupt)
    await cli._interactive_loop_async(agent)
    output = capsys.readouterr().out
    assert "(CUDA 12.1)" in output


@pytest.mark.asyncio
async def test_interactive_loop_handles_response_cancelled(monkeypatch, capsys):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    agent = _InteractiveAgent()
    agent._respond_error = cli.asyncio.CancelledError()
    inputs = iter(["ask me"])

    async def _fake_to_thread(_fn, _prompt):
        return next(inputs)

    monkeypatch.setattr(cli.asyncio, "to_thread", _fake_to_thread)
    await cli._interactive_loop_async(agent)
    output = capsys.readouterr().out
    assert "İşlem iptal edildi" in output


@pytest.mark.asyncio
async def test_interactive_loop_handles_response_exception_then_exit(monkeypatch, capsys):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    agent = _InteractiveAgent()
    agent._respond_error = RuntimeError("boom")
    inputs = iter(["ask me", ".exit"])

    async def _fake_to_thread(_fn, _prompt):
        return next(inputs)

    monkeypatch.setattr(cli.asyncio, "to_thread", _fake_to_thread)
    await cli._interactive_loop_async(agent)
    output = capsys.readouterr().out
    assert "✗ Hata: boom" in output
    assert "Görüşürüz. ✓" in output


def test_interactive_loop_wrapper_calls_asyncio_run(monkeypatch):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    called = {"count": 0}

    def _fake_run(coro):
        called["count"] += 1
        coro.close()

    monkeypatch.setattr(cli.asyncio, "run", _fake_run)
    cli.interactive_loop(object())
    assert called["count"] == 1


@pytest.mark.asyncio
async def test_ensure_cli_memory_user_sets_active_user(monkeypatch):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    calls = []

    async def _ensure_user(username):
        calls.append(("ensure_user", username))
        return SimpleNamespace(id=7, username=username)

    async def _set_active_user(user_id, username):
        calls.append(("set_active_user", user_id, username))

    fake_agent = SimpleNamespace(
        memory=SimpleNamespace(
            db=SimpleNamespace(ensure_user=_ensure_user),
            set_active_user=_set_active_user,
        )
    )
    await cli._ensure_cli_memory_user(fake_agent)
    assert calls == [("ensure_user", "cli"), ("set_active_user", 7, "cli")]


def test_main_command_mode_runs_setup_and_response(monkeypatch, capsys):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    created = {}

    class _ConfigWithTimeout(_FakeConfig):
        CLI_COMMAND_TIMEOUT = 9

        def __init__(self):
            super().__init__()
            self.CLI_FAST_MODE = False

    def _agent_factory(cfg):
        agent = _MainFlowAgent(cfg)
        created["agent"] = agent
        return agent

    monkeypatch.setattr(cli, "Config", _ConfigWithTimeout)
    monkeypatch.setattr(cli, "SidarAgent", _agent_factory)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "cli.py",
            "--command",
            "hello",
            "--provider",
            "openai",
            "--level",
            "sandbox",
            "--model",
            "m1",
        ],
    )
    cli.main()
    out = capsys.readouterr().out

    agent = created["agent"]
    assert agent.initialized == 1
    assert agent.ensure_user_calls == ["cli"]
    assert agent.active_user_calls == [(42, "cli")]
    assert agent.command_prompts == ["hello"]
    assert "Sidar > OK" in out
    assert agent.cfg.CLI_FAST_MODE is True
    assert agent.cfg.AI_PROVIDER == "openai"
    assert agent.cfg.ACCESS_LEVEL == "sandbox"
    assert agent.cfg.CODING_MODEL == "m1"


def test_main_command_mode_timeout_prints_warning(monkeypatch, capsys):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)

    class _ConfigWithTimeout(_FakeConfig):
        CLI_COMMAND_TIMEOUT = 8

    monkeypatch.setattr(cli, "Config", _ConfigWithTimeout)
    monkeypatch.setattr(cli, "SidarAgent", _MainFlowAgent)
    monkeypatch.setattr(cli.sys, "argv", ["cli.py", "--command", "hello"])

    def _raise_timeout(_coro, timeout):
        _ = timeout
        _coro.close()
        raise cli.asyncio.TimeoutError

    monkeypatch.setattr(cli.asyncio, "wait_for", _raise_timeout)
    cli.main()
    out = capsys.readouterr().out
    assert "Komut zaman aşımına uğradı (8s)." in out


def test_main_interactive_mode_initializes_and_enters_loop(monkeypatch):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    created = {}

    class _DefaultConfig(_FakeConfig):
        def __init__(self):
            super().__init__()
            self.CLI_FAST_MODE = False

    def _agent_factory(cfg):
        agent = _MainFlowAgent(cfg)
        created["agent"] = agent
        return agent

    entered = {"count": 0}

    def _fake_interactive_loop(agent):
        entered["count"] += 1
        assert agent is created["agent"]

    monkeypatch.setattr(cli, "Config", _DefaultConfig)
    monkeypatch.setattr(cli, "SidarAgent", _agent_factory)
    monkeypatch.setattr(cli, "interactive_loop", _fake_interactive_loop)
    monkeypatch.setattr(cli.sys, "argv", ["cli.py"])
    cli.main()

    agent = created["agent"]
    assert agent.initialized == 1
    assert agent.ensure_user_calls == ["cli"]
    assert agent.active_user_calls == [(42, "cli")]
    assert entered["count"] == 1


def test_main_skips_overrides_when_args_are_none(monkeypatch):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)

    class _ConfigWithFields(_FakeConfig):
        def __init__(self):
            super().__init__()
            self.CLI_FAST_MODE = False

    created = {}

    def _agent_factory(cfg):
        created["cfg"] = cfg
        return _MainFlowAgent(cfg)

    parsed = SimpleNamespace(
        command=None,
        status=True,
        level=None,
        provider=None,
        model=None,
        log="INFO",
    )

    monkeypatch.setattr(cli, "Config", _ConfigWithFields)
    monkeypatch.setattr(cli, "SidarAgent", _agent_factory)
    monkeypatch.setattr(cli.argparse.ArgumentParser, "parse_args", lambda _self: parsed)
    cli.main()

    cfg = created["cfg"]
    assert cfg.ACCESS_LEVEL == "full"
    assert cfg.AI_PROVIDER == "ollama"
    assert cfg.CODING_MODEL == "qwen2.5-coder:7b"
    assert cfg.CLI_FAST_MODE is False


def test_main_dispatches_heal_subcommand(monkeypatch):
    cli = _load_cli_module_with_stubbed_agent(monkeypatch)
    called = {}

    def _fake_run_heal(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(cli, "_run_heal_cli", _fake_run_heal)
    monkeypatch.setattr(cli.sys, "argv", ["cli.py", "heal", "--target", "mypy"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert called["argv"] == ["--target", "mypy"]
