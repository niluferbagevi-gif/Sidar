from __future__ import annotations

import asyncio
import json
import subprocess

import pytest
from fastapi import HTTPException

from agent.base_agent import BaseAgent
from web.plugins.sandbox import (
    PLUGIN_RPC_MAX_RESPONSE_BYTES,
    PLUGIN_RPC_VERSION,
    DockerPluginSandboxBackend,
    PluginSandboxError,
    assert_in_process_plugin_execution_allowed,
    build_isolated_plugin_proxy,
    execute_validated_plugin_source,
    in_process_plugin_execution_allowed,
    plugin_sandbox_backend,
    plugin_source_filename,
    restricted_plugin_import,
    run_plugin_source_in_process,
    validate_plugin_source,
)


class _FakeCompletedProcess:
    """Minimal stand-in for subprocess.CompletedProcess used by request() tests."""

    def __init__(self, *, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _docker_backend(monkeypatch: pytest.MonkeyPatch) -> DockerPluginSandboxBackend:
    """Build a backend whose docker binary lookup always succeeds."""
    monkeypatch.setattr("web.plugins.sandbox.shutil.which", lambda _name: "/usr/bin/docker")
    return DockerPluginSandboxBackend({})


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


def test_plugin_backend_defaults_production_to_docker_and_rejects_unknown() -> None:
    assert plugin_sandbox_backend({"SIDAR_ENV": "production"}) == "docker"
    assert plugin_sandbox_backend({"SIDAR_ENV": "development"}) == "in_process"
    assert plugin_sandbox_backend({"SIDAR_PLUGIN_SANDBOX_BACKEND": "docker"}) == "docker"
    with pytest.raises(PluginSandboxError, match="Desteklenmeyen"):
        plugin_sandbox_backend({"SIDAR_PLUGIN_SANDBOX_BACKEND": "subprocess"})


def test_docker_backend_command_applies_isolation_contract(monkeypatch) -> None:
    monkeypatch.setattr("web.plugins.sandbox.shutil.which", lambda _name: "/usr/bin/docker")
    command = DockerPluginSandboxBackend({})._command()

    for expected in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user=65534:65534",
        "--memory=256m",
        "--memory-swap=256m",
        "--cpus=0.5",
        "--pids-limit=64",
    ):
        assert expected in command
    assert command[-3:] == ["python", "-m", "web.plugins.worker"]


def test_docker_backend_fails_closed_without_docker(monkeypatch) -> None:
    monkeypatch.setattr("web.plugins.sandbox.shutil.which", lambda _name: None)
    with pytest.raises(PluginSandboxError, match="fail-closed"):
        DockerPluginSandboxBackend({}).describe("VALUE = 1", None, "missing")


def test_docker_backend_container_command_reuses_isolation_flags_with_custom_entrypoint(
    monkeypatch,
) -> None:
    monkeypatch.setattr("web.plugins.sandbox.shutil.which", lambda _name: "/usr/bin/docker")
    backend = DockerPluginSandboxBackend({})

    command = backend.container_command("python", "-c", "print('probe')")

    assert command[: len(backend._isolation_argv())] == backend._isolation_argv()
    assert command[-3:] == ["python", "-c", "print('probe')"]


def test_docker_backend_container_command_requires_entrypoint(monkeypatch) -> None:
    monkeypatch.setattr("web.plugins.sandbox.shutil.which", lambda _name: "/usr/bin/docker")
    backend = DockerPluginSandboxBackend({})

    with pytest.raises(ValueError, match="boş olamaz"):
        backend.container_command()


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


def test_in_process_backend_executes_only_outside_production(monkeypatch) -> None:
    monkeypatch.setenv("SIDAR_ENV", "development")
    namespace = run_plugin_source_in_process("RESULT = 42", "safe_plugin")
    assert namespace["RESULT"] == 42

    monkeypatch.setenv("SIDAR_ENV", "production")
    monkeypatch.setenv("SIDAR_ENABLE_IN_PROCESS_PLUGINS", "1")
    with pytest.raises(HTTPException) as exc:
        run_plugin_source_in_process("RESULT = 42", "blocked_plugin")
    assert exc.value.status_code == 403


def test_docker_backend_request_maps_timeout_to_sandbox_error(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)

    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=1)

    monkeypatch.setattr("web.plugins.sandbox.subprocess.run", _raise_timeout)

    with pytest.raises(PluginSandboxError, match="zaman aşımına uğradı"):
        backend.request({"action": "describe"})


