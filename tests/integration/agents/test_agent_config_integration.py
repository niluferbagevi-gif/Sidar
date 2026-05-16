"""End-to-end integration: agents read centralized config secrets losslessly.

This test exercises the .env loading chain introduced in the centralized
config.py refactor. It writes a layered set of dotenv files (base + the
home-style secrets file referenced by SIDAR_KEYS_FILE), reloads config,
and asserts that:

1. ``Config.LOADED_ENV_FILES`` records the override chain.
2. ``Config.get_env_loading_report()`` reflects the resolved priority.
3. Managers that agents instantiate for external API calls
   (WebSearchManager, JiraManager, SlackManager, GitHubManager) read
   their secrets from Config without dropping/transforming values.
4. ``Config.validate_critical_settings()`` accepts the configured setup.

The aim is not to hit external APIs — every network boundary is mocked
— but to prove the wiring between Config and agent-facing managers is
intact end-to-end after env_keys.py was removed.
"""

from __future__ import annotations

import importlib
import sys

import pytest


def _write_layered_env(tmp_path, *, base: dict[str, str], keys: dict[str, str]) -> tuple:
    """Write base .env + sidar_keys.env files in the layout config.py expects."""
    base_env = tmp_path / "base.env"
    base_env.write_text(
        "\n".join(f"{key}={value}" for key, value in base.items()) + "\n",
        encoding="utf-8",
    )
    keys_env = tmp_path / "sidar_keys.env"
    keys_env.write_text(
        "\n".join(f"{key}={value}" for key, value in keys.items()) + "\n",
        encoding="utf-8",
    )
    return base_env, keys_env


@pytest.fixture
def reloaded_config_with_layered_env(monkeypatch, tmp_path):
    """Reload config.py with a deterministic .env override chain in place."""
    base_payload = {
        "AI_PROVIDER": "ollama",
        "SEARCH_ENGINE": "tavily",
        "TAVILY_API_KEY": "base-tavily-key",
        "GOOGLE_SEARCH_API_KEY": "base-google-key",
        "GOOGLE_SEARCH_CX": "base-google-cx",
        "GITHUB_TOKEN": "base-github-token",
        "GITHUB_REPO": "owner/sidar",
        "SLACK_TOKEN": "xoxb-base-slack-token",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/AAA/BBB/CCC",
        "SLACK_DEFAULT_CHANNEL": "#sidar",
        "JIRA_URL": "https://example.atlassian.net",
        "JIRA_TOKEN": "base-jira-token",
        "JIRA_EMAIL": "ops@example.com",
        "JIRA_DEFAULT_PROJECT": "SIDAR",
        "JWT_SECRET_KEY": "integration-jwt-secret-value-1234567890",
        "API_KEY": "integration-api-key-value-1234567890",
    }
    # The sidar_keys file is loaded last with override=True, so it must win
    # for any overlapping field — proving the priority chain is honored.
    keys_payload = {
        "TAVILY_API_KEY": "overridden-tavily-key",
        "OPENAI_API_KEY": "sk-overridden-openai-key",
    }
    base_env, keys_env = _write_layered_env(
        tmp_path, base=base_payload, keys=keys_payload
    )

    # Make sure no stray host envs pollute the assertion. Each var we care about
    # must come from the dotenv files we just wrote.
    for var in (
        *base_payload.keys(),
        *keys_payload.keys(),
        "SIDAR_ENV",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "DATABASE_URL",
        "SIDAR_CONTAINER_DATABASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setenv("DOTENV_FILE", str(base_env))
    monkeypatch.setenv("SIDAR_KEYS_FILE", str(keys_env))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "agent_config_integration")

    # Earlier unit tests may have removed `config` from sys.modules, so use a
    # fresh import_module before reloading to make this fixture robust to that.
    config_module = importlib.import_module("config")
    if sys.modules.get("config") is not config_module:
        sys.modules["config"] = config_module
    reloaded = importlib.reload(config_module)
    return reloaded, base_env, keys_env


@pytest.mark.integration
def test_loaded_env_chain_records_priority_layering(reloaded_config_with_layered_env):
    reloaded, base_env, keys_env = reloaded_config_with_layered_env

    labels = [entry["label"] for entry in reloaded.LOADED_ENV_FILES]
    assert "dotenv_file" in labels
    assert "sidar_keys" in labels

    report = reloaded.get_env_loading_report()
    assert "dotenv_file" in report["override_chain"]
    assert "sidar_keys" in report["override_chain"]
    # sidar_keys has higher priority (40) and must be loaded after dotenv_file (30)
    chain_priorities = [entry["priority"] for entry in report["files"]]
    assert chain_priorities == sorted(chain_priorities)


@pytest.mark.integration
def test_sidar_keys_overrides_dotenv_file_for_overlapping_secrets(
    reloaded_config_with_layered_env,
):
    """The home-style keys file (priority 40) must win over .env (priority 30)."""
    reloaded, _base, _keys = reloaded_config_with_layered_env
    assert reloaded.Config.TAVILY_API_KEY == "overridden-tavily-key"
    assert reloaded.Config.OPENAI_API_KEY == "sk-overridden-openai-key"
    # Non-overlapping values from base remain intact.
    assert reloaded.Config.GOOGLE_SEARCH_API_KEY == "base-google-key"


