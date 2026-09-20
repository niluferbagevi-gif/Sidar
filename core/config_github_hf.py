"""GitHub and Hugging Face integration settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env, get_external_bool_env


@dataclass(frozen=True)
class GitHubHuggingFaceSettings:
    """GitHub webhook/API and Hugging Face Hub integration settings."""

    github_token: str
    github_repo: str
    github_webhook_secret: str
    github_webhook_require_signature: bool
    hf_token: str
    hf_hub_offline: bool
    hf_use_local_cache_only: bool


def load_github_huggingface_settings() -> GitHubHuggingFaceSettings:
    """Load GitHub and Hugging Face integration settings from environment variables."""
    return GitHubHuggingFaceSettings(
        github_token=os.getenv("GITHUB_TOKEN", ""),
        github_repo=os.getenv("GITHUB_REPO", ""),
        github_webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
        github_webhook_require_signature=get_bool_env("GITHUB_WEBHOOK_REQUIRE_SIGNATURE", True),
        hf_token=os.getenv("HF_TOKEN", ""),
        hf_hub_offline=get_external_bool_env("HF_HUB_OFFLINE", False),
        hf_use_local_cache_only=get_bool_env("HF_USE_LOCAL_CACHE_ONLY", False),
    )
