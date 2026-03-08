import asyncio
import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _temp_modules(mapping):
    prev = {k: sys.modules.get(k) for k in mapping}
    sys.modules.update(mapping)
    try:
        yield
    finally:
        for k, v in prev.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _load_cli_module():
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

    cfg_mod.Config = _Cfg

    agent_mod = types.ModuleType("agent.sidar_agent")
    agent_mod.SidarAgent = object
    agent_pkg = types.ModuleType("agent")

    with _temp_modules({"config": cfg_mod, "agent": agent_pkg, "agent.sidar_agent": agent_mod}):
        spec = importlib.util.spec_from_file_location("cli_under_test", Path("cli.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod


def _make_agent():
    class _Sec:
        @staticmethod
        def status_report():
            return "SEC"

    class _Docs:
        @staticmethod
        def status():
            return "docs-ok"

        @staticmethod
        def list_documents():
            return "docs"

    class _Health:
        @staticmethod
        def full_report():
            return "health"

        @staticmethod
        def optimize_gpu_memory():
            return "gpu"

    class _Simple:
        def __init__(self, val):
            self._val = val

        def is_available(self):
            return self._val

        def status(self):
            return f"status:{self._val}"

    class _Cfg:
        AI_PROVIDER = "ollama"
        GEMINI_MODEL = "g-2"
        CODING_MODEL = "qwen"
        ACCESS_LEVEL = "sandbox"
        USE_GPU = False
        GPU_INFO = "CPU"

    class _Agent:
        VERSION = "2.0"
        cfg = _Cfg()
        github = _Simple(True)
        web = _Simple(True)
        pkg = types.SimpleNamespace(status=lambda: "pkg")
        docs = _Docs()
        health = _Health()
        security = _Sec()
        code = types.SimpleNamespace(audit_project=lambda _: "audit")

        @staticmethod
        def clear_memory():
            return "cleared"

        @staticmethod
        def status():
            return "agent-status"

        @staticmethod
        def set_access_level(level):
            return f"set:{level}"

        async def respond(self, text):
            yield f"R:{text}"

    return _Agent()


def test_banner_logging_and_interactive_commands(monkeypatch):
    cli = _load_cli_module()
    cli._setup_logging("debug")
    assert "Yazılım Mimarı" in cli._make_banner("123456789012345")

    agent = _make_agent()
    inputs = iter([".help", ".status", ".clear", ".audit", ".health", ".gpu", ".github", ".level", ".level full", ".web", ".docs", "merhaba", ".exit"])
    monkeypatch.setattr(asyncio, "to_thread", lambda fn, *a, **k: asyncio.sleep(0, result=next(inputs)))

    asyncio.run(cli._interactive_loop_async(agent))


def test_interactive_loop_wrapper_and_main_paths(monkeypatch):
    cli = _load_cli_module()

    called = {"loop": 0}
    monkeypatch.setattr(cli, "_interactive_loop_async", lambda a: asyncio.sleep(0))

    def _run_coro(coro):
        called["loop"] += 1
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    monkeypatch.setattr(asyncio, "run", _run_coro)
    cli.interactive_loop(_make_agent())
    assert called["loop"] == 1

    agent = _make_agent()
    monkeypatch.setattr(cli, "SidarAgent", lambda cfg: agent)

    # --status path
    monkeypatch.setattr(sys, "argv", ["cli.py", "--status"])
    cli.main()

    # --command path
    monkeypatch.setattr(asyncio, "run", _run_coro)
    monkeypatch.setattr(sys, "argv", ["cli.py", "--command", "ping"])
    cli.main()

    # interactive fallback path
    monkeypatch.setattr(cli, "interactive_loop", lambda a: called.__setitem__("loop", called["loop"] + 1))
    monkeypatch.setattr(sys, "argv", ["cli.py"])
    cli.main()
    assert called["loop"] >= 2