@pytest.mark.integration
def test_web_search_manager_reads_keys_from_config(reloaded_config_with_layered_env):
    """ResearcherAgent/PoyrazAgent's WebSearchManager must see the merged secrets."""
    reloaded, _, _ = reloaded_config_with_layered_env
    from managers.web_search import WebSearchManager

    mgr = WebSearchManager(reloaded.Config)
    assert mgr.tavily_key == "overridden-tavily-key"
    assert mgr.google_key == "base-google-key"
    assert mgr.google_cx == "base-google-cx"
    assert mgr.engine == "tavily"
    assert mgr.is_available() is True


@pytest.mark.integration
def test_slack_manager_reads_keys_from_config(reloaded_config_with_layered_env):
    reloaded, _, _ = reloaded_config_with_layered_env
    from managers.slack_manager import SlackManager

    mgr = SlackManager(
        token=reloaded.Config.SLACK_TOKEN,
        webhook_url=reloaded.Config.SLACK_WEBHOOK_URL,
        default_channel=reloaded.Config.SLACK_DEFAULT_CHANNEL,
    )
    assert mgr.token == "xoxb-base-slack-token"
    assert mgr.webhook_url == "https://hooks.slack.com/services/AAA/BBB/CCC"
    assert mgr.default_channel == "#sidar"


@pytest.mark.integration
def test_jira_manager_reads_keys_from_config(reloaded_config_with_layered_env):
    reloaded, _, _ = reloaded_config_with_layered_env
    from managers.jira_manager import JiraManager

    mgr = JiraManager(
        url=reloaded.Config.JIRA_URL,
        token=reloaded.Config.JIRA_TOKEN,
        email=reloaded.Config.JIRA_EMAIL,
        default_project=reloaded.Config.JIRA_DEFAULT_PROJECT,
    )
    assert mgr.url == "https://example.atlassian.net"
    assert mgr.token == "base-jira-token"
    assert mgr.email == "ops@example.com"
    assert mgr.default_project == "SIDAR"


@pytest.mark.integration
def test_github_manager_reads_token_from_config(
    reloaded_config_with_layered_env, monkeypatch
):
    reloaded, _, _ = reloaded_config_with_layered_env
    from managers import github_manager as gh_mod

    # GitHubManager._init_client() reaches out to GitHub on construction.
    # Stub it out so this stays an offline integration test of the Config wiring.
    monkeypatch.setattr(gh_mod.GitHubManager, "_init_client", lambda self: None)

    mgr = gh_mod.GitHubManager(reloaded.Config.GITHUB_TOKEN, reloaded.Config.GITHUB_REPO)
    assert mgr.token == "base-github-token"
    assert mgr.repo_name == "owner/sidar"


@pytest.mark.integration
def test_validate_critical_settings_accepts_layered_config(
    reloaded_config_with_layered_env, monkeypatch
):
    """End-to-end validation: configured ollama + keys must pass critical-settings check."""
    reloaded, _, _ = reloaded_config_with_layered_env
    Config = reloaded.Config

    # Skip the live ollama HTTP probe — we only care that secret validation passes.
    import sys
    import types as _types

    class _FakeResp:
        status_code = 200

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, _url):
            return _FakeResp()

    monkeypatch.setitem(sys.modules, "httpx", _types.SimpleNamespace(Client=_FakeClient))
    # Avoid touching the actual GPU detection path during this check.
    monkeypatch.setattr(
        Config, "_ensure_hardware_info_loaded", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(
        Config, "_apply_gpu_memory_safety_check", classmethod(lambda cls: None)
    )
    monkeypatch.setattr(Config, "REQUIRE_GPU", False)
    monkeypatch.setattr(Config, "USE_GPU", False)

    assert Config.validate_critical_settings() is True


@pytest.mark.integration
def test_researcher_and_poyraz_agents_propagate_keys_to_web_search(
    reloaded_config_with_layered_env, monkeypatch
):
    """Agent construction must pipe Config values into their WebSearchManager."""
    reloaded, _, _ = reloaded_config_with_layered_env

    class _NoopLLMClient:
        def __init__(self, *args, **kwargs):
            pass

    class _NoopDocStore:
        def __init__(self, *args, **kwargs):
            self.cfg = kwargs.get("cfg")

        def search(self, *args, **kwargs):
            return True, ""

    class _NoopSocialMediaManager:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    # Patch module-level attributes that base_agent + role agents resolve via
    # top-level imports. This avoids importlib.reload, which trips agent's
    # lazy __getattr__ for the "base_agent" symbol.
    import agent.base_agent as base_agent_mod
    import agent.roles.poyraz_agent as poyraz_mod
    import agent.roles.researcher_agent as researcher_mod

    monkeypatch.setattr(base_agent_mod, "LLMClient", _NoopLLMClient)
    monkeypatch.setattr(researcher_mod, "DocumentStore", _NoopDocStore)
    monkeypatch.setattr(poyraz_mod, "DocumentStore", _NoopDocStore)
    monkeypatch.setattr(poyraz_mod, "SocialMediaManager", _NoopSocialMediaManager)

    researcher = researcher_mod.ResearcherAgent(cfg=reloaded.Config())
    poyraz = poyraz_mod.PoyrazAgent(cfg=reloaded.Config())

    # Both agents must surface the overridden Tavily key losslessly.
    assert researcher.web.tavily_key == "overridden-tavily-key"
    assert poyraz.web.tavily_key == "overridden-tavily-key"
    # The web tool registration must succeed so downstream LLM tool dispatch
    # can reach the configured search backend.
    assert "web_search" in researcher.tools
    assert "web_search" in poyraz.tools
