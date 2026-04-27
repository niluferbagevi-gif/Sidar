from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core.event_stream import AgentEvent, AgentEventBus


class BaseEventBusBackend(abc.ABC):
    """Remote transport backend strategy interface."""

    def __init__(self, bus: AgentEventBus) -> None:
        self.bus = bus

    @abc.abstractmethod
    def schedule_bootstrap(self) -> None:
        """Schedule backend listener bootstrap if needed."""

    @abc.abstractmethod
    async def publish(self, evt: AgentEvent) -> bool:
        """Publish an event via backend transport."""
