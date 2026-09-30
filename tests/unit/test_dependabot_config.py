"""Tests for the Dependabot configuration."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT_CONFIG = ROOT / ".github/dependabot.yml"


def _dependabot_config() -> dict:
    return yaml.safe_load(DEPENDABOT_CONFIG.read_text(encoding="utf-8"))


def test_dependabot_config_covers_repo_dependency_surfaces() -> None:
    """Dependabot config covers repo dependency surfaces."""
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
    """Dependabot config uses weekly grouped prs with labels."""
    updates = _dependabot_config()["updates"]

    for entry in updates:
        assert entry["schedule"]["interval"] == "weekly"
        assert entry["schedule"]["day"] == "monday"
        assert entry["schedule"]["timezone"] == "Etc/UTC"
        assert entry["open-pull-requests-limit"] == 2
        assert "dependencies" in entry["labels"]
        assert entry["commit-message"]["prefix"] == "deps"
        assert entry["commit-message"]["include"] == "scope"
        assert entry["groups"]
        for group_name, group in entry["groups"].items():
            assert group["patterns"] == ["*"]
            if group_name == "github-actions-major":
                assert entry["package-ecosystem"] == "github-actions"
                assert group["update-types"] == ["major"]
            else:
                assert group["update-types"] == ["minor", "patch"]


def test_dependabot_leaves_torch_family_upgrades_to_the_runbook() -> None:
    """torch/torchvision minor+major bumps are ignored so the pair only moves together."""
    uv_entry = next(
        entry for entry in _dependabot_config()["updates"] if entry["package-ecosystem"] == "uv"
    )
    ignored = {rule["dependency-name"]: set(rule["update-types"]) for rule in uv_entry["ignore"]}
    blocked = {"version-update:semver-minor", "version-update:semver-major"}

    for package in ("torch", "torchvision"):
        assert ignored.get(package) == blocked
    runbook = ROOT / "docs/runbooks/torch-cve-upgrade.md"
    assert "uv lock --upgrade-package torch --upgrade-package torchvision" in runbook.read_text(
        encoding="utf-8"
    )
