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
    assert not in_process_plugin_execution_allowed({"SIDAR_ENV": "development"})
    assert not in_process_plugin_execution_allowed({"SIDAR_ENV": "test"})
    assert not in_process_plugin_execution_allowed({"SIDAR_ENV": "production"})
    for explicit in ("1", "true", "yes", "on"):
        assert not in_process_plugin_execution_allowed(
            {"SIDAR_ENABLE_IN_PROCESS_PLUGINS": explicit, "SIDAR_ENV": "production"}
        )


def test_plugin_backend_defaults_all_environments_to_docker_and_rejects_unknown() -> None:
    assert plugin_sandbox_backend({"SIDAR_ENV": "production"}) == "docker"
    assert plugin_sandbox_backend({"SIDAR_ENV": "development"}) == "docker"
    assert plugin_sandbox_backend({"SIDAR_ENV": "test"}) == "docker"
    assert plugin_sandbox_backend({}) == "docker"
    assert plugin_sandbox_backend({"SIDAR_PLUGIN_SANDBOX_BACKEND": "docker"}) == "docker"
    assert (
        plugin_sandbox_backend(
            {
                "SIDAR_PLUGIN_SANDBOX_BACKEND": "in_process",
                "SIDAR_ENABLE_IN_PROCESS_PLUGINS": "1",
            }
        )
        == "in_process"
    )
    with pytest.raises(PluginSandboxError, match="açık.*opt-in"):
        plugin_sandbox_backend({"SIDAR_PLUGIN_SANDBOX_BACKEND": "in_process"})
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
        "--memory=512m",
        "--memory-swap=512m",
        "--cpus=0.5",
        "--pids-limit=128",
        "--sysctl=net.ipv4.ip_unprivileged_port_start=1024",
        "-e",
        "SIDAR_ENABLE_IN_PROCESS_PLUGINS=1",
        "SIDAR_ENV=development",
        "--entrypoint=python",
    ):
        assert expected in command
    assert command[-2:] == ["-m", "web.plugins.worker"]


def test_docker_backend_pins_the_unprivileged_port_sysctl(monkeypatch) -> None:
    """Regression test for the container-escape matrix's CI-only finding.

    ``--cap-drop=ALL``/``--user=65534:65534`` alone cannot block a privileged
    port bind if the host's (or CI runner's) ambient
    ``net.ipv4.ip_unprivileged_port_start`` is lowered -- that sysctl is
    namespaced per network namespace, but a *new* namespace inherits whatever
    value the host currently has, not a fixed 1024
    (tests/integration/web/test_plugin_sandbox_container_escape.py's
    ``privileged_port_bind`` check caught exactly this against a real
    container). An explicit ``--sysctl`` pin makes the boundary independent
    of host/runner drift.
    """
    monkeypatch.setattr("web.plugins.sandbox.shutil.which", lambda _name: "/usr/bin/docker")
    argv = DockerPluginSandboxBackend({})._isolation_argv()

    assert "--sysctl=net.ipv4.ip_unprivileged_port_start=1024" in argv


def test_docker_backend_grants_the_worker_its_own_in_process_execution_opt_in(
    monkeypatch,
) -> None:
    """Regression test: the worker could never actually execute any plugin.

    ``web/plugins/worker.py`` runs plugin source via
    ``run_plugin_source_in_process()`` -- the same helper gated by
    ``assert_in_process_plugin_execution_allowed()`` for the *host's* legacy
    in-process backend, which fails closed unless
    ``SIDAR_ENABLE_IN_PROCESS_PLUGINS=1`` is set in ``os.environ``. Docker
    containers don't inherit the host's environment unless explicitly passed
    with ``-e``, and nothing did -- so every real ``describe()``/``run_task()``
    call failed closed with a generic "rejected by security policy" before a
    single plugin ever actually ran inside the sandbox
    (tests/integration/web/test_plugin_sandbox_container_escape.py's
    marketplace-proxy smoke test caught this against a real container).
    Verified live: a real ``python -m web.plugins.worker`` subprocess returns
    ``{"ok": false, "error": "403: ..."}`` without these two ``-e`` flags and
    ``{"ok": true, ...}`` with them. The host process's own environment is
    untouched -- these are fixed values scoped to the container via ``-e``,
    not values forwarded from ``os.environ``.
    """
    monkeypatch.setattr("web.plugins.sandbox.shutil.which", lambda _name: "/usr/bin/docker")
    argv = DockerPluginSandboxBackend({})._isolation_argv()

    env_index = argv.index("-e")
    assert argv[env_index : env_index + 4] == [
        "-e",
        "SIDAR_ENABLE_IN_PROCESS_PLUGINS=1",
        "-e",
        "SIDAR_ENV=development",
    ]


