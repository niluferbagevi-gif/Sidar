"""Tests for ``agent.roles.coverage.config.read_coverage_config``."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.roles.coverage.config import read_coverage_config

PYPROJECT = """
[project]
name = "demo"

[tool.coverage.run]
branch = true
omit = ["tests/*", "migrations/*"]

[tool.coverage.report]
fail_under = 100
show_missing = true
precision = 2
"""


def test_missing_coveragerc_falls_back_to_sibling_pyproject(tmp_path: Path) -> None:
    """A missing default ``.coveragerc`` reads ``pyproject.toml [tool.coverage]``."""
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")

    config = read_coverage_config(tmp_path / ".coveragerc")

    assert config == {
        "path": str(tmp_path / "pyproject.toml"),
        "exists": True,
        "run": {"branch": "true", "omit": "tests/*\nmigrations/*"},
        "report": {"fail_under": "100", "show_missing": "true", "precision": "2"},
    }


def test_existing_coveragerc_wins_over_pyproject(tmp_path: Path) -> None:
    """An explicit INI file keeps precedence, like coverage.py's own lookup."""
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    rc = tmp_path / ".coveragerc"
    rc.write_text("[run]\ninclude = src/*\n[report]\nfail_under = 90\n", encoding="utf-8")

    config = read_coverage_config(rc)

    assert config["path"] == str(rc)
    assert config["run"] == {"include": "src/*"}
    assert config["report"] == {"fail_under": "90"}


def test_setup_cfg_style_sections_and_missing_sections(tmp_path: Path) -> None:
    """``[coverage:run]`` sections are read; absent sections become empty dicts."""
    cfg = tmp_path / "setup.cfg"
    cfg.write_text("[coverage:run]\nomit = a.py\n", encoding="utf-8")

    config = read_coverage_config(cfg)

    assert config["exists"] is True
    assert config["run"] == {"omit": "a.py"}
    assert config["report"] == {}


def test_explicit_toml_path_is_read_directly(tmp_path: Path) -> None:
    """A ``.toml`` path is parsed as pyproject; a non-table ``run`` is ignored."""
    toml = tmp_path / "cov.toml"
    toml.write_text('[tool.coverage]\nrun = "odd"\n[tool.coverage.report]\nskip_covered = false\n')

    config = read_coverage_config(toml)

    assert config == {
        "path": str(toml),
        "exists": True,
        "run": {},
        "report": {"skip_covered": "false"},
    }


@pytest.mark.parametrize(
    "pyproject_text",
    ['[project]\nname = "demo"\n', "not = [valid toml"],
    ids=["no-tool-coverage", "invalid-toml"],
)
def test_unusable_pyproject_reports_missing_config(tmp_path: Path, pyproject_text: str) -> None:
    """Without a usable ``[tool.coverage]`` table the default path is reported missing."""
    (tmp_path / "pyproject.toml").write_text(pyproject_text, encoding="utf-8")

    fallback = read_coverage_config(tmp_path / ".coveragerc")
    explicit = read_coverage_config(tmp_path / "pyproject.toml")

    assert fallback == {
        "path": str(tmp_path / ".coveragerc"),
        "exists": False,
        "run": {},
        "report": {},
    }
    assert explicit["exists"] is False


def test_missing_non_default_path_and_empty_argument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Other missing names never fall back; empty input means ``./.coveragerc``."""
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert read_coverage_config(tmp_path / "none.rc")["exists"] is False
    assert read_coverage_config("  ")["path"] == "pyproject.toml"
    assert read_coverage_config(None)["exists"] is True
