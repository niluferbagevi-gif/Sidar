"""Contract tests for built-in role registry/import/capability consistency."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _installer_full_text() -> str:
    """Concatenate install_sidar.sh with every sourced install_modules/*.sh file.

    install_sidar.sh was split into scripts/install_modules/{phases,utils}/*.sh;
    terminology/default-value contracts that used to live inline now live in
    whichever module owns that concern, so contract tests must search the
    combined text rather than the entrypoint file alone.
    """
    root = _repo_root()
    parts = [(root / "install_sidar.sh").read_text(encoding="utf-8")]
    parts.extend(
        path.read_text(encoding="utf-8")
        for path in sorted((root / "scripts" / "install_modules").rglob("*.sh"))
    )
    return "\n".join(parts)


def _extract_builtin_import_modules() -> set[str]:
    init_path = _repo_root() / "agent" / "roles" / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 1:
            modules.add(f"agent.roles.{node.module}")
    return modules


def _extract_registry_builtin_modules() -> set[str]:
    registry_path = _repo_root() / "agent" / "registry.py"
    tree = ast.parse(registry_path.read_text(encoding="utf-8"))
    modules: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_import_builtin_roles":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    if inner.value.startswith("agent.roles."):
                        modules.add(inner.value)
    return modules


def _extract_capabilities_from_role_file(role_file: Path) -> set[str]:
    tree = ast.parse(role_file.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr != "register":
                    continue
                for keyword in decorator.keywords:
                    if keyword.arg != "capabilities":
                        continue
                    if isinstance(keyword.value, ast.List):
                        values = {
                            elt.value
                            for elt in keyword.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        }
                        if values:
                            return values
    raise AssertionError(
        f"No AgentCatalog.register(capabilities=...) decorator found in {role_file}"
    )


def _extract_is_builtin_from_role_file(role_file: Path) -> bool:
    tree = ast.parse(role_file.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr != "register":
                    continue
                for keyword in decorator.keywords:
                    if keyword.arg == "is_builtin" and isinstance(keyword.value, ast.Constant):
                        return keyword.value.value is True
    raise AssertionError(
        f"No explicit AgentCatalog.register(is_builtin=True) decorator found in {role_file}"
    )


def test_builtin_role_import_lists_are_consistent() -> None:
    from_init = _extract_builtin_import_modules()
    from_registry = _extract_registry_builtin_modules()

    assert from_init == from_registry


def test_builtin_role_capabilities_match_expected_contract() -> None:
    root = _repo_root()
    expected = {
        "coder_agent.py": {
            "code_generation",
            "file_io",
            "shell_execution",
            "code_review",
        },
        "researcher_agent.py": {"web_search", "rag_search", "summarization"},
        "reviewer_agent.py": {"code_review", "security_audit", "quality_check"},
        "qa_agent.py": {"test_generation", "ci_remediation"},
        "coverage_agent.py": {
            "coverage_analysis",
            "pytest_output_analysis",
            "autonomous_test_generation",
        },
        "poyraz_agent.py": {
            "marketing_strategy",
            "seo_analysis",
            "campaign_copy",
            "audience_ops",
        },
    }

    role_dir = root / "agent" / "roles"
    for file_name, expected_caps in expected.items():
        observed = _extract_capabilities_from_role_file(role_dir / file_name)
        assert observed == expected_caps


def test_builtin_role_decorators_explicitly_mark_is_builtin_true() -> None:
    root = _repo_root()
    role_dir = root / "agent" / "roles"

    for module_name in _extract_registry_builtin_modules():
        role_file = role_dir / f"{module_name.rsplit('.', maxsplit=1)[-1]}.py"
        assert _extract_is_builtin_from_role_file(role_file) is True


def _extract_role_class_docstrings(role_file: Path) -> dict[str, str]:
    tree = ast.parse(role_file.read_text(encoding="utf-8"))
    return {
        node.name: ast.get_docstring(node) or ""
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name.endswith("Agent")
    }


def test_builtin_role_classes_keep_documented_agent_contracts() -> None:
    role_dir = _repo_root() / "agent" / "roles"
    expected_classes = {
        "CoderAgent",
        "ResearcherAgent",
        "ReviewerAgent",
        "QAAgent",
        "CoverageAgent",
        "PoyrazAgent",
    }

    documented_classes: dict[str, str] = {}
    for role_file in role_dir.glob("*_agent.py"):
        documented_classes.update(_extract_role_class_docstrings(role_file))

    assert set(documented_classes) == expected_classes
    for class_name, docstring in documented_classes.items():
        assert (
            len(docstring.split()) >= 6
        ), f"{class_name} needs a meaningful role contract docstring"


def test_agents_documentation_covers_specialized_roles_and_interactions() -> None:
    docs = (_repo_root() / "AGENTS.md").read_text(encoding="utf-8")

    expected_fragments = [
        "`researcher` — `ResearcherAgent`",
        "`coverage` — `CoverageAgent`",
        "`poyraz` — `PoyrazAgent`",
        "web_search`, `fetch_url`, `search_docs` ve `docs_search`",
        "run_pytest`, `analyze_pytest_output`",
        "generate_missing_tests` ve",
        "publish_social`, `publish_instagram_post`, `publish_facebook_post`",
        "researcher -> poyraz -> reviewer",
        "coverage -> coder -> reviewer -> qa",
    ]

    for fragment in expected_fragments:
        assert fragment in docs


def test_agents_documentation_covers_self_healing_loop_contract() -> None:
    docs = (_repo_root() / "AGENTS.md").read_text(encoding="utf-8")

    expected_fragments = [
        "### 2.5 Otonom operasyonlar / Self-healing döngüsü",
        "`.heal <log_dosyası>`",
        "`scripts/auto_heal.py`, analiz logunu okuyarak",
        "`SidarAgent._attempt_autonomous_self_heal(...)`",
        "`validation_commands` girdisini sandbox içinde çalıştırır",
        "`_restore_self_heal_backups(...)`",
        "`awaiting_hitl`",
        "`CoverageAgent` ile `coverage.xml`",
        "`AUTONOMOUS_LOOP_MUTATION_ENABLED`",
        "`mutmut` tabanlı mutasyon testi",
        "`ReviewerAgent` semantik onayı",
    ]

    for fragment in expected_fragments:
        assert fragment in docs


def test_run_tests_mypy_self_heal_is_explicit_opt_in() -> None:
    script = (_repo_root() / "run_tests.sh").read_text(encoding="utf-8")

    assert 'AUTO_HEAL_ON_FAILURE="${AUTO_HEAL_ON_FAILURE:-0}"' in script
    assert 'AUTO_HEAL_MAX_ATTEMPTS="${AUTO_HEAL_MAX_ATTEMPTS:-2}"' in script
    assert 'AUTO_HEAL_BATCH_RETRIES="${AUTO_HEAL_BATCH_RETRIES:-0}"' in script
    assert (
        'uv run python -m scripts.auto_heal --log "${AUTO_HEAL_LOG_PATH}" --source mypy --batch-retries "${AUTO_HEAL_BATCH_RETRIES}"'
        in script
    )


def test_autonomous_loop_contains_complete_coverage_agent_gate() -> None:
    script = (_repo_root() / "autonomous_loop.sh").read_text(encoding="utf-8")

    assert "@@ -" not in script
    assert "async def _review_with_reviewer_agent" in script
    assert "eksik exception path'i" in script
    assert "tautolojik mock kontrolü" in script
    assert "(neden belirtilmedi)" in script
    assert 'print(f"[ReviewerAgent] weaknesses={weaknesses}")' in script
    assert "ReviewerAgent semantik onay vermedi" in script
    assert "run_autonomous_coverage_batch" in script
    assert "write_missing_tests" in script
    assert "AUTONOMOUS_LOOP_EXCLUDE_FILES" in script
    assert "exclude_files=exclude_files" in script
    assert "run_autonomous_quality_tests" in script
    assert (
        'RUN_STATIC_ANALYSIS="${AUTONOMOUS_TEST_STATIC_ANALYSIS}" AUTO_HEAL_ON_FAILURE=0' in script
    )
    assert "run_mutation_quality_gate" in script
    assert "AUTONOMOUS_LOOP_MUTATION_ENABLED" in script
    assert (
        'AUTONOMOUS_MUTATION_MAX_CHILDREN="${AUTONOMOUS_LOOP_MUTATION_MAX_CHILDREN:-8}"' in script
    )
    assert "uv run --with mutmut mutmut run" in script
    assert "Coverage hedefi sağlandı fakat mutasyon kalite kapısı başarısız oldu" in script
    assert "Mevcut coverage artefaktları bulundu" in script
    assert "raise SystemExit(asyncio.run(main()))" in script


def test_agents_documentation_covers_swarm_supervisor_event_coordination() -> None:
    docs = (_repo_root() / "AGENTS.md").read_text(encoding="utf-8")

    expected_fragments = [
        "### 2.6 Swarm, Supervisor ve event-driven koordinasyon",
        "`Supervisor`, tek görev için",
        "`SwarmOrchestrator`, çoklu görevi intent",
        "`ActiveAgentRegistry` runtime ajan örneklerini",
        "`AgentEventBus.publish(...)`",
        "`DelegationRequest` / `P2PMessage`",
        "`run_parallel(...)`",
        "`dispatch_distributed(...)`",
        "`AsyncDelegationBackend`",
        "`SIDAR_EVENT_BUS_BACKEND` `redis`",
        "`RedisBackend`, `RabbitMQBackend`, `KafkaBackend`",
        "`SIDAR_EVENT_BUS_DLQ_CHANNEL`",
    ]

    for fragment in expected_fragments:
        assert fragment in docs


def test_agents_documentation_covers_multimodal_voice_vision_contracts() -> None:
    docs = (_repo_root() / "AGENTS.md").read_text(encoding="utf-8")

    expected_fragments = [
        "### 2.7 Çoklu modalite (multimodal): görüş ve ses yetenekleri",
        "`ENABLE_VISION`",
        "`ENABLE_MULTIMODAL`",
        '`VisionPipeline.analyze(analysis_type="ux_review"',
        "`BrowserManager.analyze_visual_drift(...)`",
        "`MultimodalPipeline.analyze_media(...)`",
        "`WebRTCAudioIngress.decode_packet(...)`",
        "`VoicePipeline.should_commit_audio(...)`",
        "`WHISPER_MODEL`, varsayılan `base`",
        "`MultimodalPipeline.analyze_media_source(...)`",
        "`VoicePipeline.extract_ready_segments(...)`",
        "#### 2.7.7 Operasyonel kurallar (özet)",
    ]

    for fragment in expected_fragments:
        assert fragment in docs


def test_agents_documentation_codifies_sidar_uv_qwen_terminology() -> None:
    docs = (_repo_root() / "AGENTS.md").read_text(encoding="utf-8")

    expected_fragments = [
        "### 1.1 Geliştirme ortamı ve terminoloji standardı",
        "Güncel ürün adı **Sidar**",
        "qwen2.5-coder:7b",
        "Tüm Python bağımlılık ve komut yönetimi `uv` üzerinden",
        "uv sync --all-extras",
        "uv sync --extra dev",
    ]

    for fragment in expected_fragments:
        assert fragment in docs


def test_readme_uses_sidar_uv_qwen_terminology_standards() -> None:
    readme = (_repo_root() / "README.md").read_text(encoding="utf-8")

    assert "CODING_MODEL=qwen2.5-coder:7b" in readme
    assert "CODING_MODEL=qwen2.5-coder:3b" not in readme
    assert "uv sync --all-extras" in readme
    assert "uv run pytest" in readme
    assert "uv run python main.py" in readme
    # Ham `python -m pip install` referansı kalmamalıdır.
    assert "python -m pip install" not in readme


def test_install_script_defaults_match_terminology_standards() -> None:
    script = _installer_full_text()

    assert 'CODE_MOD="qwen2.5-coder:7b"' in script
    assert 'CODE_MOD="qwen2.5-coder:3b"' not in script
    assert "uv run pytest" in script
    assert "install_pyright_lsp_tool" in script
    assert "pyright-langserver" in script
    # Eski ürün adı kullanıcıya görünen mesajda geçmemelidir; legacy yakalama korunur.
    assert "*lotus*" in script
    assert "'lotus' referansı" not in script


def test_extract_capabilities_skips_non_matching_decorators(tmp_path: Path) -> None:
    role_file = tmp_path / "example_role.py"
    role_file.write_text(
        """
@not_a_call
@AgentCatalog.register()
@OtherCatalog.register(capabilities=["ignored"])
@AgentCatalog.register(tags=["ignored"])
@AgentCatalog.register(capabilities=("still", "ignored"))
@AgentCatalog.register(capabilities=["ok_capability"])
class ExampleRole:
    pass
""".strip(),
        encoding="utf-8",
    )

    assert _extract_capabilities_from_role_file(role_file) == {"ignored"}


def test_extract_capabilities_raises_when_missing_or_empty(tmp_path: Path) -> None:
    role_file = tmp_path / "empty_caps_role.py"
    role_file.write_text(
        """
class ExampleRole:
    @AgentCatalog.register(capabilities=[])
    class Inner:
        pass
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="No AgentCatalog.register"):
        _extract_capabilities_from_role_file(role_file)


def test_sidar_uv_qwen_development_contract() -> None:
    """Keep repo-facing setup guidance aligned with Sidar's local dev standard."""
    root = _repo_root()
    text_by_file = {
        rel_path: (root / rel_path).read_text(encoding="utf-8")
        for rel_path in [
            "AGENTS.md",
            "README.md",
            "agent/registry.py",
            "config.py",
            "config_llm.py",
            "gui_launcher.py",
        ]
    }
    # install_sidar.sh was split into scripts/install_modules/{phases,utils}/*.sh;
    # search the combined text so moved terminology contracts still get checked.
    text_by_file["install_sidar.sh"] = _installer_full_text()

    assert "Güncel ürün adı **Sidar**" in text_by_file["AGENTS.md"]
    assert "uv sync --all-extras" in text_by_file["AGENTS.md"]
    assert "CODING_MODEL=qwen2.5-coder:7b" in text_by_file["README.md"]
    assert 'CODING_MODEL: str = "qwen2.5-coder:7b"' in text_by_file["config_llm.py"]
    assert 'REVIEWER_TEST_COMMAND", "uv run pytest"' in text_by_file["config.py"]
    assert 'CODE_MOD="qwen2.5-coder:7b"' in text_by_file["install_sidar.sh"]
    assert "uv run pytest" in text_by_file["install_sidar.sh"]
    assert "uv tool install pyright" in text_by_file["README.md"]
    assert "uv run alembic upgrade head" in text_by_file["README.md"]

    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pyright>=1.1.409,<2.0.0" not in pyproject["project"]["dependencies"]
    assert "pyright>=1.1.409,<2.0.0" in pyproject["project"]["optional-dependencies"]["dev"]

    forbidden_terms = [
        "Lot" "us",
        "qwen2.5-coder:" "3b",
        "python -m " "pip install",
    ]
    for rel_path, text in text_by_file.items():
        for term in forbidden_terms:
            assert term not in text, f"{term!r} should not appear in {rel_path}"


@pytest.mark.parametrize(
    "source",
    [
        # "register" çağrısı attribute değilse atlanmalı.
        """
@register(capabilities=["x"])
class ExampleRole:
    pass
""",
        # capabilities dışındaki keyword'ler atlanmalı.
        """
@AgentCatalog.register(tags=["x"])
class ExampleRole:
    pass
""",
        # capabilities listesi boşsa değer dönmemeli.
        """
@AgentCatalog.register(capabilities=[])
class ExampleRole:
    pass
""",
    ],
)
def test_extract_capabilities_raises_for_non_contract_decorators(
    tmp_path: Path, source: str
) -> None:
    role_file = tmp_path / "non_contract_role.py"
    role_file.write_text(source.strip(), encoding="utf-8")

    with pytest.raises(AssertionError, match="No AgentCatalog.register"):
        _extract_capabilities_from_role_file(role_file)
