from __future__ import annotations

import sys
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
        "core/llm_client.py",
        "core/doctor.py",
        "agent/roles/reviewer_agent.py",
        "core/ci_remediation.py",
        "managers/browser_manager.py",
        "agent/swarm.py",
    ):
        assert target in plan

    for module in (
        "web/routes/ws_chat.py",
        "web/routes/webhooks.py",
        "core/db/auth.py",
        "core/rag/embeddings.py",
        "managers/code/patcher.py",
        "agent/self_heal/executor.py",
        "agent/roles/coverage/analyzer.py",
        "core/llm/providers/ollama.py",
        "core/llm/openai.py",
        "core/llm/anthropic.py",
        "core/llm/gemini.py",
        "core/llm/ollama.py",
        "core/llm/litellm.py",
        "core/doctor/checks/gpu.py",
        "agent/roles/reviewer/judge.py",
        "core/ci_remediation/validation.py",
        "managers/browser/visual_drift.py",
        "agent/swarm/handoff.py",
    ):
        assert module in plan

    assert "Compatibility shim" in plan
    assert "Küçük PR" in plan
    assert "Test-first güvence" in plan
    assert "GitHub webhook router çıkarımı yapıldı" in plan
    assert "`/ws/chat` router factory" in plan
    assert "WebSocket token parser (`web/security.py`) çıkarımı yapıldı" in plan
    assert "middleware/frontend fallback bootstrap boundary" in plan


def test_phase_one_refactor_boundaries_are_importable() -> None:
    # Guard this boundary smoke test against stale fake modules left by
    # earlier tests in the same worker: importing submodules requires
    # ``core.db`` to be the real package, not a plain ModuleType stub.
    sys.modules.pop("core.db", None)

    import agent.self_heal.executor as self_heal_executor
    import core.db.auth as db_auth
    import core.db.coverage as db_coverage
    import core.db.marketing as db_marketing
    import core.db.models as db_models
    import core.db.session as db_session
    import core.rag.facade as rag_facade

    assert db_auth.UserRecord is db_models.UserRecord
    assert db_session.SessionRecord is db_models.SessionRecord
    assert db_marketing.MarketingCampaignRecord is db_models.MarketingCampaignRecord
    assert db_coverage.CoverageTaskRecord is db_models.CoverageTaskRecord
    assert callable(rag_facade.build_embedding_function)
    assert callable(self_heal_executor.execute_self_heal_plan)


def test_p2_refactor_plan_tracks_llm_and_browser_adapter_boundaries() -> None:
    plan = Path("docs/REFACTOR_PLAN.md").read_text(encoding="utf-8")

    assert "core/llm/{openai,anthropic,gemini,ollama,litellm}.py" in plan
    assert "core/llm/openai.py" in plan
    assert "core/llm/anthropic.py" in plan
    assert "core/llm/gemini.py" in plan
    assert "core/llm/ollama.py" in plan
    assert "core/llm/litellm.py" in plan
    assert "managers/browser/playwright.py" in plan
    assert "managers/browser/selenium.py" in plan
    assert "P2 Playwright/Selenium adapter" in plan
