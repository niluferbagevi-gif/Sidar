"""Tests for the canonical local/container/CI toolchain contract."""

from pathlib import Path

from scripts.ci import check_toolchain_contract as contract


def test_repository_toolchain_surfaces_match_canonical_file() -> None:
    pins = contract.read_toolchain()

    assert pins["PYTHON_VERSION"] == "3.11.15"
    assert pins["UV_VERSION"] == "0.12.0"
    assert pins["NODE_VERSION"] == "20"
    assert pins["PLAYWRIGHT_PYTHON_MIN"] == "1.62.0"
    assert pins["PLAYWRIGHT_PYTHON_MAX"] == "1.63"
    assert pins["PLAYWRIGHT_NODE_MIN"] == "1.60.0"
    assert pins["PLAYWRIGHT_NODE_MAX"] == "1.62.0"
    assert contract.contract_errors(contract.ROOT, pins) == []


def test_contract_reports_docker_pin_drift(tmp_path: Path) -> None:
    (tmp_path / ".python-version").write_text("3.11.15\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("ARG PYTHON_VERSION=3.11.14\n", encoding="utf-8")
    (tmp_path / "Dockerfile.production").write_text(
        "ARG PYTHON_VERSION=3.11.15\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        'dependencies = ["playwright>=1.62.0,<1.63"]\n', encoding="utf-8"
    )
    (tmp_path / "web_ui_react").mkdir()
    (tmp_path / "web_ui_react/package.json").write_text(
        '{"devDependencies":{"@playwright/test": ">=1.60.0 <1.62.0"}}\n',
        encoding="utf-8",
    )
    (tmp_path / ".github/workflows").mkdir(parents=True)

    errors = contract.contract_errors(tmp_path, contract.read_toolchain())

    assert "Dockerfile: Python pin drift" in errors
    assert "Dockerfile: uv image pin drift" in errors
