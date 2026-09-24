"""Autonomous remediation and self-healing configuration defaults."""

from __future__ import annotations

from core.config_env_helpers import get_int_env, get_int_prefixed_env, get_optional_prefixed_env


def load_self_heal_settings() -> dict[str, int | str | None]:
    """Return self-heal settings consumed by the legacy Config facade."""
    return {
        "SELF_HEAL_MAX_PATCHES": get_int_env("SELF_HEAL_MAX_PATCHES", 3),
        "SELF_HEAL_PLAN_MAX_RETRIES": get_int_env("SELF_HEAL_PLAN_MAX_RETRIES", 3),
        "SELF_HEAL_PLAN_TIMEOUT_SECONDS": get_int_env("SELF_HEAL_PLAN_TIMEOUT_SECONDS", 180),
        "SELF_HEAL_SKIP_FULL_SCOPE_MIN_FILES": get_int_env(
            "SELF_HEAL_SKIP_FULL_SCOPE_MIN_FILES", 6
        ),
        "SELF_HEAL_LOCAL_SCOPE_LIMIT": get_int_prefixed_env(
            "SIDAR_SELF_HEAL_LOCAL_SCOPE_LIMIT", "SELF_HEAL_LOCAL_SCOPE_LIMIT", 200
        ),
        "SELF_HEAL_HITL_SCOPE_THRESHOLD": get_int_prefixed_env(
            "SIDAR_SELF_HEAL_HITL_SCOPE_THRESHOLD", "SELF_HEAL_HITL_SCOPE_THRESHOLD", 3
        ),
        "SELF_HEAL_AUTONOMOUS_BATCH_SIZE": get_int_prefixed_env(
            "SIDAR_SELF_HEAL_AUTONOMOUS_BATCH_SIZE", "SELF_HEAL_AUTONOMOUS_BATCH_SIZE", 5
        ),
        "SELF_HEAL_DEFAULT_DECISION": (
            get_optional_prefixed_env(
                "SIDAR_SELF_HEAL_DEFAULT_DECISION", "SELF_HEAL_DEFAULT_DECISION"
            )
            or "prompt"
        )
        .strip()
        .lower(),
        "RUFF_AUTOFIX_UNSAFE_RULES": get_optional_prefixed_env(
            "SIDAR_RUFF_AUTOFIX_UNSAFE_RULES", "RUFF_AUTOFIX_UNSAFE_RULES"
        ),
    }
