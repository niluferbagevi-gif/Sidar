import configparser
import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
PYTHON_MAJOR_MINOR = "3.11"
PYTHON_PATCH_PIN = "3.11.15"
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
    assert (ROOT / ".python-version").read_text().strip() == PYTHON_PATCH_PIN

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


def test_ruff_enables_pydocstyle_incrementally():
    pyproject_text = (ROOT / "pyproject.toml").read_text()
    pyproject = tomllib.loads(pyproject_text)
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    lint_config = pyproject["tool"]["ruff"]["lint"]
    assert "D" in lint_config["select"]
    assert pyproject["tool"]["ruff"]["lint"]["pydocstyle"]["convention"] == "google"
    for transitional_ignore in (
        "D100",
        "D101",
        "D102",
        "D103",
        "D104",
        "D105",
        "D106",
        "D107",
    ):
        assert transitional_ignore in lint_config["ignore"]
    for enforced_rule in ("E501", "D200", "D417", "ASYNC240"):
        assert enforced_rule not in lint_config["ignore"]
    assert "AGENTS.md §2.5.6" in pyproject_text
    assert "Kademeli dokümantasyon kampanyası" in agents
    for milestone in ("2026-07-15", "2026-08-15", "2026-09-30"):
        assert milestone in agents


def test_setuptools_security_floor_is_enforced_in_build_and_lock():
    """Setuptools must stay pinned to >=83.0.0 without freezing it to one exact build.

    The floor exists to keep the known-vulnerable 81.x line out of the build
    and lock. It must not regress into an exact-version pin: that turns every
    routine `uv lock --upgrade` that legitimately bumps setuptools past
    83.0.0 into a false failure here, while still allowing the floor itself
    to be re-checked against the resolved lock version.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())

    build_requirement = Requirement(
        next(
            item for item in pyproject["build-system"]["requires"] if item.startswith("setuptools")
        )
    )
    override_requirement = Requirement(
        next(
            item
            for item in pyproject["tool"]["uv"]["override-dependencies"]
            if item.startswith("setuptools")
        )
    )
    lock_override = next(
        override for override in lock["manifest"]["overrides"] if override["name"] == "setuptools"
    )

    security_floor = Version("83.0.0")
    assert Version(str(build_requirement.specifier).removeprefix(">=")) == security_floor
    assert Version(str(override_requirement.specifier).removeprefix(">=")) == security_floor
    assert lock_override["specifier"] == str(build_requirement.specifier)

    locked_version = Version(
        next(package["version"] for package in lock["package"] if package["name"] == "setuptools")
    )

    # The lock must resolve to a version that actually satisfies the floor
    # (>=83.0.0), not one exact build of it — any newer, still-safe release
    # (84.0.0, 85.x, ...) is a valid resolution and must keep passing.
    assert locked_version in build_requirement.specifier
    assert locked_version in override_requirement.specifier
    assert locked_version >= security_floor
