from __future__ import annotations

import tomllib
from pathlib import Path

import core
import sidar_version
from agent.sidar_agent import SidarAgent
from config import Config


def test_runtime_versions_use_pyproject_single_source() -> None:
    with (Path(__file__).resolve().parents[3] / "pyproject.toml").open("rb") as file_obj:
        pyproject_version = tomllib.load(file_obj)["project"]["version"]

    assert sidar_version.PRODUCT_VERSION == pyproject_version
    assert Config.VERSION == pyproject_version
    assert SidarAgent.VERSION == pyproject_version
    assert core.__version__ == pyproject_version
