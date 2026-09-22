"""GPU-related Doctor checks."""

from __future__ import annotations

import contextlib
import os
import shutil
from typing import Any

import core.doctor as _doctor
from core.doctor import DoctorCheck


def check_gpu_memory_config() -> DoctorCheck:
    """Report effective local model and VRAM budget settings."""
    from config import Config
    from core.config_gpu_detect import normalize_gpu_memory_fractions

    # Config.GPU_INFO/GPU_COUNT/etc. are lazy-loaded on first Config() instantiation
    # (see Config._ensure_hardware_info_loaded). Reading the class attribute below
    # before anything else in this process has constructed a Config() leaves
    # GPU_INFO frozen at its "Devre Dışı / CPU Modu" placeholder even when USE_GPU
    # is true, producing a self-contradictory report. Force the hardware probe so
    # both fields agree; suppress errors so a broken .env doesn't turn this
    # diagnostic check itself into a crash.
    with contextlib.suppress(Exception):
        Config._ensure_hardware_info_loaded()

    provider = str(getattr(Config, "AI_PROVIDER", "ollama") or "ollama").strip().lower()
    coding_model = str(getattr(Config, "CODING_MODEL", "") or "").strip()
    access_level = str(getattr(Config, "ACCESS_LEVEL", "") or "").strip().lower()
    use_gpu = bool(getattr(Config, "USE_GPU", False))
    gpu_info = str(getattr(Config, "GPU_INFO", "") or "").strip()
    docker_image = str(getattr(Config, "DOCKER_IMAGE", "") or "").strip()
    llm_fraction = float(getattr(Config, "LLM_GPU_MEMORY_FRACTION", 0.0) or 0.0)
    rag_fraction = float(getattr(Config, "RAG_GPU_MEMORY_FRACTION", 0.0) or 0.0)
    legacy_fraction = float(getattr(Config, "GPU_MEMORY_FRACTION", 0.0) or 0.0)
    budget = normalize_gpu_memory_fractions(llm_fraction, rag_fraction)
    total = llm_fraction + rag_fraction
    details: dict[str, Any] = {
        "ai_provider": provider,
        "coding_model": coding_model,
        "access_level": access_level,
        "use_gpu": use_gpu,
        "gpu_info": gpu_info,
        "docker_image": docker_image,
        "gpu_memory_fraction": legacy_fraction,
        "llm_gpu_memory_fraction": llm_fraction,
        "rag_gpu_memory_fraction": rag_fraction,
        "total_gpu_memory_fraction": round(total, 4),
        "effective_gpu_memory_fraction": budget["gpu"],
        "effective_llm_gpu_memory_fraction": budget["llm"],
        "effective_rag_gpu_memory_fraction": budget["rag"],
        "normalized": budget["normalized"],
        "recommended_commands": [
            "uv run python -m scripts.bootstrap_env --profile development",
            "uv run python -m core.doctor artifacts/install/doctor.json",
        ],
    }

    warnings: list[str] = []
    if budget["normalized"]:
        warnings.append(
            "LLM/RAG VRAM fractions exceed the safe 80% target or are non-positive; Sidar will "
            "normalize the effective GPU budget to 80%"
        )
    if provider == "ollama" and coding_model != "qwen2.5-coder:7b":
        warnings.append(
            "local Ollama coding model differs from the Sidar standard qwen2.5-coder:7b"
        )
    if not use_gpu and (docker_image and "gpu" in docker_image.lower()):
        warnings.append(
            "Docker image suggests GPU profile but runtime is CPU mode; verify NVIDIA Container "
            "Toolkit, CUDA visibility, and USE_GPU settings"
        )
    if access_level != "sandbox":
        warnings.append("CLI access level is not sandbox; verify this is intentional")
    status = "warn" if warnings else "pass"
    message = "; ".join(warnings or ["Local model and VRAM configuration look safe"])
    return DoctorCheck("gpu_memory_config", status, message, details)


def check_docker_test_image() -> DoctorCheck:
    """Report Docker test-image readiness independently from GPU configuration."""
    from config import Config

    docker_test_image = str(getattr(Config, "DOCKER_TEST_IMAGE", "") or "").strip()
    auto_build = os.getenv("AUTO_BUILD_DOCKER_TEST_IMAGE", "0") == "1"
    production_readiness = os.getenv("SIDAR_PRODUCTION_READINESS", "0") == "1"
    image_exists = _doctor._docker_image_exists_local(docker_test_image)
    details: dict[str, Any] = {
        "docker_test_image": docker_test_image,
        "image_exists": image_exists,
        "auto_build_docker_test_image": auto_build,
        "production_readiness": production_readiness,
        "recommended_commands": [],
    }

    if docker_test_image == "python:3.11-slim":
        message = (
            "DOCKER_TEST_IMAGE points to python:3.11-slim; Docker tests may miss Sidar test "
            "dependencies"
        )
        details["docker_image_container_note"] = (
            "Docker image is the reusable template, container is a running instance. Having a "
            "running sidar-* container does not prove sidar:latest exists locally."
        )
        details.setdefault("recommended_commands", []).extend(
            [
                "docker image ls | rg 'sidar|python'",
                "docker build -t sidar:latest .",
                "echo 'DOCKER_TEST_IMAGE=sidar:latest' >> .env.development",
            ]
        )
        return DoctorCheck("docker_test_image", "warn", message, details)
    if image_exists:
        return DoctorCheck("docker_test_image", "pass", "Docker test image is available", details)
    details["recommended_commands"] = [
        "AUTO_BUILD_DOCKER_TEST_IMAGE=1 DOCKER_TEST_IMAGE=sidar:latest bash run_tests.sh"
    ]
    if auto_build:
        return DoctorCheck(
            "docker_test_image",
            "pass",
            "Docker test image is missing; enabled auto-build will create it before tests",
            details,
        )
    if production_readiness:
        return DoctorCheck(
            "docker_test_image",
            "fail",
            "Docker test image is missing for production-readiness and auto-build is disabled",
            details,
        )
    return DoctorCheck(
        "docker_test_image",
        "pass",
        "Docker test image is not built yet; make dev-full enables its automatic build",
        {**details, "hint_level": "info"},
    )


def check_gpu() -> DoctorCheck:
    details: dict[str, Any] = {"detected": False, "run_gpu_stress": False}
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        rc, output = _doctor._run_command(
            [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"], timeout=10
        )
        if rc == 0 and output:
            details.update(
                {"detected": True, "source": "nvidia-smi", "devices": output.splitlines()}
            )
    if not details["detected"]:
        try:
            import torch

            if torch.cuda.is_available():
                details.update(
                    {
                        "detected": True,
                        "source": "torch",
                        "devices": [
                            torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
                        ],
                    }
                )
        except Exception as exc:
            details["torch_error"] = str(exc)

    details["run_gpu_stress"] = bool(details["detected"])
    return DoctorCheck(
        "gpu",
        "pass" if details["detected"] else "warn",
        "GPU detected; RUN_GPU_STRESS should be enabled"
        if details["detected"]
        else "GPU not detected; GPU stress tests remain opt-in",
        details,
    )


__all__ = ["check_docker_test_image", "check_gpu", "check_gpu_memory_config"]
