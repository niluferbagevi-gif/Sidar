import asyncio
import sys
import types
from types import SimpleNamespace

from agent.core.event_stream import AgentEventBus
from agent.sidar_agent import SidarAgent
from core.db import Database


class _AcquireCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self):
        self.fetchval_value = 0
        self.execute_calls = []
        self.fetchrow_value = None

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        return "EXECUTE 1"

    async def fetchval(self, query, *args):
        return self.fetchval_value

    async def fetchrow(self, query, *args):
        return self.fetchrow_value


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


class _DummySupervisor:
    def __init__(self, _cfg):
        pass

    async def run_task(self, _user_input):
        return ""


def test_event_bus_drops_full_subscriber():
    bus = AgentEventBus()

    async def _run():
        sid, _q = bus.subscribe(maxsize=10)
        for i in range(11):
            await bus.publish("supervisor", f"msg-{i}")
        assert sid not in bus._subscribers

    asyncio.run(_run())


def test_sidar_agent_try_multi_agent_handles_invalid_supervisor_output(monkeypatch):
    agent = object.__new__(SidarAgent)
    agent.cfg = SimpleNamespace()
    agent._supervisor = None

    fake_module = types.ModuleType("agent.core.supervisor")
    fake_module.SupervisorAgent = _DummySupervisor
    monkeypatch.setitem(sys.modules, "agent.core.supervisor", fake_module)

    result = asyncio.run(agent._try_multi_agent("test"))
    assert "geçerli bir çıktı" in result


def test_db_postgresql_early_return_and_remaining_branches(monkeypatch):
    cfg = SimpleNamespace(
        DATABASE_URL="postgresql://user:pass@localhost:5432/sidar",
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=2,
    )
    db = Database(cfg=cfg)
    conn = _FakeConn()
    conn.fetchval_value = 2
    db._pg_pool = _FakePool(conn)

    async def _run():
        await db._ensure_schema_version_postgresql()
        inserts = [q for q, _ in conn.execute_calls if "INSERT INTO schema_versions" in q]
        assert inserts == []

        conn.fetchrow_value = {
            "id": "u-1",
            "username": "alice",
            "password_hash": "hash",
            "role": "admin",
            "created_at": "now",
        }
        monkeypatch.setattr("core.db._verify_password", lambda *_: True)
        user = await db.authenticate_user("alice", "pw")
        assert user is not None and user.username == "alice"

        conn.fetchrow_value = None
        assert await db.get_user_by_token("missing") is None

    asyncio.run(_run())

import os

from config import Config
from core import llm_metrics as lm
from managers.code_manager import CodeManager
from agent.core.contracts import DelegationRequest, TaskResult
from agent.core.supervisor import SupervisorAgent
from agent.roles.coder_agent import CoderAgent
from agent.roles.reviewer_agent import ReviewerAgent


class _DummyEvents:
    async def publish(self, _source, _message):
        return None


class _DummyMemoryHub:
    def add_global(self, _msg):
        return None

    def add_role_note(self, _role, _note):
        return None


class _AwaitableNoop:
    def __await__(self):
        if False:
            yield None
        return None


def test_code_manager_execute_code_runtime_and_wait_exception_path(monkeypatch):
    manager = object.__new__(CodeManager)
    manager.security = SimpleNamespace(can_execute=lambda: True, level="full")
    manager.docker_available = True
    manager.docker_image = "python:3.11"
    manager.docker_mem_limit = "128m"
    manager.docker_nano_cpus = 500_000_000
    manager.docker_network_disabled = False
    manager.docker_exec_timeout = 1
    manager.max_output_chars = 1000
    manager._resolve_runtime = lambda: "runc"

    class _Container:
        status = "exited"

        def reload(self):
            return None

        def logs(self, stdout=True, stderr=True):
            return b"ok"

        def wait(self, timeout=1):
            raise RuntimeError("wait boom")

        def remove(self, force=True):
            return None

    captured = {}

    class _Containers:
        def run(self, **kwargs):
            captured.update(kwargs)
            return _Container()

    manager.docker_client = SimpleNamespace(containers=_Containers())

    fake_docker = types.ModuleType("docker")
    fake_docker.errors = SimpleNamespace(ImageNotFound=RuntimeError, APIError=RuntimeError)
    monkeypatch.setitem(sys.modules, "docker", fake_docker)

    ok, out = manager.execute_code("print('x')")
    assert ok is True
    assert "runtime" in captured and captured["runtime"] == "runc"
    assert "REPL Çıktısı" in out


def test_supervisor_route_p2p_max_hops_failure_branch():
    sup = object.__new__(SupervisorAgent)
    sup.events = _DummyEvents()

    async def _always_delegate(*args, **kwargs):
        req = DelegationRequest(task_id="d1", reply_to="coder", target_agent="reviewer", payload="again")
        return TaskResult(task_id="t", status="done", summary=req)

    sup._delegate = _always_delegate
    req = DelegationRequest(task_id="d0", reply_to="supervisor", target_agent="coder", payload="p")
    result = asyncio.run(sup._route_p2p(req, max_hops=1))
    assert result.status == "failed"
    assert "Maksimum delegasyon hop" in str(result.summary)


