"""Multi-agent çekirdek bileşenleri.

Döngüsel importları önlemek için paket düzeyindeki tüm ağır importlar lazy yapılır.
"""

from .contracts import ExternalTrigger, FederationTaskEnvelope, FederationTaskResult, TaskEnvelope, TaskResult

__all__ = [
    "TaskEnvelope",
    "TaskResult",
    "ExternalTrigger",
    "FederationTaskEnvelope",
    "FederationTaskResult",
    "MemoryHub",
    "AgentRegistry",
    "SupervisorAgent",
]


def __getattr__(name: str):
    if name == "MemoryHub":
        from .memory_hub import MemoryHub

        return MemoryHub
    if name == "AgentRegistry":
        from .registry import AgentRegistry

        return AgentRegistry
    if name == "SupervisorAgent":
        from .supervisor import SupervisorAgent

        return SupervisorAgent
    raise AttributeError(name)
