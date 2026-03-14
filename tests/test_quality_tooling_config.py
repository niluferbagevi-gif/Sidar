# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

from pathlib import Path


def test_pyproject_has_ruff_and_mypy_configured():
    src = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.ruff]" in src
    assert "[tool.mypy]" in src
    assert "strict = true" in src


def test_environment_includes_ruff_dependency():
    src = Path("environment.yml").read_text(encoding="utf-8")
    assert "ruff~=" in src