def test_docker_backend_command_overrides_the_image_entrypoint(monkeypatch) -> None:
    """The image's own ENTRYPOINT is the Sidar launcher (`python main.py`).

    Without an explicit ``--entrypoint`` override, ``docker run <image> -m
    web.plugins.worker`` would append ``-m web.plugins.worker`` as *arguments
    to main.py* instead of replacing the command -- the RPC worker would
    never actually run. This pins the fix: ``--entrypoint=python`` must
    appear as a run flag *before* the image argument.
    """
    monkeypatch.setattr("web.plugins.sandbox.shutil.which", lambda _name: "/usr/bin/docker")
    command = DockerPluginSandboxBackend({})._command()

    image_index = command.index("sidar:latest")
    assert "--entrypoint=python" in command[:image_index]
    assert command[image_index:] == ["sidar:latest", "-m", "web.plugins.worker"]


def test_docker_backend_fails_closed_without_docker(monkeypatch) -> None:
    monkeypatch.setattr("web.plugins.sandbox.shutil.which", lambda _name: None)
    with pytest.raises(PluginSandboxError, match="fail-closed"):
        DockerPluginSandboxBackend({}).describe("VALUE = 1", None, "missing")


def test_docker_backend_container_command_reuses_isolation_flags_with_custom_entrypoint(
    monkeypatch,
) -> None:
    monkeypatch.setattr("web.plugins.sandbox.shutil.which", lambda _name: "/usr/bin/docker")
    backend = DockerPluginSandboxBackend({})

    command = backend.container_command("-c", "print('probe')")

    assert command[: len(backend._isolation_argv())] == backend._isolation_argv()
    assert command[-2:] == ["-c", "print('probe')"]


def test_docker_backend_container_command_requires_args(monkeypatch) -> None:
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
    monkeypatch.setenv("SIDAR_ENABLE_IN_PROCESS_PLUGINS", "1")
    namespace = run_plugin_source_in_process("RESULT = 42", "safe_plugin")
    assert namespace["RESULT"] == 42

    monkeypatch.setenv("SIDAR_ENV", "production")
    monkeypatch.setenv("SIDAR_ENABLE_IN_PROCESS_PLUGINS", "1")
    with pytest.raises(HTTPException) as exc:
        run_plugin_source_in_process("RESULT = 42", "blocked_plugin")
    assert exc.value.status_code == 403


def test_in_process_backend_maps_validator_failure_to_http_400(monkeypatch) -> None:
    monkeypatch.setenv("SIDAR_ENV", "development")
    monkeypatch.setenv("SIDAR_ENABLE_IN_PROCESS_PLUGINS", "1")

    def _reject(_source: str) -> None:
        raise ValueError("validator detail")

    with pytest.raises(HTTPException) as exc:
        run_plugin_source_in_process("VALUE = 1", "invalid_plugin", validator=_reject)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Plugin kaynağı doğrulanamadı: validator detail"


def test_in_process_backend_maps_runtime_failure_to_http_400(monkeypatch) -> None:
    monkeypatch.setenv("SIDAR_ENV", "development")
    monkeypatch.setenv("SIDAR_ENABLE_IN_PROCESS_PLUGINS", "1")

    with pytest.raises(HTTPException) as exc:
        run_plugin_source_in_process("raise ValueError('runtime detail')", "broken_plugin")

    assert exc.value.status_code == 400
    assert exc.value.detail == "Plugin kodu derlenemedi/çalıştırılamadı: runtime detail"


def test_in_process_backend_preserves_runtime_http_exception(monkeypatch) -> None:
    monkeypatch.setenv("SIDAR_ENV", "development")
    monkeypatch.setenv("SIDAR_ENABLE_IN_PROCESS_PLUGINS", "1")

    def _raise_http(*_args) -> None:
        raise HTTPException(status_code=409, detail="runtime policy")

    monkeypatch.setattr("web.plugins.sandbox.execute_validated_plugin_source", _raise_http)

    with pytest.raises(HTTPException) as exc:
        run_plugin_source_in_process("VALUE = 1", "policy_plugin")

    assert exc.value.status_code == 409
    assert exc.value.detail == "runtime policy"


