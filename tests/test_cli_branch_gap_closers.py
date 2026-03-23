import asyncio
import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest


@contextmanager
def _temp_modules(mapping):
    previous = {name: sys.modules.get(name) for name in mapping}
    sys.modules.update(mapping)
    try:
        yield
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _load_cli_module(config_cls=None):
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        ACCESS_LEVEL = "sandbox"
        AI_PROVIDER = "ollama"
        CODING_MODEL = "qwen"
        LOG_LEVEL = "INFO"
        GEMINI_MODEL = "g-2"
        USE_GPU = False
        GPU_INFO = "CPU"
        VERSION = "2.0"

        @staticmethod
        def initialize_directories():
            return None

    cfg_mod.Config = config_cls or _Cfg

    agent_mod = types.ModuleType("agent.sidar_agent")
    agent_mod.SidarAgent = object
    agent_pkg = types.ModuleType("agent")

    with _temp_modules({"config": cfg_mod, "agent": agent_pkg, "agent.sidar_agent": agent_mod}):
        spec = importlib.util.spec_from_file_location("cli_under_test_branch_gaps", Path("cli.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod


def test_interactive_loop_gpu_without_cuda_suffix_prints_plain_gpu_line(monkeypatch, capsys):
    cli = _load_cli_module()

    class _Cfg:
        AI_PROVIDER = "ollama"
        CODING_MODEL = "qwen"
        ACCESS_LEVEL = "sandbox"
        USE_GPU = True
        GPU_INFO = "RTX 4090"
        CUDA_VERSION = "N/A"

    class _Simple:
        def is_available(self):
            return True

        def status(self):
            return "ok"

    class _Agent:
        VERSION = "2.0"
        cfg = _Cfg()
        github = _Simple()
        web = _Simple()
        pkg = types.SimpleNamespace(status=lambda: "pkg")
        docs = types.SimpleNamespace(status=lambda: "docs", list_documents=lambda: "docs")
        health = types.SimpleNamespace(full_report=lambda: "health", optimize_gpu_memory=lambda: "gpu")
        security = types.SimpleNamespace(status_report=lambda: "SEC")
        code = types.SimpleNamespace(audit_project=lambda _: "audit")

        async def clear_memory(self):
            return "cleared"

        def status(self):
            return "agent-status"

        async def set_access_level(self, level):
            return level

        async def respond(self, _text):
            if False:
                yield ""

    async def _stop_immediately(_fn, *_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(asyncio, "to_thread", _stop_immediately)

    asyncio.run(cli._interactive_loop_async(_Agent()))

    out = capsys.readouterr().out
    assert "GPU             : ✓ RTX 4090" in out
    assert "(CUDA" not in out


def test_interactive_loop_gpu_with_single_gpu_omits_gpu_count(monkeypatch, capsys):
    cli = _load_cli_module()

    class _Cfg:
        AI_PROVIDER = "gemini"
        GEMINI_MODEL = "gemini-2.0-flash"
        CODING_MODEL = "qwen"
        ACCESS_LEVEL = "sandbox"
        USE_GPU = True
        GPU_INFO = "RTX"
        CUDA_VERSION = "12.4"
        GPU_COUNT = 1

    class _Simple:
        def is_available(self):
            return False

        def status(self):
            return "ok"

    class _Agent:
        VERSION = "2.0"
        cfg = _Cfg()
        github = _Simple()
        web = _Simple()
        pkg = types.SimpleNamespace(status=lambda: "pkg")
        docs = types.SimpleNamespace(status=lambda: "docs", list_documents=lambda: "docs")
        health = types.SimpleNamespace(full_report=lambda: "health", optimize_gpu_memory=lambda: "gpu")
        security = types.SimpleNamespace(status_report=lambda: "SEC")
        code = types.SimpleNamespace(audit_project=lambda _: "audit")

        async def clear_memory(self):
            return "cleared"

        def status(self):
            return "agent-status"

        async def set_access_level(self, level):
            return level

        async def respond(self, _text):
            if False:
                yield ""

    async def _stop_immediately(_fn, *_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(asyncio, "to_thread", _stop_immediately)

    asyncio.run(cli._interactive_loop_async(_Agent()))

    out = capsys.readouterr().out
    assert "AI Sağlayıcı    : gemini (gemini-2.0-flash)" in out
    assert "GPU             : ✓ RTX  (CUDA 12.4)" in out
    assert ", 1 GPU" not in out


def test_cli_main_preserves_config_defaults_when_optional_overrides_are_missing(monkeypatch):
    class _Cfg:
        ACCESS_LEVEL = "restricted"
        AI_PROVIDER = "anthropic"
        CODING_MODEL = "claude-code"
        LOG_LEVEL = "WARNING"

        def initialize_directories(self):
            self.initialized = True

    cli = _load_cli_module(config_cls=_Cfg)
    captured = {}

    class _Agent:
        def __init__(self, cfg):
            captured["cfg"] = cfg
            self.memory = types.SimpleNamespace(initialize=lambda: asyncio.sleep(0))

    def _run_coro(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    monkeypatch.setattr(cli.argparse.ArgumentParser, "parse_args", lambda _self: types.SimpleNamespace(
        command=None,
        status=False,
        level=None,
        provider=None,
        model=None,
        log="INFO",
    ))
    monkeypatch.setattr(cli, "SidarAgent", _Agent)
    monkeypatch.setattr(cli, "interactive_loop", lambda agent: captured.setdefault("interactive_agent", agent))
    monkeypatch.setattr(asyncio, "run", _run_coro)

    cli.main()

    cfg = captured["cfg"]
    assert cfg.ACCESS_LEVEL == "restricted"
    assert cfg.AI_PROVIDER == "anthropic"
    assert cfg.CODING_MODEL == "claude-code"
    assert getattr(cfg, "initialized", False) is True
    assert captured["interactive_agent"] is not None


def test_cli_main_rejects_invalid_level_choice(monkeypatch):
    cli = _load_cli_module()
    monkeypatch.setattr(sys, "argv", ["cli.py", "--level", "admin"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
