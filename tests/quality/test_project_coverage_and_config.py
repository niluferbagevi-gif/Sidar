"""Quality gates for coverage scope and infrastructure configuration files."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_coveragerc_sources() -> set[str]:
    parser = ConfigParser()
    parser.read(REPO_ROOT / ".coveragerc", encoding="utf-8")
    raw_sources = parser.get("run", "source", fallback="")
    return {
        line.strip()
        for line in raw_sources.splitlines()
        if line.strip()
    }


def _read_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_coveragerc_includes_entrypoint_modules() -> None:
    required_sources = {
        "agent",
        "core",
        "managers",
        "plugins",
        "main.py",
        "web_server.py",
        "cli.py",
        "config.py",
        "gui_launcher.py",
        "github_upload.py",
    }
    configured_sources = _read_coveragerc_sources()

    missing_sources = sorted(required_sources - configured_sources)
    assert not missing_sources, f"Missing coverage sources: {missing_sources}"


def test_workflow_includes_infra_validation_gates() -> None:
    workflow_text = _read_text(".github/workflows/ci.yml")

    expected_steps = {
        "Lint GitHub Actions workflows (actionlint)",
        "Lint YAML manifests (yamllint)",
        "Lint Shell scripts (ShellCheck)",
        "Lint Dockerfile (Hadolint)",
        "Validate Helm chart",
    }

    missing_steps = sorted(
        step_name for step_name in expected_steps if step_name not in workflow_text
    )
    assert not missing_steps, f"Missing CI infra validation steps: {missing_steps}"


def test_critical_yaml_files_exist_and_nonempty() -> None:
    yaml_files = [
        "docker-compose.yml",
        "environment.yml",
        ".github/workflows/ci.yml",
        "helm/sidar/values.yaml",
        "helm/sidar/values-staging.yaml",
        "helm/sidar/values-prod.yaml",
    ]

    for relative_path in yaml_files:
        file_path = REPO_ROOT / relative_path
        assert file_path.exists(), f"Missing YAML file: {relative_path}"
        assert file_path.stat().st_size > 0, f"YAML file is empty: {relative_path}"
