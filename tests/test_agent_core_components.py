import asyncio
import importlib.util
import sys
import types
from pathlib import Path

from tests.test_sidar_agent_runtime import SidarAgent, _make_agent_for_runtime

ROOT = Path(__file__).resolve().parents[1]


def _load_core_modules():
    agent_pkg = types.ModuleType("agent")
    agent_pkg.__path__ = [str(ROOT / "agent")]
    core_pkg = types.ModuleType("agent.core")
    core_pkg.__path__ = [str(ROOT / "agent" / "core")]
    sys.modules.setdefault("agent", agent_pkg)
    sys.modules.setdefault("agent.core", core_pkg)

    contracts_spec = importlib.util.spec_from_file_location("agent.core.contracts", ROOT / "agent" / "core" / "contracts.py")
    contracts_mod = importlib.util.module_from_spec(contracts_spec)
    assert contracts_spec and contracts_spec.loader
    sys.modules["agent.core.contracts"] = contracts_mod
    contracts_spec.loader.exec_module(contracts_mod)

    hub_spec = importlib.util.spec_from_file_location("agent.core.memory_hub", ROOT / "agent" / "core" / "memory_hub.py")
    hub_mod = importlib.util.module_from_spec(hub_spec)
    assert hub_spec and hub_spec.loader
    sys.modules["agent.core.memory_hub"] = hub_mod
    hub_spec.loader.exec_module(hub_mod)


    base_stub = types.ModuleType("agent.base_agent")
    class _BaseAgent:
        pass
    base_stub.BaseAgent = _BaseAgent
    sys.modules["agent.base_agent"] = base_stub

    reg_spec = importlib.util.spec_from_file_location("agent.core.registry", ROOT / "agent" / "core" / "registry.py")
    reg_mod = importlib.util.module_from_spec(reg_spec)
    assert reg_spec and reg_spec.loader
    sys.modules["agent.core.registry"] = reg_mod
    reg_spec.loader.exec_module(reg_mod)

    return contracts_mod.DelegationRequest, hub_mod.MemoryHub, reg_mod.AgentRegistry


DelegationRequest, MemoryHub, AgentRegistry = _load_core_modules()


class DummyAgent:
    pass


def test_memory_hub_global_and_role_context_limits():
    hub = MemoryHub()
    for i in range(6):
        hub.add_global(f"g{i}")
    for i in range(4):
        hub.add_role_note("reviewer", f"r{i}")

    assert hub.global_context(limit=3) == ["g3", "g4", "g5"]
    assert hub.role_context("reviewer", limit=2) == ["r2", "r3"]


def test_agent_registry_register_get_and_roles():
    reg = AgentRegistry()
    agent = DummyAgent()

    reg.register("reviewer", agent)

    assert reg.has("reviewer") is True
    assert reg.has("coder") is False
    assert reg.get("reviewer") is agent

    roles = reg.roles()
    assert isinstance(roles, tuple)
    assert "reviewer" in roles
    assert len(roles) == 1


def _load_event_stream_module():
    redis_async_mod = types.ModuleType("redis.asyncio")
    redis_exc_mod = types.ModuleType("redis.exceptions")

    class _Redis:
        @classmethod
        def from_url(cls, *_a, **_k):
            return cls()

        async def ping(self):
            return True

    class _ResponseError(Exception):
        pass

    redis_async_mod.Redis = _Redis
    redis_exc_mod.ResponseError = _ResponseError

    saved_async = sys.modules.get("redis.asyncio")
    saved_exc = sys.modules.get("redis.exceptions")
    try:
        sys.modules["redis.asyncio"] = redis_async_mod
        sys.modules["redis.exceptions"] = redis_exc_mod
        spec = importlib.util.spec_from_file_location("event_stream_under_test", Path("agent/core/event_stream.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["event_stream_under_test"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if saved_async is None:
            sys.modules.pop("redis.asyncio", None)
        else:
            sys.modules["redis.asyncio"] = saved_async
        if saved_exc is None:
            sys.modules.pop("redis.exceptions", None)
        else:
            sys.modules["redis.exceptions"] = saved_exc


def test_event_bus_fanout_drops_full_subscriber_without_buffer_and_unsubscribe():
    mod = _load_event_stream_module()
    bus = mod.AgentEventBus()

    sid, q = bus.subscribe(maxsize=10)
    for i in range(10):
        q.put_nowait(mod.AgentEvent(ts=float(i), source="a", message=f"m{i}"))

    bus._fanout_local(mod.AgentEvent(ts=20.0, source="b", message="n"))
    assert sid not in bus._subscribers


def test_event_bus_drain_buffered_events_handles_full_queue_and_then_progress():
    mod = _load_event_stream_module()
    bus = mod.AgentEventBus()

    sid, q = bus.subscribe(maxsize=10)
    for i in range(10):
        q.put_nowait(mod.AgentEvent(ts=float(i), source="a", message=f"m{i}"))
    bus._buffered_events[sid] = mod.deque([mod.AgentEvent(ts=20.0, source="b", message="n")], maxlen=4)

    progressed_full = asyncio.run(bus._drain_buffered_events_once())
    assert progressed_full is True
    assert q.qsize() == 10

    _ = q.get_nowait()
    progressed_put = asyncio.run(bus._drain_buffered_events_once())
    assert progressed_put is True
    messages = []
    while not q.empty():
        messages.append(q.get_nowait().message)
    assert "n" in messages


def test_sidar_agent_try_multi_agent_returns_fallback_for_blank_supervisor_output():
    agent = _make_agent_for_runtime()

    class _Supervisor:
        async def run_task(self, _user_input):
            return "   "

    agent._supervisor = _Supervisor()
    out = asyncio.run(SidarAgent._try_multi_agent(agent, "istek"))

    assert "Supervisor geçerli bir çıktı üretemedi" in out
