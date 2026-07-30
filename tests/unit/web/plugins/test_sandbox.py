from __future__ import annotations

import pytest
from fastapi import HTTPException

from agent.base_agent import BaseAgent
from web.plugins.sandbox import (
    assert_in_process_plugin_execution_allowed,
    execute_validated_plugin_source,
    in_process_plugin_execution_allowed,
    plugin_source_filename,
    restricted_plugin_import,
    validate_plugin_source,
)


def test_plugin_source_filename_sanitizes_label() -> None:
    assert plugin_source_filename("mod / name.py") == "<sidar-plugin:mod___name.py>"
    assert plugin_source_filename("!!!") == "<sidar-plugin:___>"
    assert plugin_source_filename("") == "<sidar-plugin:inline>"


def test_in_process_plugin_execution_env_matrix() -> None:
    for explicit in ("1", "true", "yes", "on"):
        assert in_process_plugin_execution_allowed({"SIDAR_ENABLE_IN_PROCESS_PLUGINS": explicit})
    for explicit in ("0", "false", "no", "off"):
        assert not in_process_plugin_execution_allowed(
            {"SIDAR_ENABLE_IN_PROCESS_PLUGINS": explicit, "SIDAR_ENV": "development"}
        )

    assert in_process_plugin_execution_allowed({"SIDAR_ENV": "development"})
    assert not in_process_plugin_execution_allowed({"SIDAR_ENV": "production"})
    for explicit in ("1", "true", "yes", "on"):
        assert not in_process_plugin_execution_allowed(
            {"SIDAR_ENABLE_IN_PROCESS_PLUGINS": explicit, "SIDAR_ENV": "production"}
        )


def test_assert_in_process_plugin_execution_allowed_rejects_disabled_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIDAR_ENABLE_IN_PROCESS_PLUGINS", "0")

    with pytest.raises(HTTPException) as exc:
        assert_in_process_plugin_execution_allowed()

    assert exc.value.status_code == 403
    assert "process-içi" in exc.value.detail

    monkeypatch.setenv("SIDAR_ENABLE_IN_PROCESS_PLUGINS", "1")
    assert_in_process_plugin_execution_allowed()


def test_validate_plugin_source_rejects_syntax_and_banned_imports() -> None:
    for source in ("def broken(:\n", "import os\n", "from subprocess import run\n"):
        with pytest.raises(HTTPException) as exc:
            validate_plugin_source(source)
        assert exc.value.status_code == 400


def test_validate_plugin_source_rejects_introspection_and_dynamic_code() -> None:
    for source in (
        "eval('1')",
        "safe.exec('payload')",
        "leak = (lambda: 1).__globals__",
        "importlib.resources.files('os')",
        "getattr(__builtins__, '__import__')('os')",
    ):
        with pytest.raises(HTTPException) as exc:
            validate_plugin_source(source)
        assert exc.value.status_code == 400


def test_validate_plugin_source_rejects_banned_subscript_and_call_attribute_roots() -> None:
    for source in ("os[0].system('id')", "factory().exec('payload')"):
        with pytest.raises(HTTPException) as exc:
            validate_plugin_source(source)
        assert exc.value.status_code == 400


def test_validate_plugin_source_allows_safe_imports_and_non_name_call_shapes() -> None:
    validate_plugin_source("import math\nfrom typing import Any\nvalue = math.sqrt(4)\n")
    validate_plugin_source("def make():\n    return lambda: 1\n\nvalue = make()()\n")
    validate_plugin_source("handler = (lambda: None)\nhandler.__call__()\n")
    validate_plugin_source("('literal').safe()\n")


def test_restricted_plugin_import_rejects_relative_import() -> None:
    with pytest.raises(ImportError, match="relative import engellendi"):
        restricted_plugin_import("sibling", fromlist=("thing",), level=1)


def test_restricted_plugin_import_rejects_out_of_scope_from_imports() -> None:
    with pytest.raises(ImportError, match="web_server import kapsamı engellendi"):
        restricted_plugin_import("web_server", fromlist=("run_plugin",))

    with pytest.raises(ImportError, match="fastapi import kapsamı engellendi"):
        restricted_plugin_import("fastapi", fromlist=("Depends",))

    with pytest.raises(ImportError, match="agent.base_agent import kapsamı engellendi"):
        restricted_plugin_import("agent.base_agent", fromlist=("OtherClass",))


def test_restricted_plugin_import_rejects_modules_outside_allowlist() -> None:
    with pytest.raises(ImportError, match="import allowlist dışında"):
        restricted_plugin_import("json")


def test_restricted_plugin_import_allows_scoped_and_allowlisted_modules() -> None:
    web_server_ns = restricted_plugin_import("web_server", fromlist=("BaseAgent",))
    assert web_server_ns.BaseAgent is BaseAgent

    fastapi_ns = restricted_plugin_import("fastapi", fromlist=("HTTPException",))
    assert fastapi_ns.HTTPException is HTTPException

    base_agent_module = restricted_plugin_import("agent.base_agent", fromlist=("BaseAgent",))
    assert base_agent_module.BaseAgent is BaseAgent

    assert restricted_plugin_import("math") is not None


def test_execute_validated_plugin_source_uses_sanitized_filename() -> None:
    namespace: dict[str, object] = {}

    execute_validated_plugin_source("RESULT = 42", "plugin/name", namespace)

    assert namespace["RESULT"] == 42