def test_docker_backend_request_rejects_nonzero_returncode(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)
    monkeypatch.setattr(
        "web.plugins.sandbox.subprocess.run",
        lambda *_a, **_k: _FakeCompletedProcess(returncode=1, stdout=""),
    )

    with pytest.raises(PluginSandboxError, match="güvenli biçimde tamamlanamadı"):
        backend.request({"action": "describe"})


def test_docker_backend_request_rejects_oversized_response(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)
    oversized = "a" * (PLUGIN_RPC_MAX_RESPONSE_BYTES + 1)
    monkeypatch.setattr(
        "web.plugins.sandbox.subprocess.run",
        lambda *_a, **_k: _FakeCompletedProcess(returncode=0, stdout=oversized),
    )

    with pytest.raises(PluginSandboxError, match="yanıt limiti aşıldı"):
        backend.request({"action": "describe"})


def test_docker_backend_request_rejects_invalid_json(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)
    monkeypatch.setattr(
        "web.plugins.sandbox.subprocess.run",
        lambda *_a, **_k: _FakeCompletedProcess(returncode=0, stdout="not-json"),
    )

    with pytest.raises(PluginSandboxError, match="geçersiz RPC yanıtı"):
        backend.request({"action": "describe"})


def test_docker_backend_request_rejects_rpc_version_mismatch(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)
    monkeypatch.setattr(
        "web.plugins.sandbox.subprocess.run",
        lambda *_a, **_k: _FakeCompletedProcess(
            returncode=0, stdout=json.dumps({"rpc_version": "0"})
        ),
    )

    with pytest.raises(PluginSandboxError, match="RPC sürümü doğrulanamadı"):
        backend.request({"action": "describe"})


def test_docker_backend_request_rejects_worker_reported_failure(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)
    payload = json.dumps({"rpc_version": PLUGIN_RPC_VERSION, "ok": False, "error": "leak"})
    monkeypatch.setattr(
        "web.plugins.sandbox.subprocess.run",
        lambda *_a, **_k: _FakeCompletedProcess(returncode=0, stdout=payload),
    )

    with pytest.raises(PluginSandboxError, match="güvenlik politikasıyla reddedildi"):
        backend.request({"action": "describe"})


async def test_docker_backend_run_task_returns_worker_result_off_the_event_loop(
    monkeypatch,
) -> None:
    backend = _docker_backend(monkeypatch)
    payload = json.dumps({"rpc_version": PLUGIN_RPC_VERSION, "ok": True, "result": "42"})
    monkeypatch.setattr(
        "web.plugins.sandbox.subprocess.run",
        lambda *_a, **_k: _FakeCompletedProcess(returncode=0, stdout=payload),
    )

    result = await backend.run_task("SOURCE", "EchoAgent", "echo", "prompt")

    assert result == "42"


def test_build_isolated_plugin_proxy_requires_resolved_class_name(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)
    payload = json.dumps({"rpc_version": PLUGIN_RPC_VERSION, "ok": True, "class_name": ""})
    monkeypatch.setattr(
        "web.plugins.sandbox.subprocess.run",
        lambda *_a, **_k: _FakeCompletedProcess(returncode=0, stdout=payload),
    )
    monkeypatch.setattr("web.plugins.sandbox.DockerPluginSandboxBackend", lambda: backend)

    with pytest.raises(PluginSandboxError, match="sınıf metadata"):
        build_isolated_plugin_proxy("SOURCE", None, "echo")


def test_build_isolated_plugin_proxy_creates_baseagent_subclass_that_delegates(
    monkeypatch,
) -> None:
    backend = _docker_backend(monkeypatch)
    monkeypatch.setattr("web.plugins.sandbox.DockerPluginSandboxBackend", lambda: backend)

    responses = iter(
        [
            json.dumps(
                {
                    "rpc_version": PLUGIN_RPC_VERSION,
                    "ok": True,
                    "class_name": "EchoAgent",
                    "description": "Echo plugin.",
                }
            ),
            json.dumps({"rpc_version": PLUGIN_RPC_VERSION, "ok": True, "result": "isolated:hi"}),
        ]
    )
    monkeypatch.setattr(
        "web.plugins.sandbox.subprocess.run",
        lambda *_a, **_k: _FakeCompletedProcess(returncode=0, stdout=next(responses)),
    )

    proxy_cls = build_isolated_plugin_proxy("SOURCE", "EchoAgent", "echo")

    assert proxy_cls.__name__ == "EchoAgent"
    assert issubclass(proxy_cls, BaseAgent)
    assert proxy_cls.__doc__ == "Echo plugin."
    assert asyncio.run(proxy_cls().run_task("hi")) == "isolated:hi"
