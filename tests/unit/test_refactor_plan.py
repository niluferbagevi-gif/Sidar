from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_large_production_file_refactor_plan_tracks_priority_targets() -> None:
    plan = Path("docs/REFACTOR_PLAN.md").read_text(encoding="utf-8")

    for target in (
        "web_server.py",
        "run_tests.sh",
        "install_sidar.sh",
        "config.py",
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
        "web/app_factory.py",
        "web/plugins/sandbox.py",
        "scripts/test_gates/benchmark.sh",
        "scripts/test_gates/summary.py",
        "scripts/install_modules/validation.sh",
        "scripts/install_modules/install_cli.sh",
        "scripts/install_modules/install_dispatcher.sh",
        "scripts/install_modules/utils/ux.sh",
        "web/bootstrap.py",
        "web/middleware/cors.py",
        "web/middleware/access_policy.py",
        "core/config_runtime_paths.py",
        "core/config_secret_hardening.py",
        "core/db/auth.py",
        "core/db/audit.py",
        "core/rag/embeddings.py",
        "managers/code/patcher.py",
        "managers/code/runner.py",
        "managers/code/docker_lifecycle.py",
        "managers/code/shell_sandbox.py",
        "agent/self_heal/executor.py",
        "agent/autonomy/service.py",
        "agent/federation/service.py",
        "agent/roles/coverage/analyzer.py",
        "core/llm/providers/ollama.py",
        "core/llm/openai.py",
        "core/llm/anthropic.py",
        "core/llm/gemini.py",
        "core/llm/ollama.py",
        "core/llm/litellm.py",
        "core/llm/router.py",
        "core/llm/streaming.py",
        "core/llm/cache.py",
        "core/llm/facade.py",
        "core/doctor/checks/gpu.py",
        "core/doctor/models.py",
        "core/doctor/reporting.py",
        "agent/roles/reviewer/judge.py",
        "core/ci_remediation/validation.py",
        "managers/browser/visual_drift.py",
        "agent/swarm/handoff.py",
    ):
        assert module in plan

    assert "Compatibility shim" in plan
    assert "Küçük PR" in plan
    assert "Test-first güvence" in plan
    assert "App factory boundary'si `web/app_factory.py` içine çıkarıldı" in plan
    assert "GitHub webhook router çıkarımı yapıldı" in plan
    assert "`/ws/chat` router factory" in plan
    assert "WebSocket token parser (`web/security.py`) çıkarımı yapıldı" in plan
    assert "AST-validated `exec()`" in plan
    assert "plugin AST/policy helperları `web/plugins/sandbox.py`" in plan
    assert "process-içi plugin exec varsayılan olarak fail-closed" in plan
    assert "Docker sandbox sözleşmesiyle uyumlu" in plan
    assert "frontend static mount ve SPA fallback bootstrap boundary'si `web/bootstrap.py`" in plan
    assert "middleware/frontend fallback bootstrap boundary" in plan
    assert "loopback CORS middleware bootstrap'ı `web/middleware/cors.py`" in plan
    assert "access policy middleware orchestration'ı `web/middleware/access_policy.py`" in plan
    assert "Güncel bakım hotspot snapshot" in plan
    assert "Quality gate orchestration büyüdü" in plan
    assert "ana script bootstrap facade" in plan


def test_install_sidar_cli_and_dispatch_boundaries_are_sourced() -> None:
    installer = Path("install_sidar.sh").read_text(encoding="utf-8")
    cli = Path("scripts/install_modules/install_cli.sh").read_text(encoding="utf-8")
    dispatcher = Path("scripts/install_modules/install_dispatcher.sh").read_text(encoding="utf-8")

    assert 'source "${INSTALL_MODULE_DIR}/install_cli.sh"' in installer
    assert 'sidar_parse_install_cli "$@"' in installer
    assert 'source "${INSTALL_MODULE_DIR}/install_dispatcher.sh"' in installer
    assert 'sidar_dispatch_install_phases "$@"' in installer
    assert "sidar_parse_install_cli()" in cli
    assert 'for arg in "$@"' in cli
    assert "sidar_dispatch_install_phases()" in dispatcher
    assert 'sidar_run_install_phase "01_context"' in dispatcher
    assert 'sidar_run_install_phase "07_finish"' in dispatcher
    assert 'for arg in "$@"' not in installer


