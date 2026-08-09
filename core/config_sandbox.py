"""Docker code-execution sandbox settings for ``config.Config``."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.config_env_helpers import (
    get_bool_prefixed_env,
    get_int_env,
    get_int_prefixed_env,
    get_list_env,
    get_optional_prefixed_env,
    get_prefixed_env,
)


@dataclass(frozen=True)
class SandboxSettings:
    """Docker REPL sandbox resource and runtime settings."""

    sandbox_limits: dict[str, Any]
    code_execution_backend: str
    docker_autodetect: bool
    docker_python_image: str
    docker_image: str
    docker_test_image_raw: str | None
    docker_test_image_explicit: bool
    docker_test_image: str
    docker_runtime: str
    docker_allowed_runtimes: list[str]
    docker_microvm_mode: str
    docker_mem_limit: str
    docker_network_disabled: bool
    docker_nano_cpus: int
    docker_exec_timeout: int
    docker_required: bool
    prompt_guard_enabled: bool
    guardrails_required: bool
    python_virtual_env: str
    python_conda_prefix: str


def load_sandbox_settings(
    *,
    base_sandbox_limits: dict[str, Any],
    safe_choice: Callable[[str, str, set[str]], str],
    get_external_bool_prefixed_env: Callable[[str, str, bool], bool],
) -> SandboxSettings:
    """Load Docker sandbox settings from environment variables."""
    docker_python_image = get_prefixed_env(
        "SIDAR_DOCKER_PYTHON_IMAGE", "DOCKER_PYTHON_IMAGE", "python:3.11-slim"
    )
    docker_test_image_raw = get_optional_prefixed_env(
        "SIDAR_DOCKER_TEST_IMAGE", "DOCKER_TEST_IMAGE"
    )
    guardrails_default = os.getenv("SIDAR_ENV", "").strip().lower() == "production"
    return SandboxSettings(
        sandbox_limits=dict(base_sandbox_limits),
        code_execution_backend=safe_choice(
            get_prefixed_env("SIDAR_CODE_EXECUTION_BACKEND", "CODE_EXECUTION_BACKEND", "docker"),
            "docker",
            {"docker", "disabled"},
        ),
        docker_autodetect=get_external_bool_prefixed_env(
            "SIDAR_DOCKER_AUTODETECT", "DOCKER_AUTODETECT", True
        ),
        docker_python_image=docker_python_image,
        docker_image=get_prefixed_env("SIDAR_DOCKER_IMAGE", "DOCKER_IMAGE", ""),
        docker_test_image_raw=docker_test_image_raw,
        docker_test_image_explicit=bool((docker_test_image_raw or "").strip()),
        docker_test_image=(docker_test_image_raw or docker_python_image).strip(),
        docker_runtime=get_prefixed_env("SIDAR_DOCKER_RUNTIME", "DOCKER_RUNTIME", ""),
        docker_allowed_runtimes=get_list_env(
            "DOCKER_ALLOWED_RUNTIMES", ["", "runc", "runsc", "kata-runtime"]
        ),
        docker_microvm_mode=get_prefixed_env(
            "SIDAR_DOCKER_MICROVM_MODE", "DOCKER_MICROVM_MODE", "off"
        ),
        docker_mem_limit=get_prefixed_env("SIDAR_DOCKER_MEM_LIMIT", "DOCKER_MEM_LIMIT", "256m"),
        docker_network_disabled=get_bool_prefixed_env(
            "SIDAR_DOCKER_NETWORK_DISABLED", "DOCKER_NETWORK_DISABLED", True
        ),
        docker_nano_cpus=get_int_prefixed_env(
            "SIDAR_DOCKER_NANO_CPUS", "DOCKER_NANO_CPUS", 1_000_000_000
        ),
        docker_exec_timeout=get_int_env("DOCKER_EXEC_TIMEOUT", 10),
        docker_required=get_bool_prefixed_env("SIDAR_DOCKER_REQUIRED", "DOCKER_REQUIRED", True),
        prompt_guard_enabled=get_external_bool_prefixed_env(
            "SIDAR_PROMPT_GUARD_ENABLED", "PROMPT_GUARD_ENABLED", True
        ),
        guardrails_required=get_external_bool_prefixed_env(
            "SIDAR_GUARDRAILS_REQUIRED", "GUARDRAILS_REQUIRED", guardrails_default
        ),
        python_virtual_env=os.getenv("VIRTUAL_ENV", ""),
        python_conda_prefix=os.getenv("CONDA_PREFIX", ""),
    )
