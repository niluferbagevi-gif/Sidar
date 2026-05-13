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


def test_resolve_version_prefers_installed_package_metadata(monkeypatch) -> None:
    monkeypatch.setattr(sidar_version, "package_version", lambda package_name: " 2.4.6 ")
    monkeypatch.setattr(sidar_version, "_read_pyproject_version", lambda: "0.0.0")

    assert sidar_version.resolve_version() == "2.4.6"


def test_resolve_version_falls_back_when_package_metadata_is_missing(monkeypatch) -> None:
    def raise_missing(_package_name: str) -> str:
        raise sidar_version.PackageNotFoundError

    monkeypatch.setattr(sidar_version, "package_version", raise_missing)
    monkeypatch.setattr(sidar_version, "_read_pyproject_version", lambda: "1.2.3")

    assert sidar_version.resolve_version() == "1.2.3"


def test_resolve_version_falls_back_when_metadata_is_blank(monkeypatch) -> None:
    monkeypatch.setattr(sidar_version, "package_version", lambda package_name: "   ")
    monkeypatch.setattr(sidar_version, "_read_pyproject_version", lambda: "3.2.1")

    assert sidar_version.resolve_version() == "3.2.1"


def test_read_pyproject_version_returns_fallback_for_missing_file(monkeypatch, tmp_path: Path) -> None:
    fake_module_file = tmp_path / "missing_package" / "sidar_version.py"
    monkeypatch.setattr(sidar_version, "__file__", str(fake_module_file))

    assert sidar_version._read_pyproject_version() == "0.0.0"


def test_read_pyproject_version_returns_fallback_for_invalid_toml(monkeypatch, tmp_path: Path) -> None:
    fake_module_file = tmp_path / "sidar_version.py"
    fake_module_file.write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project\n", encoding="utf-8")
    monkeypatch.setattr(sidar_version, "__file__", str(fake_module_file))

    assert sidar_version._read_pyproject_version() == "0.0.0"


def test_read_pyproject_version_returns_fallback_for_blank_project_version(monkeypatch, tmp_path: Path) -> None:
    fake_module_file = tmp_path / "sidar_version.py"
    fake_module_file.write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "   "\n', encoding="utf-8")
    monkeypatch.setattr(sidar_version, "__file__", str(fake_module_file))

    assert sidar_version._read_pyproject_version() == "0.0.0"
