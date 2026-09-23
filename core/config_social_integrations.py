"""Marketing/social platform integration settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env

# Sosyal medya yayını (Meta Graph / WhatsApp) deneysel bir özelliktir ve opt-in'dir.
EXPERIMENTAL_SOCIAL_PUBLISHING_ENV = "ENABLE_EXPERIMENTAL_SOCIAL_PUBLISHING"
EXPERIMENTAL_SOCIAL_PUBLISHING_DISABLED_REASON = (
    "Deneysel sosyal medya yayını kapalı; açmak için "
    f"{EXPERIMENTAL_SOCIAL_PUBLISHING_ENV}=true ayarlayın"
)


@dataclass(frozen=True)
class SocialIntegrationSettings:
    """Meta/Instagram/Facebook/WhatsApp, Slack, Jira and Teams integration settings."""

    enable_experimental_social_publishing: bool
    meta_graph_api_token: str
    meta_graph_api_version: str
    instagram_business_account_id: str
    facebook_page_id: str
    whatsapp_phone_number_id: str
    slack_token: str
    slack_webhook_url: str
    slack_default_channel: str
    jira_url: str
    jira_token: str
    jira_email: str
    jira_default_project: str
    jira_base_url: str
    jira_api_token: str
    teams_webhook_url: str


def load_social_integration_settings() -> SocialIntegrationSettings:
    """Load marketing/social platform integration settings from environment variables."""
    jira_url = os.getenv("JIRA_URL", "")
    jira_token = os.getenv("JIRA_TOKEN", "")
    return SocialIntegrationSettings(
        # Deneysel: Meta Graph/WhatsApp yayını açıkça opt-in edilmeden dış API'ye gitmez.
        enable_experimental_social_publishing=get_bool_env(
            EXPERIMENTAL_SOCIAL_PUBLISHING_ENV, False
        ),
        meta_graph_api_token=os.getenv("META_GRAPH_API_TOKEN", ""),
        meta_graph_api_version=os.getenv("META_GRAPH_API_VERSION", "v20.0"),
        instagram_business_account_id=os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", ""),
        facebook_page_id=os.getenv("FACEBOOK_PAGE_ID", ""),
        whatsapp_phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
        slack_token=os.getenv("SLACK_TOKEN", ""),
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL", ""),
        slack_default_channel=os.getenv("SLACK_DEFAULT_CHANNEL", ""),
        jira_url=jira_url,
        jira_token=jira_token,
        jira_email=os.getenv("JIRA_EMAIL", ""),
        jira_default_project=os.getenv("JIRA_DEFAULT_PROJECT", ""),
        # Geriye dönük/alternatif adlandırma uyumluluğu.
        jira_base_url=os.getenv("JIRA_BASE_URL", jira_url),
        jira_api_token=os.getenv("JIRA_API_TOKEN", jira_token),
        teams_webhook_url=os.getenv("TEAMS_WEBHOOK_URL", ""),
    )
