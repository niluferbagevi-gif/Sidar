"""Project-level configuration validation tests.

Bu testler, uygulama kodu dışında kalan kritik altyapı dosyalarının
(yaml/workflow/compose/coverage konfigleri) bozulmasını erken yakalamak için çalışır.
"""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

YAML_LIKE_FILES = [
    "docker-compose.yml",
    "environment.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/migration-cutover-checks.yml",
    "helm/sidar/values.yaml",
]

EXPECTED_COVERAGE_SOURCES = {
    "agent",
    "core",
    "managers",
    "plugins",
    "main.py",
    "web_server.py",
    "cli.py",
    "config.py",
    "github_upload.py",
    "gui_launcher.py",
}


@pytest.mark.parametrize("relative_path", YAML_LIKE_FILES)
def test_yaml_like_files_exist_and_are_not_empty(relative_path: str) -> None:
    file_path = REPO_ROOT / relative_path
    assert file_path.exists(), f"Missing expected config file: {relative_path}"

    content = file_path.read_text(encoding="utf-8")
    assert content.strip(), f"Configuration file is empty: {relative_path}"


def test_docker_compose_contains_services_block() -> None:
    compose_text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "services:" in compose_text


def test_workflow_files_have_required_top_level_keys() -> None:
    for workflow_file in [
        ".github/workflows/ci.yml",
        ".github/workflows/migration-cutover-checks.yml",
    ]:
        workflow_text = (REPO_ROOT / workflow_file).read_text(encoding="utf-8")

        assert "name:" in workflow_text
        assert "jobs:" in workflow_text
        assert "on:" in workflow_text


def test_coveragerc_includes_root_python_entrypoints() -> None:
    coveragerc = ConfigParser()
    coveragerc.read(REPO_ROOT / ".coveragerc", encoding="utf-8")

    assert coveragerc.has_section("run")
    sources_raw = coveragerc.get("run", "source")
    sources = {line.strip() for line in sources_raw.splitlines() if line.strip()}

    missing = EXPECTED_COVERAGE_SOURCES - sources
    assert not missing, f"Missing coverage source entries: {sorted(missing)}"