def test_refactor_plan_tracks_only_meaningful_todo_debt() -> None:
    plan = Path("docs/REFACTOR_PLAN.md").read_text(encoding="utf-8")

    assert "Gerçek TODO envanteri" in plan
    assert "`core/rag/graph.py` içindeki `LLM_ENTITY_EXTRACTION_TODO`" in plan
    assert "2026-Q3 hedefiyle feature flag ve schema validation" in plan
    assert "todo_manager.py" in plan
    assert "açık ürün borcu değil" in plan


def test_claude_zero_debt_scope_distinguishes_audit_findings_from_refactor_debt() -> None:
    claude = Path("docs/CLAUDE.md").read_text(encoding="utf-8")
    plan = Path("docs/REFACTOR_PLAN.md").read_text(encoding="utf-8")

    assert "Açık kritik / yüksek / orta / düşük audit bulgusu yok" in claude
    assert "Zero-Debt kapsamı" in claude
    assert "otomatik audit/quality-gate taramalarında açık bulgu olmamasını" in claude
    assert "plugin sandbox gibi bilinçli mimari refactor/güvenlik borçları" in claude
    assert "plugin sandbox policy üretimde fail-closed" in plan


def test_phase_one_refactor_boundaries_are_importable() -> None:
    # Guard this boundary smoke test against stale fake modules left by
    # earlier tests in the same worker: importing submodules requires
    # ``core.db`` to be the real package, not a plain ModuleType stub.
    sys.modules.pop("core.db", None)

    import agent.autonomy.service as autonomy_service
    import agent.self_heal.executor as self_heal_executor
    import core.db.auth as db_auth
    import core.db.coverage as db_coverage
    import core.db.marketing as db_marketing
    import core.db.models as db_models
    import core.db.session as db_session
    import core.rag.facade as rag_facade
    import managers.code.runner as code_runner
    import scripts.test_gates.summary as test_gate_summary
    import web.middleware.access_policy as access_policy_middleware
    import web.plugins.sandbox as plugin_sandbox

    assert db_auth.UserRecord is db_models.UserRecord
    assert db_session.SessionRecord is db_models.SessionRecord
    assert db_marketing.MarketingCampaignRecord is db_models.MarketingCampaignRecord
    assert db_coverage.CoverageTaskRecord is db_models.CoverageTaskRecord
    assert callable(rag_facade.build_embedding_function)
    assert callable(self_heal_executor.execute_self_heal_plan)
    assert callable(autonomy_service.append_autonomy_history)
    assert callable(code_runner.run_shell_command)
    assert callable(test_gate_summary.build_summary)
    assert callable(access_policy_middleware.access_policy_middleware_impl)
    assert callable(plugin_sandbox.validate_plugin_source)


def test_p2_refactor_plan_tracks_llm_and_browser_adapter_boundaries() -> None:
    plan = Path("docs/REFACTOR_PLAN.md").read_text(encoding="utf-8")

    assert "P2 LLM provider adapter modülleri" in plan
    assert "core/llm/{openai,anthropic,gemini,ollama,litellm}.py" in plan
    assert "provider contract testleriyle korunuyor" in plan
    assert "core/llm/{router,streaming,cache,facade}.py" in plan
    assert "core/llm/openai.py" in plan
    assert "core/llm/anthropic.py" in plan
    assert "core/llm/gemini.py" in plan
    assert "core/llm/ollama.py" in plan
    assert "core/llm/litellm.py" in plan
    assert "managers/browser/playwright.py" in plan
    assert "managers/browser/selenium.py" in plan
    assert "P2 Playwright/Selenium adapter" in plan


def test_p2_llm_provider_boundaries_are_importable() -> None:
    for module_name in (
        "core.llm.openai",
        "core.llm.anthropic",
        "core.llm.gemini",
        "core.llm.ollama",
        "core.llm.litellm",
        "core.llm.router",
        "core.llm.streaming",
        "core.llm.cache",
        "core.llm.facade",
    ):
        assert importlib.import_module(module_name) is not None
