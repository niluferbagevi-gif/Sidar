from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_agents_and_integration_managers_read_runtime_keys_from_config_py(
    tmp_path: Path,
) -> None:
    """Validate agent/manager credential wiring through the centralized config module."""
    override_env = tmp_path / "agent-override.env"
    keys_env = tmp_path / "sidar-keys.env"
    rag_dir = tmp_path / "rag"
    db_path = tmp_path / "agents.db"

    override_env.write_text(
        "\n".join(
            [
                "TAVILY_API_KEY=tavily-from-dotenv",
                "SLACK_TOKEN=slack-from-dotenv",
                "JIRA_TOKEN=jira-from-dotenv",
                "META_GRAPH_API_TOKEN=meta-from-dotenv",
                "JWT_SECRET_KEY=jwt-from-dotenv-value-32-characters",
                "API_KEY=api-from-dotenv-value-32-characters",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    keys_env.write_text(
        "\n".join(
            [
                "USE_GPU=false",
                "REQUIRE_GPU=false",
                "AI_PROVIDER=ollama",
                "SEARCH_ENGINE=tavily",
                "TAVILY_API_KEY=tavily-from-keys",
                "GOOGLE_SEARCH_API_KEY=google-key-from-keys",
                "GOOGLE_SEARCH_CX=google-cx-from-keys",
                "SLACK_TOKEN=xoxb-from-keys",
                "SLACK_APP_LEVEL_TOKEN=xapp-from-keys",
                "SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T/B/C",
                "SLACK_DEFAULT_CHANNEL=#sidar-e2e",
                "JIRA_URL=https://sidar.atlassian.net",
                "JIRA_EMAIL=agent@example.com",
                "JIRA_TOKEN=jira-token-from-keys",
                "JIRA_DEFAULT_PROJECT=SID",
                "JIRA_DEFAULT_LABEL=sidar-e2e",
                "JIRA_BASE_URL=https://sidar-base.atlassian.net",
                "JIRA_API_TOKEN=jira-api-token-from-keys",
                "META_GRAPH_API_TOKEN=meta-token-from-keys",
                "META_GRAPH_API_VERSION=v21.0",
                "INSTAGRAM_BUSINESS_ACCOUNT_ID=ig-business-id",
                "FACEBOOK_PAGE_ID=facebook-page-id",
                "WHATSAPP_PHONE_NUMBER_ID=whatsapp-phone-id",
                f"DATABASE_URL=sqlite+aiosqlite:///{db_path}",
                f"RAG_DIR={rag_dir}",
                "JWT_SECRET_KEY=jwt-from-keys-value-32-characters",
                "API_KEY=api-from-keys-value-32-characters",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    script = textwrap.dedent(
        """
        import json
        from pathlib import Path

        from config import Config
        from managers.jira_manager import JiraManager
        from managers.slack_manager import SlackManager
        from managers.web_search import WebSearchManager

        cfg = Config()

        class DummyDocumentStore:
            def __init__(self, store_dir, *args, **kwargs):
                self.store_dir = Path(store_dir)
                self.cfg = kwargs.get("cfg")

            def search(self, query, _filters, mode, session_id):
                return True, f"dummy-docs:{query}:{mode}:{session_id}"

        import agent.roles.researcher_agent as researcher_module
        import agent.roles.poyraz_agent as poyraz_module
        from agent.roles.coder_agent import CoderAgent

        researcher_module.DocumentStore = DummyDocumentStore
        poyraz_module.DocumentStore = DummyDocumentStore

        researcher = researcher_module.ResearcherAgent(cfg=cfg)
        poyraz = poyraz_module.PoyrazAgent(cfg=cfg)
        coder = CoderAgent(cfg=cfg)
        web = WebSearchManager(cfg)
        slack = SlackManager(
            token=cfg.SLACK_TOKEN,
            webhook_url=cfg.SLACK_WEBHOOK_URL,
            default_channel=cfg.SLACK_DEFAULT_CHANNEL,
        )
        jira = JiraManager(
            url=cfg.JIRA_URL,
            token=cfg.JIRA_TOKEN,
            email=cfg.JIRA_EMAIL,
            default_project=cfg.JIRA_DEFAULT_PROJECT,
            base_url=cfg.JIRA_BASE_URL,
            api_token=cfg.JIRA_API_TOKEN,
        )

        assert cfg.TAVILY_API_KEY == "tavily-from-keys"
        assert cfg.SLACK_TOKEN == "xoxb-from-keys"
        assert cfg.JIRA_TOKEN == "jira-token-from-keys"
        assert cfg.JIRA_API_TOKEN == "jira-api-token-from-keys"
        assert cfg.JIRA_DEFAULT_LABEL == "sidar-e2e"
        assert cfg.META_GRAPH_API_TOKEN == "meta-token-from-keys"
        assert cfg.INSTAGRAM_BUSINESS_ACCOUNT_ID == "ig-business-id"

        assert web.tavily_key == cfg.TAVILY_API_KEY
        assert web.google_key == cfg.GOOGLE_SEARCH_API_KEY
        assert researcher.web.tavily_key == cfg.TAVILY_API_KEY
        assert researcher.docs.cfg is cfg
        assert poyraz.web.tavily_key == cfg.TAVILY_API_KEY
        assert poyraz.docs.cfg is cfg
        assert poyraz.social.graph_api_token == cfg.META_GRAPH_API_TOKEN
        assert (
            poyraz.social.instagram_business_account_id
            == cfg.INSTAGRAM_BUSINESS_ACCOUNT_ID
        )
        assert poyraz.social.facebook_page_id == cfg.FACEBOOK_PAGE_ID
        assert poyraz.social.whatsapp_phone_number_id == cfg.WHATSAPP_PHONE_NUMBER_ID
        assert slack.token == cfg.SLACK_TOKEN
        assert slack.webhook_url == cfg.SLACK_WEBHOOK_URL
        assert slack.default_channel == cfg.SLACK_DEFAULT_CHANNEL
        assert jira.url == cfg.JIRA_URL
        assert jira.token == cfg.JIRA_TOKEN
        assert jira.email == cfg.JIRA_EMAIL
        assert jira.default_project == cfg.JIRA_DEFAULT_PROJECT
        assert coder.cfg is cfg
        assert coder.security.cfg is cfg

        print(json.dumps({"ok": True, "role_count": 3}, sort_keys=True))
        """
    )

    env = os.environ.copy()
    for key in ("SIDAR_ENV", "PYTEST_CURRENT_TEST"):
        env.pop(key, None)
    env.update(
        {
            "PYTHONPATH": str(PROJECT_ROOT),
            "DOTENV_FILE": str(override_env),
            "SIDAR_KEYS_FILE": str(keys_env),
        }
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=45,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {
        "ok": True,
        "role_count": 3,
    }
