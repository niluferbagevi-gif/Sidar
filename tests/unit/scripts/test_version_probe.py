from __future__ import annotations

from pathlib import Path

from scripts.version_probe import resolve_pyproject_version


def test_resolve_pyproject_version_reads_static_project_version(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "7.8.9"\n', encoding="utf-8")

    assert resolve_pyproject_version(pyproject) == "7.8.9"


def test_resolve_pyproject_version_reads_dynamic_file(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndynamic = ["version"]\n'
        '[tool.setuptools.dynamic]\nversion = {file = ["VERSION"]}\n',
        encoding="utf-8",
    )
    (tmp_path / "VERSION").write_text("\n 6.5.4 \n", encoding="utf-8")

    assert resolve_pyproject_version(pyproject) == "6.5.4"


def test_resolve_pyproject_version_reads_dynamic_literal_attr(tmp_path: Path) -> None:
    package_dir = tmp_path / "sidar_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text('__version__ = "4.3.2"\n', encoding="utf-8")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndynamic = ["version"]\n'
        '[tool.setuptools.dynamic]\nversion = {attr = "sidar_pkg.__version__"}\n',
        encoding="utf-8",
    )

    assert resolve_pyproject_version(pyproject) == "4.3.2"
