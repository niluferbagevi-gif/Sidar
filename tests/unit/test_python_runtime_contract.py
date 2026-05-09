import configparser
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON_MAJOR_MINOR = "3.11"
PYTHON_PROJECT_RANGE = ">=3.11,<3.12"


def test_project_packaging_targets_python_311_only():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    project = pyproject["project"]
    assert project["requires-python"] == PYTHON_PROJECT_RANGE
    assert "Programming Language :: Python :: 3.11" in project["classifiers"]
    assert "Programming Language :: Python :: 3.12" not in project["classifiers"]

    assert pyproject["tool"]["ruff"]["target-version"] == "py311"
    assert pyproject["tool"]["mypy"]["python_version"] == PYTHON_MAJOR_MINOR


def test_project_python_pin_and_lock_are_python_311_only():
    assert (ROOT / ".python-version").read_text().strip() == PYTHON_MAJOR_MINOR

    lock_text = (ROOT / "uv.lock").read_text()
    assert 'requires-python = "==3.11.*"' in lock_text
    assert "cp312" not in lock_text


def test_legacy_setup_cfg_has_no_conflicting_python_requires():
    setup_cfg = ROOT / "setup.cfg"
    parser = configparser.ConfigParser()
    parser.read(setup_cfg)

    # setup.cfg is used for tool configuration in this project. If legacy
    # packaging metadata is added later, keep it aligned with pyproject.toml.
    if parser.has_option("options", "python_requires"):
        assert parser.get("options", "python_requires") == PYTHON_PROJECT_RANGE

    raw_text = setup_cfg.read_text()
    assert not re.search(r"python_requires\s*=\s*[^\n]*3\.12", raw_text)
