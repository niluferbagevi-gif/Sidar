from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_agents_and_integrations_read_authorized_keys_from_config_dotenv_chain(
    tmp_path: Path,
) -> None:
    """E2E-smoke the config.py dotenv chain used by authorization-aware agents/tools."""
    env_file = tmp_path / "agent-runtime.env"
    keys_file = tmp_path / "sidar_keys.env"
    rag_dir = tmp_path / "rag"
    base_dir = tmp_path / "workspace"

    env_file.write_text(
        "\n".join(
            [
                "SIDAR_ENV=test",
                "AI_PROVIDER=ollama",
                "USE_GPU=false",
                "JWT_SECRET_KEY=agent-e2e-jwt-secret-32-plus-chars",
                "API_KEY=agent-e2e-api-key-32-plus-chars",
                f"BASE_DIR={base_dir}",
                f"RAG_DIR={rag_dir}",
                "RAG_TOP_K=7",
                "RAG_CHUNK_SIZE=321",
                "RAG_CHUNK_OVERLAP=12",
                "TAVILY_API_KEY=env-tavily-should-be-overridden",
                "GOOGLE_SEARCH_API_KEY=env-google-key",
                "GOOGLE_SEARCH_CX=env-google-cx",
                'SLACK_DEFAULT_CHANNEL="#ops-from-env"',
                "JIRA_URL=https://sidar.atlassian.net",
                "JIRA_EMAIL=ops@example.test",
                "JIRA_DEFAULT_PROJECT=SID",
                "META_GRAPH_API_TOKEN=meta-env-token",
                "INSTAGRAM_BUSINESS_ACCOUNT_ID=ig-env-id",
                "FACEBOOK_PAGE_ID=fb-env-id",
                "WHATSAPP_PHONE_NUMBER_ID=wa-env-id",
                "META_GRAPH_API_VERSION=v20.0",
            ]
        ),
        encoding="utf-8",
    )
    keys_file.write_text(
        "\n".join(
            [
                "TAVILY_API_KEY=keys-tavily-token",
                "SLACK_TOKEN=xoxb-keys-token",
                "SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T000/B000/secret",
                "JIRA_TOKEN=keys-jira-token",
                "HF_TOKEN=keys-hf-token",
            ]
        ),
        encoding="utf-8",
    )

    script = textwrap.dedent(
        """
        from __future__ import annotations

        import json
        from pathlib import Path
        from typing import Any

        import config
        from agent.roles.poyraz_agent import PoyrazAgent
        from agent.roles.researcher_agent import ResearcherAgent
        from managers.jira_manager import JiraManager
        from managers.slack_manager import SlackManager
        import agent.roles.poyraz_agent as poyraz_module
        import agent.roles.researcher_agent as researcher_module

        class FakeDocumentStore:
            def __init__(
                self,
                store_dir: Path,
                top_k: int | None = None,
                chunk_size: int | None = None,
                chunk_overlap: int | None = None,
                use_gpu: bool = False,
                gpu_device: int = 0,
                mixed_precision: bool = False,
                cfg: Any | None = None,
                **_: Any,
            ) -> None:
                self.store_dir = Path(store_dir)
                self.top_k = top_k
                self.chunk_size = chunk_size
                self.chunk_overlap = chunk_overlap
                self.use_gpu = use_gpu
                self.cfg = cfg

            def search(self, query: str, *_args: Any, **_kwargs: Any) -> tuple[bool, str]:
                return True, f"rag:{query}:{self.top_k}:{self.chunk_size}:{self.chunk_overlap}"

        researcher_module.DocumentStore = FakeDocumentStore
        poyraz_module.DocumentStore = FakeDocumentStore

        cfg = config.Config()
        researcher = ResearcherAgent(cfg)
        poyraz = PoyrazAgent(cfg)
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
        )

        assert researcher.web.tavily_key == "keys-tavily-token"
        assert researcher.web.google_key == "env-google-key"
        assert researcher.web.google_cx == "env-google-cx"
        assert researcher.docs.store_dir == Path(cfg.RAG_DIR)
        assert researcher.docs.top_k == 7
        assert researcher.docs.chunk_size == 321
        assert researcher.docs.chunk_overlap == 12

        assert poyraz.web.tavily_key == "keys-tavily-token"
        assert poyraz.social.graph_api_token == "meta-env-token"
        assert poyraz.social.instagram_business_account_id == "ig-env-id"
        assert poyraz.social.facebook_page_id == "fb-env-id"
        assert poyraz.social.whatsapp_phone_number_id == "wa-env-id"
        assert poyraz.social.is_available("instagram") is True

        assert slack.token == "xoxb-keys-token"
        assert slack.webhook_url.startswith("https://hooks.slack.com/services/")
        assert slack.default_channel == "#ops-from-env"
        assert jira.url == "https://sidar.atlassian.net"
        assert jira.token == "keys-jira-token"
        assert jira.email == "ops@example.test"
        assert jira.default_project == "SID"
        assert jira.is_available() is True

        loaded_labels = [event["label"] for event in config.get_dotenv_load_report() if event["loaded"]]
        assert "explicit:DOTENV_FILE" in loaded_labels
        assert "secret:SIDAR_KEYS_FILE" in loaded_labels

        print(
            json.dumps(
                {
                    "researcher_tavily": researcher.web.tavily_key,
                    "poyraz_meta": poyraz.social.graph_api_token,
                    "slack_channel": slack.default_channel,
                    "jira_project": jira.default_project,
                    "loaded_labels": loaded_labels,
                },
                sort_keys=True,
            )
        )
        """
    )

    env = os.environ.copy()
    for key in (
        "SIDAR_ENV",
        "DOTENV_FILE",
        "SIDAR_KEYS_FILE",
        "TAVILY_API_KEY",
        "SLACK_TOKEN",
        "SLACK_WEBHOOK_URL",
        "JIRA_TOKEN",
    ):
        env.pop(key, None)
    env.update(
        {
            "DOTENV_FILE": str(env_file),
            "SIDAR_KEYS_FILE": str(keys_file),
            "PYTHONPATH": str(PROJECT_ROOT),
        }
    )

    completed = subprocess.run(
        ["uv", "run", "python", "-"],
        cwd=PROJECT_ROOT,
        input=script,
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=45,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload == {
        "jira_project": "SID",
        "loaded_labels": ["advanced", "explicit:DOTENV_FILE", "secret:SIDAR_KEYS_FILE"],
        "poyraz_meta": "meta-env-token",
        "researcher_tavily": "keys-tavily-token",
        "slack_channel": "#ops-from-env",
    }
