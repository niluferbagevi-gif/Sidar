from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _project_dependencies() -> list[str]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(data["project"]["dependencies"])


def test_nemoguardrails_stays_on_validated_minor() -> None:
    """NeMo Guardrails should stay on the validated 0.22 API surface."""
    deps = _project_dependencies()

    assert "nemoguardrails>=0.22.0,<0.23.0" in deps


def test_agent_swarm_and_core_llm_do_not_import_nemoguardrails_directly() -> None:
    """Guardrails API usage should remain isolated behind SecurityManager."""
    checked_paths = [
        REPO_ROOT / "agent" / "swarm.py",
        REPO_ROOT / "agent" / "sidar_agent.py",
        *(REPO_ROOT / "core" / "llm").glob("*.py"),
        REPO_ROOT / "core" / "llm_client.py",
    ]

    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in checked_paths
        if "nemoguardrails" in path.read_text(encoding="utf-8").lower()
    ]

    assert offenders == []
