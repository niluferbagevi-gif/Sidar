"""Tests for marketing/social platform integration settings resolution."""

from core.config_social_integrations import load_social_integration_settings

_ALL_KEYS = (
    "META_GRAPH_API_TOKEN",
    "META_GRAPH_API_VERSION",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID",
    "FACEBOOK_PAGE_ID",
    "WHATSAPP_PHONE_NUMBER_ID",
    "SLACK_TOKEN",
    "SLACK_WEBHOOK_URL",
    "SLACK_DEFAULT_CHANNEL",
    "JIRA_URL",
    "JIRA_TOKEN",
    "JIRA_EMAIL",
    "JIRA_DEFAULT_PROJECT",
    "JIRA_BASE_URL",
    "JIRA_API_TOKEN",
    "TEAMS_WEBHOOK_URL",
)


def _clear_all(monkeypatch) -> None:
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_defaults_are_empty_except_meta_graph_api_version(monkeypatch):
    """With nothing configured, every field is blank except the documented API version default."""
    _clear_all(monkeypatch)

    settings = load_social_integration_settings()

    assert settings.meta_graph_api_token == ""
    assert settings.meta_graph_api_version == "v20.0"
    assert settings.instagram_business_account_id == ""
    assert settings.facebook_page_id == ""
    assert settings.whatsapp_phone_number_id == ""
    assert settings.slack_token == ""
    assert settings.slack_webhook_url == ""
    assert settings.slack_default_channel == ""
    assert settings.jira_url == ""
    assert settings.jira_token == ""
    assert settings.jira_email == ""
    assert settings.jira_default_project == ""
    assert settings.jira_base_url == ""
    assert settings.jira_api_token == ""
    assert settings.teams_webhook_url == ""


def test_each_field_resolves_from_its_own_environment_variable(monkeypatch):
    """Every field reads its own env var untouched, independent of the others."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("META_GRAPH_API_TOKEN", "meta-token")
    monkeypatch.setenv("META_GRAPH_API_VERSION", "v21.0")
    monkeypatch.setenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "ig-123")
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "fb-456")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "wa-789")
    monkeypatch.setenv("SLACK_TOKEN", "xoxb-slack")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/abc")
    monkeypatch.setenv("SLACK_DEFAULT_CHANNEL", "#general")
    monkeypatch.setenv("JIRA_EMAIL", "ops@example.com")
    monkeypatch.setenv("JIRA_DEFAULT_PROJECT", "SIDAR")
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://outlook.office.example/webhook")

    settings = load_social_integration_settings()

    assert settings.meta_graph_api_token == "meta-token"
    assert settings.meta_graph_api_version == "v21.0"
    assert settings.instagram_business_account_id == "ig-123"
    assert settings.facebook_page_id == "fb-456"
    assert settings.whatsapp_phone_number_id == "wa-789"
    assert settings.slack_token == "xoxb-slack"
    assert settings.slack_webhook_url == "https://hooks.slack.example/abc"
    assert settings.slack_default_channel == "#general"
    assert settings.jira_email == "ops@example.com"
    assert settings.jira_default_project == "SIDAR"
    assert settings.teams_webhook_url == "https://outlook.office.example/webhook"


def test_jira_base_url_and_api_token_fall_back_to_jira_url_and_token(monkeypatch):
    """Legacy alternate Jira naming falls back to the primary URL/token when unset."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "https://sidar.atlassian.net")
    monkeypatch.setenv("JIRA_TOKEN", "primary-token")

    settings = load_social_integration_settings()

    assert settings.jira_url == "https://sidar.atlassian.net"
    assert settings.jira_token == "primary-token"
    assert settings.jira_base_url == "https://sidar.atlassian.net"
    assert settings.jira_api_token == "primary-token"


def test_jira_base_url_and_api_token_are_independently_overridable(monkeypatch):
    """An explicit JIRA_BASE_URL/JIRA_API_TOKEN wins over the JIRA_URL/JIRA_TOKEN fallback."""
    _clear_all(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "https://sidar.atlassian.net")
    monkeypatch.setenv("JIRA_TOKEN", "primary-token")
    monkeypatch.setenv("JIRA_BASE_URL", "https://sidar-alt.atlassian.net")
    monkeypatch.setenv("JIRA_API_TOKEN", "alternate-token")

    settings = load_social_integration_settings()

    assert settings.jira_url == "https://sidar.atlassian.net"
    assert settings.jira_token == "primary-token"
    assert settings.jira_base_url == "https://sidar-alt.atlassian.net"
    assert settings.jira_api_token == "alternate-token"
