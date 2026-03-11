"""Basit process-içi event stream: Supervisor/Coder/Reviewer durumlarını yayınlar."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Dict


@dataclass
class AgentEvent:
    ts: float
    source: str
    message: str


class AgentEventBus:
    def __init__(self) -> None:
        self._subscribers: Dict[int, asyncio.Queue[AgentEvent]] = {}

    def subscribe(self, maxsize: int = 200) -> tuple[int, asyncio.Queue[AgentEvent]]:
        sub_id = int(time.time() * 1000) ^ id(object())
        self._subscribers[sub_id] = asyncio.Queue(maxsize=max(10, maxsize))
        return sub_id, self._subscribers[sub_id]

    def unsubscribe(self, sub_id: int) -> None:
        self._subscribers.pop(sub_id, None)

    async def publish(self, source: str, message: str) -> None:
        evt = AgentEvent(ts=time.time(), source=source, message=message)
        to_drop = []
        for sid, q in self._subscribers.items():
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                to_drop.append(sid)
        for sid in to_drop:
            self.unsubscribe(sid)


_BUS = AgentEventBus()


def get_agent_event_bus() -> AgentEventBus:
    return _BUS
