from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Apply deterministic environment variables for tests requiring API credentials."""
    env_values = {
        "OPENAI_API_KEY": "test-openai-key",
        "ANTHROPIC_API_KEY": "test-anthropic-key",
        "GOOGLE_API_KEY": "test-google-key",
        "GITHUB_TOKEN": "test-github-token",
        "JIRA_TOKEN": "test-jira-token",
    }
    for key, value in env_values.items():
        monkeypatch.setenv(key, value)
    yield env_values