def test_supervisor_run_task_delegation_request_paths():
    sup = object.__new__(SupervisorAgent)
    sup.events = _DummyEvents()
    sup.memory_hub = _DummyMemoryHub()

    async def _delegate(*args, **kwargs):
        receiver = args[0]
        if receiver == "coder":
            req = DelegationRequest(task_id="dc", reply_to="coder", target_agent="reviewer", payload="fix")
            return TaskResult(task_id="c", status="done", summary=req)
        req = DelegationRequest(task_id="dr", reply_to="reviewer", target_agent="coder", payload="review")
        return TaskResult(task_id="r", status="done", summary=req)

    async def _route(*args, **kwargs):
        return TaskResult(task_id="x", status="done", summary="pass")

    sup._delegate = _delegate
    sup._route_p2p = _route

    out = asyncio.run(sup.run_task("kod yaz"))
    assert "Reviewer QA Özeti" in out


def test_coder_agent_empty_and_execute_code_routes():
    coder = object.__new__(CoderAgent)
    coder.events = _DummyEvents()

    calls = []

    async def _call_tool(name, arg):
        calls.append((name, arg))
        return "ok"

    coder.call_tool = _call_tool

    empty = asyncio.run(coder.run_task("   "))
    assert "Boş kodlayıcı" in empty

    out = asyncio.run(coder.run_task("execute_code|print(1)"))
    assert out == "ok"
    assert calls[-1] == ("execute_code", "print(1)")


def test_coder_agent_tool_get_package_info_path():
    coder = object.__new__(CoderAgent)
    coder.pkg = SimpleNamespace(pypi_info=lambda _pkg: asyncio.sleep(0, result=(True, "pkg-ok")))
    out = asyncio.run(coder._tool_get_package_info(" requests "))
    assert out == "pkg-ok"


def test_reviewer_agent_edge_paths_and_defaults():
    reviewer = object.__new__(ReviewerAgent)
    reviewer.events = _DummyEvents()
    reviewer.cfg = SimpleNamespace(REVIEWER_TEST_COMMAND="pytest -q", BASE_DIR=".")
    reviewer.config = reviewer.cfg

    escaped = asyncio.run(reviewer._build_dynamic_test_content('bad """ marker'))
    assert "'''" in escaped

    paths = reviewer._extract_changed_paths("a/../x.py ok.py")
    assert paths == ["ok.py"]

    async def _call_tool(name, arg):
        return f"{name}:{arg}"

    reviewer.call_tool = _call_tool
    empty = asyncio.run(reviewer.run_task(""))
    assert "Boş reviewer" in empty
    default_out = asyncio.run(reviewer.run_task("merhaba"))
    assert default_out == "list_prs:open"


def test_reviewer_run_dynamic_tests_invokes_pytest_path():
    reviewer = object.__new__(ReviewerAgent)
    reviewer.config = SimpleNamespace(BASE_DIR=".")

    async def _call_tool(name, arg):
        return f"{name}|{arg}"

    async def _build_dynamic(_ctx: str) -> str:
        return "def test_temp():\n    assert True\n"

    reviewer.call_tool = _call_tool
    reviewer._build_dynamic_test_content = _build_dynamic
    reviewer.code = SimpleNamespace(write_file=lambda *_args, **_kwargs: (True, "ok"))
    out = asyncio.run(reviewer._run_dynamic_tests("ctx"))
    assert out.startswith("run_tests|pytest -q ")
    assert "test_temp.py" in out


def test_llm_metrics_env_and_context_helpers_and_sink_edges(monkeypatch):
    monkeypatch.setattr(lm.os, "getenv", lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError("boom")))
    assert lm._env_float("X", 1.25) == 1.25

    token = lm.set_current_metrics_user_id(" user-1 ")
    assert lm.get_current_metrics_user_id() == "user-1"
    lm.reset_current_metrics_user_id(token)

    collector = lm.LLMMetricsCollector()
    collector.set_usage_sink(lambda _evt: _AwaitableNoop())
    collector.record(provider="openai", model="gpt-4o", latency_ms=1)

    collector.set_usage_sink(lambda _evt: (_ for _ in ()).throw(RuntimeError("sink err")))
    collector.record(provider="openai", model="gpt-4o", latency_ms=1)


def test_config_openai_anthropic_validation_and_summary_print(capsys):
    old_provider = Config.AI_PROVIDER
    old_openai = Config.OPENAI_API_KEY
    old_anthropic = Config.ANTHROPIC_API_KEY
    old_model = Config.OPENAI_MODEL
    old_anthropic_model = Config.ANTHROPIC_MODEL
    try:
        Config.AI_PROVIDER = "openai"
        Config.OPENAI_API_KEY = ""
        assert Config.validate_critical_settings() is False

        Config.AI_PROVIDER = "anthropic"
        Config.ANTHROPIC_API_KEY = ""
        assert Config.validate_critical_settings() is False

        Config.AI_PROVIDER = "openai"
        Config.OPENAI_MODEL = "gpt-4o-mini"
        Config.print_config_summary()
        assert "OpenAI Modeli" in capsys.readouterr().out

        Config.AI_PROVIDER = "anthropic"
        Config.ANTHROPIC_MODEL = "claude-3-5-haiku-latest"
        Config.print_config_summary()
        assert "Anthropic Modeli" in capsys.readouterr().out
    finally:
        Config.AI_PROVIDER = old_provider
        Config.OPENAI_API_KEY = old_openai
        Config.ANTHROPIC_API_KEY = old_anthropic
        Config.OPENAI_MODEL = old_model
        Config.ANTHROPIC_MODEL = old_anthropic_model
