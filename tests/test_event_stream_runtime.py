import asyncio

from agent.core.event_stream import get_agent_event_bus


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