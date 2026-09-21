"""Autonomy service webhook settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env


@dataclass(frozen=True)
class AutonomySettings:
    """``web/autonomy_bridge.py``/``web/routes/autonomy.py`` webhook settings."""

    autonomy_service_user_id: str
    autonomy_webhook_secret: str
    autonomy_webhook_require_signature: bool


def load_autonomy_settings() -> AutonomySettings:
    """Load autonomy service webhook settings from environment variables."""
    return AutonomySettings(
        autonomy_service_user_id=os.getenv(
            "AUTONOMY_SERVICE_USER_ID", os.getenv("SYSTEM_USER_ID", "system:autonomy")
        ),
        autonomy_webhook_secret=os.getenv(
            "AUTONOMY_WEBHOOK_SECRET", os.getenv("SIDAR_AUTONOMY_WEBHOOK_SECRET", "")
        ),
        autonomy_webhook_require_signature=get_bool_env(
            "AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE",
            get_bool_env("SIDAR_AUTONOMY_WEBHOOK_REQUIRE_SIGNATURE", True),
        ),
    )
