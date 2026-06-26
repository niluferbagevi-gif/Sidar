from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT_CONFIG = ROOT / ".github/dependabot.yml"


def _dependabot_config() -> dict:
    return yaml.safe_load(DEPENDABOT_CONFIG.read_text(encoding="utf-8"))


def test_dependabot_config_covers_repo_dependency_surfaces() -> None:
    config = _dependabot_config()

    assert config["version"] == 2
    updates = config["updates"]
    ecosystems = {(entry["package-ecosystem"], entry["directory"]) for entry in updates}

    assert ("uv", "/") in ecosystems
    assert ("npm", "/web_ui_react") in ecosystems
    assert ("github-actions", "/") in ecosystems
    assert ("docker", "/") in ecosystems
    assert ("docker-compose", "/") in ecosystems


def test_dependabot_config_uses_weekly_grouped_prs_with_labels() -> None:
    updates = _dependabot_config()["updates"]

    for entry in updates:
        assert entry["schedule"]["interval"] == "weekly"
        assert entry["schedule"]["day"] == "monday"
        assert entry["schedule"]["timezone"] == "Etc/UTC"
        assert entry["open-pull-requests-limit"] == 5
        assert "dependencies" in entry["labels"]
        assert entry["commit-message"]["prefix"] == "deps"
        assert entry["commit-message"]["include"] == "scope"
        assert entry["groups"]
        for group in entry["groups"].values():
            assert group["patterns"] == ["*"]
            assert group["update-types"] == ["minor", "patch"]