def test_docker_backend_request_maps_timeout_to_sandbox_error(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)

    def _raise_timeout(command, **_kwargs):
        if command[1] == "create":
            return _FakeCompletedProcess(stdout="container-id")
        if command[1] == "rm":
            return _FakeCompletedProcess()
        raise subprocess.TimeoutExpired(cmd="docker", timeout=backend.timeout)

    monkeypatch.setattr("web.plugins.sandbox.subprocess.run", _raise_timeout)

    with pytest.raises(PluginSandboxError, match="zaman aşımına uğradı"):
        backend.request({"action": "describe"})


def test_docker_backend_request_rejects_create_timeout(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)

    def _raise_timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(cmd=command, timeout=kwargs["timeout"])

    monkeypatch.setattr("web.plugins.sandbox.subprocess.run", _raise_timeout)

    with pytest.raises(PluginSandboxError, match="container oluşturma zaman aşımına uğradı"):
        backend.request({"action": "describe"})


def test_docker_backend_request_rejects_failed_create(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)
    monkeypatch.setattr(
        "web.plugins.sandbox.subprocess.run",
        lambda *_args, **_kwargs: _FakeCompletedProcess(returncode=1),
    )

    with pytest.raises(PluginSandboxError, match="container'ı oluşturulamadı"):
        backend.request({"action": "describe"})


def test_docker_backend_request_rejects_empty_container_id(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)
    monkeypatch.setattr(
        "web.plugins.sandbox.subprocess.run",
        lambda *_args, **_kwargs: _FakeCompletedProcess(stdout="  \n"),
    )

    with pytest.raises(PluginSandboxError, match="container kimliği doğrulanamadı"):
        backend.request({"action": "describe"})


def test_docker_backend_keeps_rpc_and_cleanup_deadlines_separate(monkeypatch) -> None:
    backend = DockerPluginSandboxBackend(
        {
            "SIDAR_PLUGIN_SANDBOX_TIMEOUT": "11",
            "SIDAR_PLUGIN_SANDBOX_CLEANUP_TIMEOUT": "47",
        }
    )
    monkeypatch.setattr("web.plugins.sandbox.shutil.which", lambda _name: "/usr/bin/docker")
    observed_timeouts: dict[str, int] = {}
    response = json.dumps({"rpc_version": PLUGIN_RPC_VERSION, "ok": True})

    def _run(command, **kwargs):
        observed_timeouts[command[1]] = kwargs["timeout"]
        if command[1] == "create":
            return _FakeCompletedProcess(stdout="container-id")
        if command[1] == "start":
            return _FakeCompletedProcess(stdout=response)
        return _FakeCompletedProcess()

    monkeypatch.setattr("web.plugins.sandbox.subprocess.run", _run)

    assert backend.request({"action": "describe"})["ok"] is True
    assert observed_timeouts == {"create": 47, "start": 11, "rm": 47}


def test_docker_backend_reports_cleanup_timeout_separately_from_rpc_timeout(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)
    response = json.dumps({"rpc_version": PLUGIN_RPC_VERSION, "ok": True})

    def _run(command, **kwargs):
        if command[1] == "create":
            return _FakeCompletedProcess(stdout="container-id")
        if command[1] == "start":
            return _FakeCompletedProcess(stdout=response)
        raise subprocess.TimeoutExpired(cmd=command, timeout=kwargs["timeout"])

    monkeypatch.setattr("web.plugins.sandbox.subprocess.run", _run)

    with pytest.raises(PluginSandboxError, match="container'ı temizlenemedi") as exc:
        backend.request({"action": "describe"})
    assert "worker zaman aşımına" not in str(exc.value)


def test_docker_backend_request_rejects_nonzero_returncode(monkeypatch) -> None:
    backend = _docker_backend(monkeypatch)

    def _run(command, **_kwargs):
        if command[1] == "create":
            return _FakeCompletedProcess(stdout="container-id")
        if command[1] == "start":
            return _FakeCompletedProcess(returncode=1)
        return _FakeCompletedProcess()

    monkeypatch.setattr("web.plugins.sandbox.subprocess.run", _run)

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

    def _run(command, **_kwargs):
        if command[1] == "create":
            return _FakeCompletedProcess(returncode=0, stdout="container-id")
        if command[1] == "start":
            return _FakeCompletedProcess(returncode=0, stdout=next(responses))
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr("web.plugins.sandbox.subprocess.run", _run)

    proxy_cls = build_isolated_plugin_proxy("SOURCE", "EchoAgent", "echo")

    assert proxy_cls.__name__ == "EchoAgent"
    assert issubclass(proxy_cls, BaseAgent)
    assert proxy_cls.__doc__ == "Echo plugin."
    assert asyncio.run(proxy_cls().run_task("hi")) == "isolated:hi"
