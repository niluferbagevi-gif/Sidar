from __future__ import annotations

from pathlib import Path


def test_large_production_file_refactor_plan_tracks_priority_targets() -> None:
    plan = Path("docs/REFACTOR_PLAN.md").read_text(encoding="utf-8")

    for target in (
        "web_server.py",
        "core/db.py",
        "core/rag/__init__.py",
        "managers/code_manager.py",
        "agent/sidar_agent.py",
        "agent/roles/coverage_agent.py",
    ):
        assert target in plan

    for module in (
        "web/routes/ws_chat.py",
        "core/db/auth.py",
        "core/rag/embeddings.py",
        "managers/code/patcher.py",
        "agent/self_heal/executor.py",
        "agent/roles/coverage/analyzer.py",
    ):
        assert module in plan

    assert "Compatibility shim" in plan
    assert "Küçük PR" in plan
    assert "Test-first güvence" in plan
