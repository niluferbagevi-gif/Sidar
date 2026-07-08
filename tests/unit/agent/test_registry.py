"""Unit tests for AgentCatalog registry behaviors."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.registry import (
    BUILTIN_ROLE_CONTRACTS,
    BUILTIN_ROLE_MODULES,
    AgentCatalog,
    AgentSpec,
    _clear_builtin_import_failures,
    _format_import_failure,
    _import_builtin_roles,
    _sync_builtin_contract_registry,
)


class _DummyAgent:
    ROLE_NAME = "tmp_dummy"

    def __init__(self, value: int = 0) -> None:
        self.value = value


def test_agent_catalog_programmatic_registration_lifecycle() -> None:
    role_name = "unit_temp_programmatic"

    class UnitTempProgrammaticAgent:
        def __init__(self, *, name: str):
            self.name = name

    AgentCatalog.unregister(role_name)
    AgentCatalog.register_type(
        role_name=role_name,
        agent_class=UnitTempProgrammaticAgent,
        capabilities=["unit_capability"],
        description="unit test role",
        version="0.0.1",
        is_builtin=False,
    )

    spec = AgentCatalog.get(role_name)
    assert spec is not None
    assert spec.role_name == role_name
    assert "unit_capability" in spec.capabilities

    created = AgentCatalog.create(role_name, name="sidar")
    assert isinstance(created, UnitTempProgrammaticAgent)
    assert created.name == "sidar"

    matches = AgentCatalog.find_by_capability("unit_capability")
    assert any(item.role_name == role_name for item in matches)

    assert AgentCatalog.unregister(role_name) is True
    assert AgentCatalog.get(role_name) is None


def test_agent_catalog_decorator_registration_exposes_metadata() -> None:
    role_name = "unit_temp_decorator"
    AgentCatalog.unregister(role_name)

    @AgentCatalog.register(
        capabilities=["decorator_capability"],
        description="decorator unit role",
        version="0.0.2",
        is_builtin=False,
    )
    class UnitTempDecoratorAgent:
        ROLE_NAME = role_name

        def __init__(self, *, value: int):
            self.value = value

    listed_roles = {spec.role_name for spec in AgentCatalog.list_all()}
    assert role_name in listed_roles

    created = AgentCatalog.create(role_name, value=7)
    assert isinstance(created, UnitTempDecoratorAgent)
    assert created.value == 7

    assert AgentCatalog.unregister(role_name) is True


def test_registration_apis_documented_is_builtin_defaults() -> None:
    decorator_role = "unit_temp_decorator_default"
    programmatic_role = "unit_temp_programmatic_default"
    AgentCatalog.unregister(decorator_role)
    AgentCatalog.unregister(programmatic_role)

    @AgentCatalog.register(capabilities=["decorator_default_capability"])
    class UnitTempDecoratorDefaultAgent:
        ROLE_NAME = decorator_role

    AgentCatalog.register_type(
        role_name=programmatic_role,
        agent_class=_DummyAgent,
        capabilities=["programmatic_default_capability"],
    )

    try:
        decorator_spec = AgentCatalog.get(decorator_role)
        programmatic_spec = AgentCatalog.get(programmatic_role)

        assert decorator_spec is not None
        assert decorator_spec.is_builtin is False
        assert programmatic_spec is not None
        assert programmatic_spec.is_builtin is True
    finally:
        AgentCatalog.unregister(decorator_role)
        AgentCatalog.unregister(programmatic_role)


def test_register_decorator_populates_catalog_and_capability_index() -> None:
    @AgentCatalog.register(
        capabilities=["unit_test_capability"],
        description="decorator registration test",
        version="1.0.0",
        is_builtin=False,
    )
    class _DecoratedAgent:  # noqa: N801 - local test class name
        ROLE_NAME = "tmp_decorated"

    spec = AgentCatalog.get("tmp_decorated")
    assert spec is not None
    assert spec.description == "decorator registration test"

    matches = AgentCatalog.find_by_capability("unit_test_capability")
    assert any(item.role_name == "tmp_decorated" for item in matches)

    assert AgentCatalog.unregister("tmp_decorated") is True


def test_register_type_create_and_unregister_roundtrip() -> None:
    AgentCatalog.register_type(
        role_name="tmp_dummy",
        agent_class=_DummyAgent,
        capabilities=["unit_test"],
        description="temporary role for test",
        version="1.0.0",
        is_builtin=False,
    )

    instance = AgentCatalog.create("tmp_dummy", value=42)
    assert isinstance(instance, _DummyAgent)
    assert instance.value == 42

    assert AgentCatalog.unregister("tmp_dummy") is True
    assert AgentCatalog.get("tmp_dummy") is None


def test_create_external_side_effect_plugin_requires_full_access() -> None:
    role_name = "aws_management"
    snapshot = dict(AgentCatalog._registry)

    class ExternalPluginAgent:
        def __init__(self, cfg=None):
            self.cfg = cfg

    AgentCatalog.unregister(role_name)
    try:
        AgentCatalog.register_type(
            role_name=role_name,
            agent_class=ExternalPluginAgent,
            capabilities=["aws_management"],
            is_builtin=False,
        )
        spec = AgentCatalog.get(role_name)
        assert spec is not None
        assert spec.side_effect_level == "external_read"

        sandbox_cfg = SimpleNamespace(
            ACCESS_LEVEL="sandbox", BASE_DIR=".", PROMPT_GUARD_ENABLED=False
        )
        with pytest.raises(PermissionError, match="side_effect_level='external_read'"):
            AgentCatalog.create(role_name, cfg=sandbox_cfg)

        full_cfg = SimpleNamespace(ACCESS_LEVEL="full", BASE_DIR=".", PROMPT_GUARD_ENABLED=False)
        created = AgentCatalog.create(role_name, cfg=full_cfg)
        assert isinstance(created, ExternalPluginAgent)
    finally:
        AgentCatalog._registry.clear()
        AgentCatalog._registry.update(snapshot)


def test_create_unknown_role_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        AgentCatalog.create("definitely_missing_role")


def test_create_uses_factory_when_agent_class_is_missing() -> None:
    def _factory(*, value: int) -> dict[str, int]:
        return {"value": value}

    AgentCatalog._registry["tmp_factory"] = AgentSpec(  # type: ignore[attr-defined]
        role_name="tmp_factory",
        agent_class=None,
        capabilities=["unit_test"],
        description="factory-backed spec",
        version="1.0.0",
        is_builtin=False,
    )
    AgentCatalog._registry["tmp_factory"]._agent_factory = _factory  # type: ignore[attr-defined]

    instance = AgentCatalog.create("tmp_factory", value=7)
    assert instance == {"value": 7}

    assert AgentCatalog.unregister("tmp_factory") is True


def test_create_raises_typeerror_when_no_class_or_factory() -> None:
    AgentCatalog._registry["tmp_broken"] = AgentSpec(  # type: ignore[attr-defined]
        role_name="tmp_broken",
        agent_class=None,
        capabilities=[],
        description="missing instantiation hooks",
        version="1.0.0",
        is_builtin=False,
    )

    with pytest.raises(TypeError):
        AgentCatalog.create("tmp_broken")

    assert AgentCatalog.unregister("tmp_broken") is True


def test_unregister_returns_false_for_unknown_role() -> None:
    assert AgentCatalog.unregister("definitely_unknown_role") is False


def test_builtin_role_contracts_cover_exports_imports_router_and_supervisor() -> None:
    import agent.roles as role_exports
    from agent.core.supervisor import SupervisorAgent
    from agent.swarm import TaskRouter

    router = TaskRouter()
    supervisor_prompts = {
        "code": "kod yaz",
        "research": "web kaynak araştır",
        "review": "pull request incele",
        "marketing": "seo kampanya planı",
        "coverage": "coverage pytest eksik test",
        "qa": "qa kalite kapısı ci hatası",
    }

    assert BUILTIN_ROLE_MODULES == tuple(
        contract.module_name for contract in BUILTIN_ROLE_CONTRACTS
    )

    for contract in BUILTIN_ROLE_CONTRACTS:
        assert contract.class_name in role_exports.__all__
        exported_cls = getattr(role_exports, contract.class_name)
        spec = AgentCatalog.get(contract.role_name)
        assert spec is not None, contract.role_name
        assert spec.is_builtin is True
        assert spec.agent_class is exported_cls
        assert set(contract.capabilities).issubset(set(spec.capabilities))

        for intent in contract.swarm_intents:
            routed = router.route(intent)
            assert routed is not None, intent
            assert routed.role_name == contract.role_name

        for intent in contract.supervisor_intents:
            assert SupervisorAgent._intent(supervisor_prompts[intent]) == intent


def test_builtin_registration_prefers_canonical_class_for_temp_module_import() -> None:
    import agent.roles as role_exports

    contract = next(item for item in BUILTIN_ROLE_CONTRACTS if item.role_name == "reviewer")
    original_spec = AgentCatalog.get(contract.role_name)
    assert original_spec is not None

    temp_module_name = "reviewer_agent_under_test"
    module_path = Path("agent/roles/reviewer_agent.py").resolve()
    spec = importlib.util.spec_from_file_location(temp_module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    try:
        sys.modules[temp_module_name] = module
        spec.loader.exec_module(module)

        temp_cls = module.ReviewerAgent
        exported_cls = getattr(role_exports, contract.class_name)
        registered_spec = AgentCatalog.get(contract.role_name)

        assert temp_cls is not exported_cls
        assert registered_spec is not None
        assert registered_spec.agent_class is exported_cls
        assert registered_spec.agent_class.__module__ == contract.module_name
    finally:
        sys.modules.pop(temp_module_name, None)
        AgentCatalog._registry[contract.role_name] = original_spec


def test_builtin_registration_keeps_temp_class_when_canonical_symbol_is_not_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = next(item for item in BUILTIN_ROLE_CONTRACTS if item.role_name == "reviewer")
    original_spec = AgentCatalog.get(contract.role_name)
    assert original_spec is not None

    class TempReviewerAgent:
        pass

    def _fake_import_module(module_name: str):
        assert module_name == contract.module_name
        return SimpleNamespace(**{contract.class_name: "not-a-class"})

    monkeypatch.setattr("importlib.import_module", _fake_import_module)
    role_exports = sys.modules.get("agent.roles")
    original_export = getattr(role_exports, contract.class_name, None) if role_exports else None
    if role_exports is not None:
        monkeypatch.setattr(role_exports, contract.class_name, "not-a-class")

    try:
        AgentCatalog.register_type(
            role_name=contract.role_name,
            agent_class=TempReviewerAgent,
            capabilities=list(contract.capabilities),
            is_builtin=True,
        )
        registered_spec = AgentCatalog.get(contract.role_name)
        assert registered_spec is not None
        assert registered_spec.agent_class is TempReviewerAgent
    finally:
        if role_exports is not None and original_export is not None:
            monkeypatch.setattr(role_exports, contract.class_name, original_export)
        AgentCatalog._registry[contract.role_name] = original_spec


def test_builtin_contract_sync_skips_non_class_symbols() -> None:
    contract = next(item for item in BUILTIN_ROLE_CONTRACTS if item.role_name == "reviewer")
    original_spec = AgentCatalog.get(contract.role_name)
    assert original_spec is not None

    try:
        _sync_builtin_contract_registry(
            {contract.module_name: SimpleNamespace(**{contract.class_name: "not-a-class"})}
        )
        synced_spec = AgentCatalog.get(contract.role_name)
        assert synced_spec is not None
        assert synced_spec.agent_class is original_spec.agent_class
    finally:
        AgentCatalog._registry[contract.role_name] = original_spec


def test_builtin_contract_sync_registers_when_role_exports_module_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = dict(AgentCatalog._registry)
    original_role_exports = sys.modules.get("agent.roles")
    module_cache = {
        contract.module_name: SimpleNamespace(
            **{
                contract.class_name: type(
                    f"Temp{contract.class_name}", (), {"__module__": contract.module_name}
                )
            }
        )
        for contract in BUILTIN_ROLE_CONTRACTS
    }

    try:
        monkeypatch.delitem(sys.modules, "agent.roles", raising=False)

        _sync_builtin_contract_registry(module_cache)

        for contract in BUILTIN_ROLE_CONTRACTS:
            synced_spec = AgentCatalog.get(contract.role_name)
            assert synced_spec is not None
            assert synced_spec.agent_class is getattr(
                module_cache[contract.module_name], contract.class_name
            )
            assert synced_spec.is_builtin is True
    finally:
        AgentCatalog._registry.clear()
        AgentCatalog._registry.update(snapshot)
        if original_role_exports is not None:
            sys.modules["agent.roles"] = original_role_exports

def test_agent_catalog_health_reports_non_builtin_builtin_role() -> None:
    snapshot = dict(AgentCatalog._registry)
    contract = next(item for item in BUILTIN_ROLE_CONTRACTS if item.role_name == "coder")

    try:
        AgentCatalog._registry[contract.role_name] = AgentSpec(
            role_name=contract.role_name,
            agent_class=_DummyAgent,
            capabilities=list(contract.capabilities),
            description="built-in contract registered as plugin by mistake",
            version="0.0.0",
            is_builtin=False,
        )

        health = AgentCatalog.health_summary()

        assert health["status"] == "degraded"
        assert health["degraded"] is True
        assert contract.role_name in health["non_builtin_builtin_roles"]
    finally:
        AgentCatalog._registry.clear()
        AgentCatalog._registry.update(snapshot)


def test_import_builtin_roles_warns_when_literal_import_list_drifts_from_contract(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import agent.registry as registry_module
    import agent.roles as role_exports

    snapshot = dict(AgentCatalog._registry)
    export_snapshot = {
        contract.class_name: getattr(role_exports, contract.class_name)
        for contract in BUILTIN_ROLE_CONTRACTS
    }
    original_contract_modules = registry_module.BUILTIN_ROLE_MODULES
    imported_modules: list[str] = []

    def _fake_import_module(module_name: str) -> SimpleNamespace:
        imported_modules.append(module_name)
        contract = next(item for item in BUILTIN_ROLE_CONTRACTS if item.module_name == module_name)
        fake_class = type(contract.class_name, (), {"__module__": contract.module_name})
        return SimpleNamespace(**{contract.class_name: fake_class})

    monkeypatch.setattr(
        registry_module,
        "BUILTIN_ROLE_MODULES",
        original_contract_modules + ("agent.roles.experimental_agent",),
    )
    monkeypatch.setattr("importlib.import_module", _fake_import_module)

    try:
        with caplog.at_level("WARNING", logger="agent.registry"):
            _import_builtin_roles()
    finally:
        _clear_builtin_import_failures()
        AgentCatalog._registry.clear()
        AgentCatalog._registry.update(snapshot)
        for class_name, original_export in export_snapshot.items():
            monkeypatch.setattr(role_exports, class_name, original_export)

    assert imported_modules == list(original_contract_modules)
    assert "Yerleşik ajan rol kontratı ile import listesi uyumsuz" in caplog.text
    assert "agent.roles.experimental_agent" in caplog.text


def test_builtin_role_contract_static_exports_match_import_bootstrap_literal() -> None:
    registry_tree = ast.parse(Path("agent/registry.py").read_text())
    roles_init_tree = ast.parse(Path("agent/roles/__init__.py").read_text())

    import_list_modules: tuple[str, ...] | None = None
    for node in ast.walk(registry_tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_import_builtin_roles":
            continue
        for stmt in ast.walk(node):
            if (
                isinstance(stmt, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "builtin_role_modules"
                    for target in stmt.targets
                )
                and isinstance(stmt.value, ast.Tuple)
            ):
                import_list_modules = tuple(
                    item.value for item in stmt.value.elts if isinstance(item, ast.Constant)
                )
                break

    exported_imports = {
        alias.name
        for node in roles_init_tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    all_exports: set[str] = set()
    for node in roles_init_tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
            )
            and isinstance(node.value, ast.List)
        ):
            all_exports = {item.value for item in node.value.elts if isinstance(item, ast.Constant)}
            break

    assert import_list_modules == BUILTIN_ROLE_MODULES
    assert exported_imports == {contract.class_name for contract in BUILTIN_ROLE_CONTRACTS}
    assert all_exports == exported_imports


def test_agent_catalog_health_reports_missing_role_and_import_failure() -> None:
    snapshot = dict(AgentCatalog._registry)
    AgentCatalog._registry.clear()
    try:
        AgentCatalog.register_type(
            role_name="coder",
            agent_class=_DummyAgent,
            capabilities=["code_generation"],
            is_builtin=True,
        )
        health = AgentCatalog.health_summary()

        assert health["status"] == "degraded"
        assert "researcher" in health["missing_builtin_roles"]
        assert health["capability_mismatches"]["coder"]["missing"]

        def _fake_import_module(module_name: str):
            raise ModuleNotFoundError("No module named 'dotenv'", name="dotenv")

        import importlib

        original_import = importlib.import_module
        importlib.import_module = _fake_import_module
        try:
            _import_builtin_roles()
        finally:
            importlib.import_module = original_import

        health = AgentCatalog.health_summary()
        assert health["status"] == "degraded"
        assert health["import_failures"]
        assert "dotenv" in next(iter(health["import_failures"].values()))
    finally:
        _clear_builtin_import_failures()
        AgentCatalog._registry.clear()
        AgentCatalog._registry.update(snapshot)


def test_import_builtin_roles_skips_failed_module_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    imported_modules: list[str] = []

    def _fake_import_module(module_name: str):
        imported_modules.append(module_name)
        if module_name.endswith("qa_agent"):
            raise RuntimeError("simulated import failure")
        return object()

    monkeypatch.setattr("importlib.import_module", _fake_import_module)

    try:
        _import_builtin_roles()
    finally:
        _clear_builtin_import_failures()

    assert imported_modules == [
        "agent.roles.coder_agent",
        "agent.roles.researcher_agent",
        "agent.roles.reviewer_agent",
        "agent.roles.poyraz_agent",
        "agent.roles.coverage_agent",
        "agent.roles.qa_agent",
    ]


def test_import_builtin_roles_warns_when_all_builtin_imports_fail(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    snapshot = dict(AgentCatalog._registry)
    AgentCatalog._registry.clear()

    def _fake_import_module(module_name: str):
        raise ModuleNotFoundError("No module named 'dotenv'", name="dotenv")

    monkeypatch.setattr("importlib.import_module", _fake_import_module)

    try:
        with caplog.at_level("WARNING", logger="agent.registry"):
            _import_builtin_roles()
    finally:
        _clear_builtin_import_failures()
        AgentCatalog._registry.clear()
        AgentCatalog._registry.update(snapshot)

    assert "Yerleşik ajan rolleri yüklenemedi" in caplog.text
    assert "uv sync --all-extras" in caplog.text
    assert "dotenv" in caplog.text


def test_format_import_failure_for_module_not_found_error_uses_module_name() -> None:
    formatted = _format_import_failure(
        ModuleNotFoundError("No module named 'nonexistent'", name="nonexistent")
    )
    assert formatted == "eksik Python modülü: nonexistent"


def test_format_import_failure_for_non_module_not_found_error_uses_repr() -> None:
    formatted = _format_import_failure(RuntimeError("simulated boot failure"))
    assert formatted == "RuntimeError: simulated boot failure"


def test_format_import_failure_includes_exception_type_for_value_error() -> None:
    formatted = _format_import_failure(ValueError("bozuk yapı"))
    assert formatted.startswith("ValueError: ")
    assert "bozuk yapı" in formatted


def test_import_builtin_roles_logs_non_module_not_found_failures(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    snapshot = dict(AgentCatalog._registry)
    AgentCatalog._registry.clear()

    def _fake_import_module(module_name: str):
        raise RuntimeError("kötü XML konfigürasyonu")

    monkeypatch.setattr("importlib.import_module", _fake_import_module)

    try:
        with caplog.at_level("WARNING", logger="agent.registry"):
            _import_builtin_roles()
        assert "RuntimeError: kötü XML konfigürasyonu" in caplog.text
    finally:
        _clear_builtin_import_failures()
        AgentCatalog._registry.clear()
        AgentCatalog._registry.update(snapshot)


# --- Built-in role contract regression tests -------------------------------
#
# The temporary-module import scenario sits on the dynamic-import / static
# type-checker boundary — the same boundary that produced the recent
# AgentCatalog mypy regression. The parametrised tests below assert that the
# canonical-class resolution and the registration APIs stay correct for
# *every* built-in role, not just one representative.


@pytest.mark.parametrize(
    "contract",
    BUILTIN_ROLE_CONTRACTS,
    ids=[contract.role_name for contract in BUILTIN_ROLE_CONTRACTS],
)
def test_builtin_role_canonical_identity_survives_temp_module_import(
    contract,
) -> None:
    """Loading a built-in role file under a temp module name must not detach
    the registered ``agent_class`` from the canonical ``agent.roles.*``
    export. Python creates a brand-new class object when the same source
    file is executed under a different module name; AgentCatalog must
    normalize back to the canonical class so router/supervisor/health
    checks keep agreeing on class identity.
    """

    import agent.roles as role_exports

    original_spec = AgentCatalog.get(contract.role_name)
    assert original_spec is not None, contract.role_name

    temp_module_name = f"{contract.role_name}_agent_under_test"
    module_path = Path(contract.module_name.replace(".", "/") + ".py").resolve()
    assert module_path.exists(), module_path

    spec = importlib.util.spec_from_file_location(temp_module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    try:
        sys.modules[temp_module_name] = module
        spec.loader.exec_module(module)

        temp_cls = getattr(module, contract.class_name)
        exported_cls = getattr(role_exports, contract.class_name)
        registered_spec = AgentCatalog.get(contract.role_name)

        # The temp class is a *distinct* class object — that's the whole
        # point of the scenario.
        assert temp_cls is not exported_cls

        # ...but the registry must still point at the canonical class, with
        # the canonical module path.
        assert registered_spec is not None
        assert registered_spec.agent_class is exported_cls
        assert registered_spec.agent_class is not None
        assert registered_spec.agent_class.__module__ == contract.module_name
        assert registered_spec.agent_class.__name__ == contract.class_name
        assert registered_spec.is_builtin is True
    finally:
        sys.modules.pop(temp_module_name, None)
        AgentCatalog._registry[contract.role_name] = original_spec


@pytest.mark.parametrize(
    "contract",
    BUILTIN_ROLE_CONTRACTS,
    ids=[contract.role_name for contract in BUILTIN_ROLE_CONTRACTS],
)
def test_builtin_contract_sync_normalizes_each_role_to_canonical_class(
    contract,
) -> None:
    """``_sync_builtin_contract_registry`` is the lower-level mechanism the
    bootstrap relies on. Each contract must round-trip cleanly through it,
    even when an unrelated module cache is provided, so a stub injected by
    one role's import path cannot poison another role's canonical
    resolution.
    """

    snapshot = dict(AgentCatalog._registry)
    original_spec = AgentCatalog.get(contract.role_name)
    assert original_spec is not None
    canonical_module = importlib.import_module(contract.module_name)
    canonical_cls = getattr(canonical_module, contract.class_name)
    assert isinstance(canonical_cls, type)

    try:
        # Seed the role with a deliberately non-canonical class so we can
        # observe the sync repointing it.
        class _DriftingPlaceholder:
            pass

        AgentCatalog._registry[contract.role_name] = AgentSpec(
            role_name=contract.role_name,
            agent_class=_DriftingPlaceholder,
            capabilities=list(contract.capabilities),
            is_builtin=True,
        )

        _sync_builtin_contract_registry({contract.module_name: canonical_module})

        synced_spec = AgentCatalog.get(contract.role_name)
        assert synced_spec is not None
        assert synced_spec.agent_class is canonical_cls
        assert synced_spec.is_builtin is True
        # Capability set from the contract must persist through the sync.
        assert set(contract.capabilities).issubset(set(synced_spec.capabilities or []))
    finally:
        AgentCatalog._registry.clear()
        AgentCatalog._registry.update(snapshot)


def test_register_type_annotations_pin_strict_typing_contract() -> None:
    """Strict typing regression guard.

    The recent AgentCatalog mypy bug landed at the dynamic-import / static
    type-checker boundary. If a future refactor relaxes a key annotation
    (e.g. drops ``agent_class: type`` to ``Any`` to silence a checker),
    the dynamic-import scenarios above become silently unsafe. Pin the
    annotations explicitly here so an accidental relaxation lights up.
    """
    import typing

    register_type_hints = typing.get_type_hints(AgentCatalog.register_type)
    assert register_type_hints["role_name"] is str
    assert register_type_hints["agent_class"] is type
    assert register_type_hints["is_builtin"] is bool
    assert register_type_hints["version"] is str
    assert register_type_hints["description"] is str
    # Optional list[str] for capabilities.
    capabilities_hint = register_type_hints["capabilities"]
    assert capabilities_hint == (list[str] | None)
    assert register_type_hints["return"] is type(None)

    register_hints = typing.get_type_hints(AgentCatalog.register)
    assert register_hints["is_builtin"] is bool
    assert register_hints["version"] is str
    assert register_hints["capabilities"] == (list[str] | None)
    # ``register`` is a decorator factory: return type must be the
    # ``type -> type`` callable family, never a bare ``Any``.
    register_return = register_hints["return"]
    register_return_str = str(register_return)
    assert "Callable" in register_return_str
    assert "type" in register_return_str

    get_hints = typing.get_type_hints(AgentCatalog.get)
    assert get_hints["role_name"] is str
    # AgentSpec | None — explicit Optional return is required so callers
    # have to handle the "unknown role" branch.
    assert get_hints["return"] == (AgentSpec | None)


def test_agent_spec_dataclass_field_types_remain_strict() -> None:
    """``AgentSpec.agent_class`` is the lone slot the dynamic-import scenario
    writes into; keeping it ``type[Any] | None`` (not ``Any``) is what lets
    mypy catch a misrouted resolver. Pin the rest of the dataclass too so
    the contract surface stays explicit.
    """
    import typing
    from typing import Any

    hints = typing.get_type_hints(AgentSpec)
    assert hints["role_name"] is str
    assert hints["agent_class"] == (type[Any] | None)
    assert hints["capabilities"] == list[str]
    assert hints["description"] is str
    assert hints["version"] is str
    assert hints["is_builtin"] is bool


def test_get_returns_none_for_unknown_role_with_typed_contract() -> None:
    """``AgentCatalog.get`` must return ``None`` for unknown roles, not raise.

    Paired with the type-hint regression above this nails the documented
    behavior: the caller is forced to handle the ``Optional`` branch.
    """
    assert AgentCatalog.get("definitely-not-a-registered-role") is None


def test_register_type_rejects_non_class_agent_class_via_create() -> None:
    """The annotation says ``agent_class: type``; Python doesn't enforce it
    at runtime, but the failure must surface clearly through ``create``
    rather than silently mis-route. This catches a regression where a
    fallback path lets a non-type slip through unnoticed.
    """
    role_name = "non_class_agent_class_test"
    AgentCatalog.unregister(role_name)
    try:
        # The annotation lies if you pass a non-type, but the runtime cost
        # has to land on the caller — exposing it via create is the
        # contract the dynamic-import boundary relies on.
        AgentCatalog._registry[role_name] = AgentSpec(
            role_name=role_name,
            agent_class=None,
            capabilities=["smoke"],
            is_builtin=False,
        )
        with pytest.raises(TypeError):
            AgentCatalog.create(role_name)
    finally:
        AgentCatalog.unregister(role_name)
