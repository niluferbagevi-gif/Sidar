"""Docker SDK lifecycle adapter for CodeManager."""

from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess  # nosec B404
import sys
from typing import Any, cast

from managers.code.docker import (
    LEGACY_PROJECT_IMAGE_PREFIXES,
    PROJECT_TEST_IMAGE_CANDIDATES,
    sanitize_docker_image,
)
from managers.image_resolver import canonical_project_image_alias, is_gpu_project_image

logger = logging.getLogger("managers.code_manager")


class DockerLifecycleAdapter:
    """Manage Docker SDK/CLI availability and project test-image discovery."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def resolve_runtime(self) -> str:
        owner = self.owner
        runtime = owner.docker_runtime
        if owner.docker_microvm_mode in ("gvisor", "runsc") and not runtime:
            runtime = "runsc"
        elif owner.docker_microvm_mode in ("kata", "firecracker") and not runtime:
            runtime = "kata-runtime"

        if runtime not in owner.docker_allowed_runtimes:
            logger.warning(
                "Docker runtime '%s' izinli listede değil (%s); varsayılan runtime kullanılacak.",
                runtime,
                owner.docker_allowed_runtimes,
            )
            return ""
        return cast(str, runtime)

    def try_wsl_socket_fallback(self, docker_module: Any) -> bool:
        owner = self.owner
        wsl_sockets = [
            "unix:///var/run/docker.sock",
            "unix:///mnt/wsl/docker-desktop/run/guest-services/backend.sock",
        ]
        for socket_path in wsl_sockets:
            fs_path = socket_path.removeprefix("unix://")
            try:
                file_stat = os.stat(fs_path)
            except OSError:
                continue
            if not stat.S_ISSOCK(file_stat.st_mode):
                logger.warning("Beklenen socket değil, atlanıyor: %s", fs_path)
                continue
            try:
                candidate = docker_module.DockerClient(base_url=socket_path)
                candidate.ping()
            except RuntimeError as exc:
                logger.warning("WSL2 socket ping başarısız (%s): %s", socket_path, exc)
                continue
            except owner._docker_exception_types(docker_module):
                continue
            owner.docker_client = candidate
            owner.docker_available = True
            logger.info("Docker bağlantısı WSL2 socket ile kuruldu: %s", socket_path)
            return True
        return False

    def try_docker_cli_fallback(self) -> bool:
        owner = self.owner
        docker_bin = shutil.which("docker")
        if not docker_bin:
            return False
        try:
            result = subprocess.run(  # nosec B603
                [docker_bin, "info"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(owner.base_dir),
            )
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
            return False

        if result.returncode != 0:
            return False

        owner.docker_client = None
        owner.docker_available = True
        logger.info(
            "Docker SDK bulunamadı ancak docker CLI erişilebilir; CLI fallback etkinleştirildi."
        )
        return True

    @staticmethod
    def docker_exception_types(docker_module: Any) -> tuple[type[BaseException], ...]:
        """Return Docker exception types safe to catch during daemon probes."""

        docker_errors = getattr(docker_module, "errors", None)
        docker_exception = getattr(docker_errors, "DockerException", None)
        if isinstance(docker_exception, type) and issubclass(docker_exception, BaseException):
            return (docker_exception, OSError, ValueError)
        return (OSError, ValueError)

    def init_docker(self) -> None:
        """Connect to Docker daemon, including WSL2 socket fallback."""

        owner = self.owner
        owner.docker_available = False
        owner.docker_client = None
        docker_module: Any | None = sys.modules.get("docker")
        try:
            if docker_module is None:
                import docker  # pragma: no cover - optional Docker dependency path

                docker_module = docker

            client = docker_module.from_env()
            client.ping()
            owner.docker_client = client
            owner.docker_available = True
            logger.info("Docker bağlantısı başarılı. REPL işlemleri izole konteynerde çalışacak.")
        except ImportError:
            if docker_module is not None and owner._try_wsl_socket_fallback(docker_module):
                return
            if owner._try_docker_cli_fallback():
                return
            logger.warning("Docker SDK kurulu değil. (uv pip install docker)")
        except Exception as first_err:
            fallback_module = docker_module
            if fallback_module is None:
                try:
                    import docker as fallback_module  # type: ignore[no-redef]
                except ImportError:
                    fallback_module = None

            if fallback_module is not None and owner._try_wsl_socket_fallback(fallback_module):
                return
            logger.warning(
                "Docker Daemon'a bağlanılamadı. Kod çalıştırma kapalı. "
                "WSL2 kullanıcıları: Docker Desktop'u açın ve "
                "Settings > Resources > WSL Integration'dan bu dağıtımı etkinleştirin. "
                "Hata: %s",
                first_err,
            )

    def docker_image_exists(self, image: str) -> bool:
        """Check Docker image existence through SDK first, then CLI."""

        owner = self.owner
        safe_image = sanitize_docker_image(image)
        if safe_image != image:
            return False

        if owner.docker_client is not None:
            images_api = getattr(owner.docker_client, "images", None)
            get_image = getattr(images_api, "get", None)
            if callable(get_image):
                try:
                    get_image(safe_image)
                    return True
                except Exception:
                    return False

        docker_bin = shutil.which("docker")
        if not docker_bin:
            return False
        try:
            result = subprocess.run(  # nosec B603
                [docker_bin, "image", "inspect", safe_image],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(owner.base_dir),
            )
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
            return False
        return result.returncode == 0

    def gpu_runtime_available(self) -> bool:
        """Probe NVIDIA/CUDA runtime availability once and cache the result on the owner."""

        owner = self.owner
        cached = getattr(owner, "_gpu_runtime_available_cached", None)
        if cached is not None:
            return bool(cached)

        available = False
        try:
            probe = subprocess.run(  # nosec B603
                [shutil.which("nvidia-smi") or "nvidia-smi"],
                capture_output=True,
                text=True,
                timeout=3,
                cwd=str(owner.base_dir),
            )
            if probe.returncode == 0:
                available = True
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
            pass

        owner._gpu_runtime_available_cached = available
        return available

    def autodetect_project_test_image(self) -> None:
        """Select a local Sidar test image without pulling legacy Docker Hub names."""

        owner = self.owner
        if not owner.docker_available:  # pragma: no cover - Docker unavailable branch
            return

        canonical_alias = canonical_project_image_alias(
            owner.docker_test_image, legacy_prefixes=LEGACY_PROJECT_IMAGE_PREFIXES
        )
        if owner._docker_test_image_explicit:
            if not canonical_alias:
                owner._warn_gpu_image_runtime_mismatch(owner.docker_test_image)
                return
            if owner._docker_image_exists(owner.docker_test_image):
                owner._warn_gpu_image_runtime_mismatch(owner.docker_test_image)
                return
            if owner._docker_image_exists(canonical_alias):
                logger.warning(
                    "DOCKER_TEST_IMAGE eski Sidar imaj adını gösteriyor (%s) ancak bu imaj "
                    "lokalde yok; bulunan güncel imaj kullanılacak: %s",
                    owner.docker_test_image,
                    canonical_alias,
                )
                owner.docker_test_image = canonical_alias
                owner._warn_gpu_image_runtime_mismatch(owner.docker_test_image)
            return

        prefer_gpu_image = (
            bool(getattr(owner.cfg, "USE_GPU", False)) and owner._gpu_runtime_available()
        )
        if bool(getattr(owner.cfg, "USE_GPU", False)) and not prefer_gpu_image:
            logger.warning(
                "USE_GPU=True ancak CUDA/NVIDIA runtime tespit edilemedi; CPU test imajı tercih edilecek"
            )

        for candidate in PROJECT_TEST_IMAGE_CANDIDATES:
            if is_gpu_project_image(candidate) and not prefer_gpu_image:
                logger.info(
                    "GPU test imajı CUDA runtime olmadığı için atlandı: %s",
                    candidate,
                )
                continue
            if owner._docker_image_exists(candidate):
                owner.docker_test_image = candidate
                logger.info(
                    "DOCKER_TEST_IMAGE verilmedi; Docker daemon'da bulunan proje test imajı kullanılacak: %s",
                    candidate,
                )
                owner._warn_gpu_image_runtime_mismatch(candidate)
                return

        logger.warning(
            "DOCKER_TEST_IMAGE otomatik bulunamadı; varsayılan sandbox imajı (%s) pytest/uv içermeyebilir. "
            "Önerilen sıra: (1) `docker build -t sidar:latest .` (2) `.env` veya `.env.development` içine "
            "`DOCKER_TEST_IMAGE=sidar:latest` ekleyin (3) kalite kapısında bilinçli otomatik hazırlık için "
            "`AUTO_BUILD_DOCKER_TEST_IMAGE=1 DOCKER_TEST_IMAGE=sidar:latest bash run_tests.sh` çalıştırın "
            "(4) Docker dışı fallback için `uv sync --frozen --all-extras` çalıştırın.",
            owner.docker_test_image,
        )
