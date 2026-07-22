"""Orchestrator and autonomous-operation settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env, get_int_env


@dataclass(frozen=True)
class OrchestratorSettings:
    """ReAct, swarm and background autonomy settings."""

    max_react_steps: int
    agent_max_react_steps: int
    react_timeout: int
    swarm_task_timeout_seconds: int
    swarm_task_timeout_by_model: str
    swarm_task_timeout_seconds_ollama: int
    subtask_max_steps: int
    auto_handle_timeout: int
    enable_autonomous_cron: bool
    autonomous_cron_interval_seconds: int
    autonomous_cron_prompt: str
    enable_swarm_federation: bool
    swarm_federation_shared_secret: str


def load_orchestrator_settings() -> OrchestratorSettings:
    """Load orchestration-related settings from environment variables."""
    max_react_steps = get_int_env("MAX_REACT_STEPS", 10)
    react_timeout = get_int_env("REACT_TIMEOUT", 60)
    swarm_task_timeout_seconds = get_int_env("SWARM_TASK_TIMEOUT_SECONDS", react_timeout)
    return OrchestratorSettings(
        max_react_steps=max_react_steps,
        agent_max_react_steps=get_int_env("AGENT_MAX_REACT_STEPS", max_react_steps),
        react_timeout=react_timeout,
        swarm_task_timeout_seconds=swarm_task_timeout_seconds,
        swarm_task_timeout_by_model=os.getenv("SWARM_TASK_TIMEOUT_BY_MODEL", ""),
        swarm_task_timeout_seconds_ollama=get_int_env(
            "SWARM_TASK_TIMEOUT_SECONDS_OLLAMA",
            swarm_task_timeout_seconds,
        ),
        subtask_max_steps=get_int_env("SUBTASK_MAX_STEPS", 5),
        auto_handle_timeout=get_int_env("AUTO_HANDLE_TIMEOUT", 12),
        enable_autonomous_cron=get_bool_env("ENABLE_AUTONOMOUS_CRON", False),
        autonomous_cron_interval_seconds=get_int_env("AUTONOMOUS_CRON_INTERVAL_SECONDS", 900),
        autonomous_cron_prompt=os.getenv(
            "AUTONOMOUS_CRON_PROMPT",
            "Sistemdeki bekleyen otonom iş fırsatlarını değerlendir ve gerekli aksiyon planını "
            "çıkar.",
        ),
        enable_swarm_federation=get_bool_env("ENABLE_SWARM_FEDERATION", True),
        swarm_federation_shared_secret=os.getenv("SWARM_FEDERATION_SHARED_SECRET", ""),
    )
