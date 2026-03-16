import asyncio
import time

from agent.core.event_stream import AgentEvent, AgentEventBus, get_agent_event_bus


def test_event_bus_publish_and_subscribe_roundtrip():
    bus = get_agent_event_bus()

    async def _run():
        sid, q = bus.subscribe()
        await bus.publish("supervisor", "Kod yazılıyor")
        evt = await asyncio.wait_for(q.get(), timeout=1)
        bus.unsubscribe(sid)
        return evt

    evt = asyncio.run(_run())
    assert evt.source == "supervisor"
    assert "Kod yazılıyor" in evt.message


def test_event_bus_drops_full_subscriber_queue():
    bus = AgentEventBus()

    async def _run():
        sid, q = bus.subscribe(maxsize=10)
        for i in range(11):
            await bus.publish("agent", f"msg-{i}")
        return sid, q

    sid, q = asyncio.run(_run())

    assert sid not in bus._subscribers
    assert q.qsize() == 10


def test_event_bus_keeps_healthy_subscribers_when_one_is_full():
    bus = AgentEventBus()

    full_q = asyncio.Queue(maxsize=10)
    for i in range(10):
        full_q.put_nowait(f"prefill-{i}")
    live_q = asyncio.Queue(maxsize=10)

    bus._subscribers = {1: full_q, 2: live_q}
    bus._fanout_local(AgentEvent(ts=time.time(), source="agent", message="keep-this"))

    assert 1 not in bus._subscribers
    assert 2 in bus._subscribers
    assert full_q.qsize() == 10
    evt = live_q.get_nowait()
    assert evt.message == "keep-this"
