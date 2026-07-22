"""Sidar Project - Kod Yöneticisi.

Dosya okuma, yazma, sözdizimi doğrulama ve DOCKER İZOLELİ kod analizi (REPL).
Sürüm: 2.7.0
"""

import contextlib
import logging
import os
import shlex
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import Any

from core.hitl import get_hitl_gate
from managers.code import docker as docker_helpers
from managers.code import file_io_security, linter_runners, runner, test_runner_orchestrator
from managers.code.docker import (
    LEGACY_PROJECT_IMAGE_PREFIXES as _LEGACY_PROJECT_IMAGE_PREFIXES,
)
from managers.code.docker import (
    build_docker_cli_command,
    execute_code_with_docker_cli,
    resolve_sandbox_limits,
    sanitize_docker_image,
    sanitize_docker_network,
    sanitize_docker_token,
)
from managers.code.docker import (
    to_int as _to_int,
)
from managers.code.docker_lifecycle import DockerLifecycleAdapter
from managers.code.lsp import (
    LSPProtocolError,
    decode_lsp_stream,
    encode_lsp_message,
    file_uri_to_path,
    path_to_file_uri,
)
from managers.code.platform import candidate_lsp_executable_paths
from managers.code.pytest_parser import (
    command_invokes_pytest,
    command_requires_uv_tooling,
    extract_pytest_args,
)
from managers.code.runner import build_sanitized_shell_args
from managers.code.security_adapter import CodeSecurityAdapter
from managers.code.shell_sandbox import ShellSandboxAdapter
from managers.image_resolver import canonical_project_image_alias, is_gpu_project_image

try:
    from config import SANDBOX_LIMITS, Config
except ImportError:
    from config import Config

    SANDBOX_LIMITS = {}
from .security import SANDBOX, SecurityManager

logger = logging.getLogger(__name__)
_OS_NAME = os.name
_LSPProtocolError = LSPProtocolError
_encode_lsp_message = encode_lsp_message
_decode_lsp_stream = decode_lsp_stream
_DOCKER_MEMORY_RE = docker_helpers.DOCKER_MEMORY_RE
_DOCKER_CPUS_RE = docker_helpers.DOCKER_CPUS_RE
_DOCKER_NETWORK_ALLOWED = docker_helpers.DOCKER_NETWORK_ALLOWED
_DOCKER_IMAGE_RE = docker_helpers.DOCKER_IMAGE_RE
_sanitize_docker_token = sanitize_docker_token
_sanitize_docker_network = sanitize_docker_network
_sanitize_docker_image = sanitize_docker_image


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:  # pragma: no cover - defensive default branch
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:  # pragma: no cover - env parsing branch
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    logger.warning("Unknown boolean value %r; using default=%s.", value, default)
    return default


class DockerState(Enum):
    """Lazy Docker initialization lifecycle for code execution backends."""

    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    READY = "ready"
    FAILED = "failed"
    DISABLED = "disabled"


def _path_to_file_uri(path: Path) -> str:
    """Backwards-compatible facade for LSP URI encoding."""
    return path_to_file_uri(path, path_separator=os.sep)


def _file_uri_to_path(uri: str) -> Path | PureWindowsPath:
    """Backwards-compatible facade for platform-sensitive LSP URI decoding."""
    return file_uri_to_path(uri, os_name=_OS_NAME)


def _build_sanitized_shell_args(command: str, *, allow_shell_features: bool) -> list[str]:
    """Backwards-compatible facade for sanitized shell argument construction."""
    return build_sanitized_shell_args(
        command, allow_shell_features=allow_shell_features, find_executable=shutil.which
    )


def _canonical_project_image_alias(image: str) -> str | None:
    """Eski Sidar proje imaj adlarını güncel Docker tag karşılığına çevir."""
    return canonical_project_image_alias(image, legacy_prefixes=_LEGACY_PROJECT_IMAGE_PREFIXES)


def _is_gpu_project_image(image: str) -> bool:
    return is_gpu_project_image(image)


class CodeManager:
    """PEP 8 uyumlu dosya işlemleri ve sözdizimi doğrulama.

    Thread-safe RLock ile korunur.
    Kod çalıştırma (execute_code) işlemleri Docker ile izole edilir.
    """

    SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".json", ".yaml", ".yml", ".md", ".txt", ".sh"}

    def __init__(
        self,
        security: SecurityManager,
        base_dir: Path | str,
        docker_image: str | None = None,
        docker_exec_timeout: int | None = None,
        cfg: Config | None = None,
    ) -> None:
        self.security = security
        self.security_adapter = CodeSecurityAdapter(security)
        self.base_dir = Path(base_dir).resolve()
        self.cfg = cfg or Config()
        self.code_execution_backend = (
            str(
                getattr(
                    self.cfg,
                    "CODE_EXECUTION_BACKEND",
                    os.getenv("CODE_EXECUTION_BACKEND", "docker"),
                )
                or "docker"
            )
            .strip()
            .lower()
        )
        self.docker_autodetect = _coerce_bool(
            getattr(self.cfg, "DOCKER_AUTODETECT", os.getenv("DOCKER_AUTODETECT", "1")),
            default=True,
        )
        self.docker_runtime = str(getattr(self.cfg, "DOCKER_RUNTIME", "") or "").strip()
        self.docker_allowed_runtimes = list(
            getattr(self.cfg, "DOCKER_ALLOWED_RUNTIMES", ["", "runc", "runsc", "kata-runtime"])
            or [""]
        )
        self.docker_microvm_mode = (
            str(getattr(self.cfg, "DOCKER_MICROVM_MODE", "off") or "off").strip().lower()
        )
        self.docker_mem_limit = str(getattr(self.cfg, "DOCKER_MEM_LIMIT", "256m") or "256m").strip()
        self.docker_network_disabled = bool(getattr(self.cfg, "DOCKER_NETWORK_DISABLED", True))
        self.docker_nano_cpus = int(
            getattr(self.cfg, "DOCKER_NANO_CPUS", 1_000_000_000) or 1_000_000_000
        )
        self.docker_image: str = str(
            docker_image
            or getattr(self.cfg, "DOCKER_IMAGE", "")
            or getattr(self.cfg, "DOCKER_PYTHON_IMAGE", "python:3.11-slim")
        )
        configured_test_image = str(getattr(self.cfg, "DOCKER_TEST_IMAGE", "") or "").strip()
        if not configured_test_image:
            configured_test_image = "sidar:latest"
        self._docker_test_image_explicit = bool(
            getattr(self.cfg, "DOCKER_TEST_IMAGE_EXPLICIT", False)
        ) or (bool(configured_test_image) and configured_test_image != self.docker_image)
        self.docker_test_image: str = configured_test_image or self.docker_image
        self.docker_exec_timeout = (
            int(docker_exec_timeout)
            if docker_exec_timeout is not None
            else _to_int(
                getattr(self.cfg, "DOCKER_EXEC_TIMEOUT", SANDBOX_LIMITS.get("timeout", 10)),
                10,
            )
        )
        self.max_output_chars = 10000
        self._lock = threading.RLock()

        # Metrikler
        self._files_read = 0
        self._files_written = 0
        self._syntax_checks = 0
        self._audits_done = 0
        self.enable_lsp = bool(getattr(self.cfg, "ENABLE_LSP", True))
        self.lsp_timeout_seconds = int(getattr(self.cfg, "LSP_TIMEOUT_SECONDS", 15) or 15)
        self.lsp_max_references = int(getattr(self.cfg, "LSP_MAX_REFERENCES", 200) or 200)
        self.python_lsp_server = str(
            getattr(self.cfg, "PYTHON_LSP_SERVER", "pyright-langserver") or "pyright-langserver"
        )
        self.typescript_lsp_server = str(
            getattr(self.cfg, "TYPESCRIPT_LSP_SERVER", "typescript-language-server")
            or "typescript-language-server"
        )

        # Docker İstemcisi Bağlantısı
        self.docker_available = False
        self.docker_client: Any | None = None
        self._docker_state = DockerState.UNINITIALIZED
        self._docker_init_lock = threading.RLock()
        self._docker_init_attempts = 0
        self._docker_init_max_attempts = max(
            1, _to_int(getattr(self.cfg, "DOCKER_INIT_MAX_ATTEMPTS", 2), 2)
        )
        self.docker_lifecycle = DockerLifecycleAdapter(self)
        self.shell_sandbox = ShellSandboxAdapter(self)
        if self.code_execution_backend not in {"docker", "disabled", "none", "off"}:
            raise ValueError(
                "Unsupported CODE_EXECUTION_BACKEND value "
                f"{self.code_execution_backend!r}; expected 'docker' or 'disabled'."
            )

    @property
    def _docker_initialized(self) -> bool:
        """Backward-compatible test facade for legacy lazy-init assertions."""
        return self._docker_state in {DockerState.READY, DockerState.DISABLED}

    def ensure_docker_initialized(self) -> None:
        """Initialize Docker lazily when code execution actually needs it."""
        with self._docker_init_lock:
            if self._docker_state in {DockerState.READY, DockerState.DISABLED}:
                return
            if self.code_execution_backend in {
                "disabled",
                "none",
                "off",
            }:  # pragma: no cover - deployment-mode branch
                logger.info("Code execution backend disabled; Docker initialization skipped.")
                self.docker_available = False
                self.docker_client = None
                self._docker_state = DockerState.DISABLED
                return
            if self._docker_init_attempts >= self._docker_init_max_attempts:
                logger.warning(
                    "Docker initialization retry limit reached (%s attempts);"
                    " leaving backend degraded.",
                    self._docker_init_attempts,
                )
                self._docker_state = DockerState.FAILED
                return

            self._docker_state = DockerState.INITIALIZING
            self._docker_init_attempts += 1
            try:
                self._init_docker()
                if self.docker_available:
                    self._docker_state = DockerState.READY
                    if self.docker_autodetect:
                        self._autodetect_project_test_image()
                else:
                    self._docker_state = DockerState.FAILED
            except Exception:
                self._docker_state = DockerState.FAILED
                self.docker_available = False
                self.docker_client = None
                raise

    def _resolve_runtime(self) -> str:
        return self.docker_lifecycle.resolve_runtime()

    def _resolve_sandbox_limits(self) -> dict[str, object]:
        """Docker çalıştırma limitlerini normalize eder (cgroups)."""
        return resolve_sandbox_limits(self, SANDBOX_LIMITS)

    def _build_docker_cli_command(self, code: str, limits: dict[str, object]) -> list[str]:
        """Docker CLI ile sandbox çalıştırma komutunu oluşturur."""
        return build_docker_cli_command(code, limits, image=self.docker_image)

    def _execute_code_with_docker_cli(
        self, code: str, limits: dict[str, object]
    ) -> tuple[bool, str]:
        """Docker SDK başarısız olursa docker CLI ile çalıştırmayı dener."""
        return execute_code_with_docker_cli(self, code, limits, run_command=subprocess.run)

    def _try_wsl_socket_fallback(self, docker_module: Any) -> bool:
        """Docker Desktop/WSL2 socket yollarını deneyerek istemci başlatır."""
        return self.docker_lifecycle.try_wsl_socket_fallback(docker_module)

    def _try_docker_cli_fallback(self) -> bool:
        """Docker SDK yoksa CLI üzerinden daemon erişimini doğrular."""
        return self.docker_lifecycle.try_docker_cli_fallback()

    @staticmethod
    def _docker_exception_types(docker_module: Any) -> tuple[type[BaseException], ...]:
        """Docker bağlantı denemelerinde yakalanacak güvenli exception tiplerini döndürür."""
        return DockerLifecycleAdapter.docker_exception_types(docker_module)

    def _init_docker(self) -> None:
        """Docker daemon'a bağlanmayı dener. WSL2 ortamında alternatif socket yollarını dener."""
        self.docker_lifecycle.init_docker()

    def _docker_image_exists(self, image: str) -> bool:
        """Docker daemon'da verilen imajın mevcut olup olmadığını SDK/CLI ile kontrol et."""
        return self.docker_lifecycle.docker_image_exists(image)

    def _autodetect_project_test_image(self) -> None:
        """Docker daemon'da bulunan Sidar test imajını güvenli biçimde seç."""
        self.docker_lifecycle.autodetect_project_test_image()

    def _gpu_runtime_available(self) -> bool:
        """CUDA/NVIDIA runtime kullanılabilirliğini önbellekli olarak kontrol et."""
        return self.docker_lifecycle.gpu_runtime_available()

    def _warn_gpu_image_runtime_mismatch(self, image_name: str) -> None:
        if not _is_gpu_project_image(image_name):
            return
        if self._gpu_runtime_available():
            return
        logger.warning(
            "GPU image selected but CUDA runtime unavailable — falling back to CPU; "
            "consider sidar-cpu:latest (image=%s)",
            image_name,
        )

    # ─────────────────────────────────────────────
    #  DOSYA OKUMA
    # ─────────────────────────────────────────────

    def read_file(self, path: str, line_numbers: bool = True) -> tuple[bool, str]:
        """Dosya içeriğini güvenlik denetimi sonrası okur."""
        return file_io_security.read_file(self, path, line_numbers=line_numbers)

    def write_file(self, path: str, content: str, validate: bool = True) -> tuple[bool, str]:
        """Dosyaya güvenli biçimde içerik yazar."""
        return file_io_security.write_file(self, path, content, validate=validate)

    async def write_file_hitl(
        self, path: str, content: str, validate: bool = True
    ) -> tuple[bool, str]:
        """Require human approval before overwriting an existing file."""
        target = Path(path)
        if target.exists():
            approved = await get_hitl_gate().request_approval(
                action="file_overwrite",
                description=f"Dosyanın üzerine yazılacak: {target}",
                payload={"path": str(target)},
                requested_by="CodeManager",
            )
            if not approved:
                return False, "Dosya üzerine yazma işlemi insan onayı olmadan reddedildi."
        return file_io_security.write_file(self, path, content, validate=validate)

    @staticmethod
    def _strip_markdown_code_fences(content: str) -> str:
        return file_io_security.strip_markdown_code_fences(content)

    def _post_process_written_file(self, target: Path) -> None:
        linter_runners.post_process_written_file(target)

    def write_generated_test(
        self,
        path: str,
        content: str,
        *,
        append: bool = True,
        marker: str = "# Generated by CoverageAgent",
    ) -> tuple[bool, str]:
        """Coverage ajanı için üretilen pytest içeriğini güvenli biçimde yazar."""
        return file_io_security.write_generated_test(
            self, path, content, append=append, marker=marker
        )

    def patch_file(self, path: str, target_block: str, replacement_block: str) -> tuple[bool, str]:
        """Dosyada hedef bloğu güvenli biçimde değiştirir."""
        return file_io_security.patch_file(self, path, target_block, replacement_block)

    async def patch_file_hitl(
        self, path: str, target_block: str, replacement_block: str
    ) -> tuple[bool, str]:
        """Require human approval before patching an existing file."""
        ok, content = self.read_file(path, line_numbers=False)
        if not ok:
            return False, content
        ok, patched_or_error = file_io_security.apply_exact_block_patch(
            content, target_block, replacement_block
        )
        if not ok:
            return False, patched_or_error
        return await self.write_file_hitl(path, patched_or_error, validate=True)

    def execute_code(self, code: str) -> tuple[bool, str]:
        """Kodu tamamen İZOLE ve geçici bir Docker konteynerinde çalıştırır.

        - Ağ erişimi kapalı (network_disabled=True)
        - Dosya sistemi okunaksız/geçici
        - Bellek/CPU/PID kotaları (cgroups)
        - Zaman aşımı koruması (configurable)
        """
        if not self.security.can_execute():
            return False, "[OpenClaw] Kod çalıştırma yetkisi yok (Restricted Mod)."
        if self.code_execution_backend in {
            "disabled",
            "none",
            "off",
        }:  # pragma: no cover - deployment-mode branch
            return False, "Kod çalıştırma backend'i devre dışı (CODE_EXECUTION_BACKEND=disabled)."

        self.ensure_docker_initialized()

        if not self.docker_available:
            if self.security.level == SANDBOX:
                return False, (
                    "HATA: Docker Sandbox erişilemedi ve güvenlik politikası gereği "
                    "yerel (unsafe) çalıştırma engellendi."
                )
            if Config.DOCKER_REQUIRED:
                return False, (
                    "[GÜVENLİK] DOCKER_REQUIRED=true — yerel subprocess fallback devre dışı. "
                    "Docker daemon'ı başlatın veya DOCKER_REQUIRED=false olarak ayarlayın."
                )
            logger.warning("Docker yok — FULL modda yerel subprocess fallback kullanılacak.")
            return self.execute_code_local(code)

        try:
            import docker  # noqa: F401

            # Kodu konteynere komut satırı argümanı olarak gönderiyoruz.
            # ENTRYPOINT override, proje Dockerfile'ındaki uygulama entrypoint'inin
            # kısa REPL doğrulamalarını yutmasını engeller.
            sandbox_limits = self._resolve_sandbox_limits()

            # Konteyneri başlat (Arka planda ayrılmış olarak)
            run_kwargs = {
                "image": self.docker_image,
                "entrypoint": "python",
                "command": ["-c", code],
                "detach": True,
                "remove": False,
                "working_dir": tempfile.gettempdir(),
                "mem_limit": sandbox_limits["memory"],
                "nano_cpus": sandbox_limits["nano_cpus"],
                "pids_limit": sandbox_limits["pids_limit"],
            }
            if self.docker_network_disabled or sandbox_limits["network_mode"] == "none":
                run_kwargs["network_mode"] = "none"
            selected_runtime = self._resolve_runtime()
            if selected_runtime:
                run_kwargs["runtime"] = selected_runtime

            if self.docker_client is None:
                return False, "Docker istemcisi başlatılamadı."
            container = self.docker_client.containers.run(**run_kwargs)

            # Zaman aşımı takibi (Config'den okunur, varsayılan 10 sn)
            timeout = _to_int(sandbox_limits["timeout"], 10)
            start_time = time.time()

            while True:
                container.reload()  # Durumu güncelle
                if container.status == "exited":
                    break
                if time.time() - start_time > timeout:
                    container.kill()  # Süre aşımında zorla durdur
                    container.remove(force=True)
                    return False, (
                        f"⚠ Zaman aşımı! Kod {timeout} saniyeden uzun sürdü ve "
                        "zorla durduruldu (sonsuz döngü koruması)."
                    )
                time.sleep(0.5)

            # Çıktıları al
            logs = container.logs(stdout=True, stderr=True).decode("utf-8").strip()

            exit_code = None
            if hasattr(container, "wait"):
                try:
                    wait_result = container.wait(timeout=1)
                    if isinstance(wait_result, dict):
                        exit_code = wait_result.get("StatusCode")
                except Exception:
                    exit_code = None

            # İşimiz bitti, konteyneri sil
            container.remove(force=True)

            if exit_code not in (None, 0):
                return False, f"REPL Hatası (Docker Sandbox):\n{logs or '(çıktı yok)'}"

            # Çıktı Boyutu Limiti (Güvenlik)
            if len(logs) > self.max_output_chars:
                logs = logs[: self.max_output_chars] + (
                    "\n\n... [ÇIKTI KIRPILDI: Maksimum"
                    f" {self.max_output_chars} karakter sınırı aşıldı] ..."
                )

            if logs:
                return True, f"REPL Çıktısı (Docker Sandbox):\n{logs}"
            else:
                return True, "(Kod başarıyla çalıştı ancak konsola bir çıktı üretmedi)"

        except docker.errors.ImageNotFound:
            return False, (
                f"Çalıştırma hatası: '{self.docker_image}' imajı bulunamadı. "
                f"Lütfen terminalde 'docker pull {self.docker_image}' komutunu çalıştırın."
            )
        except Exception as exc:
            if self.security.level == SANDBOX:
                return False, (
                    "HATA: Docker Sandbox başarısız oldu ve güvenlik politikası gereği "
                    f"yerel (unsafe) çalıştırma engellendi. Detay: {exc}"
                )

            sandbox_limits = self._resolve_sandbox_limits()
            try:
                return self._execute_code_with_docker_cli(code, sandbox_limits)
            except subprocess.TimeoutExpired:
                return False, (
                    f"⚠ Zaman aşımı! Kod {sandbox_limits['timeout']} saniyeden uzun sürdü ve "
                    "zorla durduruldu (sonsuz döngü koruması)."
                )
            except Exception as cli_exc:
                logger.warning(
                    "Docker çalıştırma hatası — FULL modda yerel subprocess fallback: %s", cli_exc
                )
                return self.execute_code_local(code)

    def execute_code_local(self, code: str) -> tuple[bool, str]:
        """Docker kullanılamadığında Python kodu güvenli subprocess ile çalıştırır.

        - sys.executable kullanır (aktif Conda/venv ortamı korunur)
        - Geçici dosyaya yazar, 10 sn timeout ile çalıştırır
        - Ağ erişimi açıktır (yalnızca Docker izolasyonundan farklı)
        """
        # Güvenlik uyarısı: Docker sandbox yok, kod izole edilmeden çalışıyor
        logger.warning(
            "[GÜVENLİK] Kod Docker izolasyonu OLMADAN yerel subprocess ile çalıştırılıyor. "
            "Ağ erişimi, dosya sistemi ve kaynak limitleri kısıtlı değil. "
            "Üretim ortamında Docker daemon'ın erişilebilir olduğundan emin olun."
        )
        if not self.security.can_execute():
            return False, "[OpenClaw] Kod çalıştırma yetkisi yok (Restricted Mod)."

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name

            python_bin = (
                sys.executable or shutil.which("python3") or shutil.which("python") or "python"
            )
            result = subprocess.run(  # nosec B603
                [python_bin, tmp_path],
                capture_output=True,
                text=True,
                timeout=self.docker_exec_timeout,
                cwd=str(self.base_dir),
            )

            output = (result.stdout + result.stderr).strip()

            # Çıktı Boyutu Limiti (Güvenlik)
            if len(output) > self.max_output_chars:
                output = output[: self.max_output_chars] + (
                    "\n\n... [ÇIKTI KIRPILDI: Maksimum"
                    f" {self.max_output_chars} karakter sınırı aşıldı] ..."
                )

            if result.returncode != 0:
                return False, f"REPL Çıktısı (Subprocess — Docker yok):\n{output or '(çıktı yok)'}"
            return (
                True,
                f"REPL Çıktısı (Subprocess — Docker yok):\n{output or '(kod çalıştı, çıktı yok)'}",
            )

        except subprocess.TimeoutExpired:
            return False, (
                f"⚠ Zaman aşımı! Kod {self.docker_exec_timeout} saniyeden uzun sürdü "
                "(sonsuz döngü koruması)."
            )
        except Exception as exc:
            return False, f"Subprocess çalıştırma hatası: {exc}"
        finally:
            if tmp_path:
                with contextlib.suppress(Exception):
                    Path(tmp_path).unlink(missing_ok=True)

    # ─────────────────────────────────────────────
    #  KABUK KOMUTU ÇALIŞTIRMA (SHELL EXECUTION)
    # ─────────────────────────────────────────────

    @staticmethod
    def _extract_pytest_args(command: str) -> list[str]:
        """Backwards-compatible facade for the extracted pytest parser."""
        return extract_pytest_args(command)

    def _build_pytest_preflight_command(self, command: str) -> str:
        """Sandbox içinde pytest yoksa proje/image venv veya uv üzerinden bootstrap et."""
        return test_runner_orchestrator.build_pytest_preflight_command(self, command)

    @staticmethod
    def _command_requires_uv_tooling(command: str) -> bool:
        """Backwards-compatible facade for sandbox tooling classification."""
        return command_requires_uv_tooling(command)

    def _select_shell_sandbox_image(self, command: str, image: str | None) -> str:
        """Test/uv komutlarında proje test imajını, diğerlerinde normal sandbox imajını seç."""
        return self.shell_sandbox.select_shell_sandbox_image(command, image)

    @staticmethod
    def _command_invokes_pytest(command: str) -> bool:
        """Backwards-compatible facade for direct pytest invocation detection."""
        return command_invokes_pytest(command)

    def _build_shell_preflight_command(self, command: str) -> str:
        """Sandbox shell komutları için PATH ve uv/pytest pre-flight koruması ekle."""
        return self.shell_sandbox.build_shell_preflight_command(command)

    def run_shell_in_sandbox(
        self,
        command: str,
        cwd: str | None = None,
        image: str | None = None,
    ) -> tuple[bool, str]:
        """Kabuk komutunu Docker sandbox içinde çalıştırır."""
        return self.shell_sandbox.run_shell_in_sandbox(command, cwd=cwd, image=image)

    @staticmethod
    def analyze_pytest_output(output: str) -> dict[str, Any]:
        return test_runner_orchestrator.analyze_pytest_output(output)

    def run_pytest_and_collect(
        self,
        command: str = "pytest -q",
        cwd: str | None = None,
    ) -> dict[str, Any]:
        return test_runner_orchestrator.run_pytest_and_collect(self, command=command, cwd=cwd)

    def run_shell(
        self,
        command: str,
        cwd: str | None = None,
        allow_shell_features: bool = False,
    ) -> tuple[bool, str]:
        """Kabuk komutunu güvenli subprocess helper'ı üzerinden çalıştırır."""
        return runner.run_shell_command(
            self, command, cwd=cwd, allow_shell_features=allow_shell_features
        )

    # ─────────────────────────────────────────────
    #  GLOB DOSYA ARAMA
    # ─────────────────────────────────────────────

    def glob_search(self, pattern: str, base_path: str = ".") -> tuple[bool, str]:
        """Glob deseni ile dosya ara. Claude Code'daki Glob aracına eşdeğer.

        Örnek desenler:
          **/*.py          → tüm .py dosyaları
          src/**/*.ts      → src/ altındaki .ts dosyaları
          *.{json,yml}     → json veya yml dosyaları
          agent/*.py       → agent/ altındaki .py dosyaları

        Args:
            pattern: Glob deseni
            base_path: Arama başlangıç dizini

        Returns:
            (başarı, eşleşen_dosyalar_listesi)
        """
        return file_io_security.glob_search(self, pattern, base_path)

    # ─────────────────────────────────────────────
    #  İÇERİK ARAMA (GREP)
    # ─────────────────────────────────────────────

    def grep_files(
        self,
        pattern: str,
        path: str = ".",
        file_glob: str = "*",
        case_sensitive: bool = True,
        context_lines: int = 0,
        max_results: int = 100,
    ) -> tuple[bool, str]:
        """Regex ile dosya içeriği ara. Claude Code'daki Grep aracına eşdeğer.

        Args:
            pattern: Aranacak regex kalıbı
            path: Arama dizini veya dosya yolu
            file_glob: Dosya filtresi (örn: "*.py", "*.{ts,tsx}")
            case_sensitive: Büyük/küçük harf duyarlılığı
            context_lines: Her eşleşme etrafında gösterilecek satır sayısı
            max_results: Maksimum eşleşme sayısı

        Returns:
            (başarı, eşleşmeler_raporu)
        """
        return file_io_security.grep_files(
            self,
            pattern,
            path=path,
            file_glob=file_glob,
            case_sensitive=case_sensitive,
            context_lines=context_lines,
            max_results=max_results,
        )

    # ─────────────────────────────────────────────
    #  DİZİN LİSTELEME
    # ─────────────────────────────────────────────

    def list_directory(self, path: str = ".") -> tuple[bool, str]:
        """Dizin içeriğini listele."""
        return file_io_security.list_directory(self, path)

    # ─────────────────────────────────────────────
    #  SÖZDİZİMİ DOĞRULAMA
    # ─────────────────────────────────────────────

    def validate_python_syntax(self, code: str) -> tuple[bool, str]:
        with self._lock:
            self._syntax_checks += 1
        return linter_runners.validate_python_syntax(code)

    def validate_json(self, content: str) -> tuple[bool, str]:
        return linter_runners.validate_json(content)

    def _detect_language_id(self, path: Path) -> str | None:
        suffix = path.suffix.lower()
        if suffix == ".py":
            return "python"
        if suffix in {".ts", ".tsx", ".js", ".jsx"}:
            return "typescript"
        return None

    def _candidate_lsp_executable_paths(self, binary: str) -> list[Path]:
        """Backwards-compatible facade for platform-specific LSP candidates."""
        return candidate_lsp_executable_paths(
            binary,
            base_dir=self.base_dir,
            python_virtual_env=str(getattr(self.cfg, "PYTHON_VIRTUAL_ENV", "") or ""),
            python_conda_prefix=str(getattr(self.cfg, "PYTHON_CONDA_PREFIX", "") or ""),
            os_name=os.name,
            sys_prefix=sys.prefix,
        )

    def _resolve_lsp_executable(self, binary: str) -> str | None:
        """LSP binary'sini PATH, aktif venv ve proje .venv içinde deterministik çöz."""
        binary_path = shutil.which(binary)
        if binary_path:
            return binary_path

        binary_candidate = Path(binary)
        if binary_candidate.parent != Path(".") and binary_candidate.exists():
            return str(binary_candidate)

        for candidate in self._candidate_lsp_executable_paths(binary):
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)
        return None

    def _resolve_lsp_command(self, language_id: str) -> list[str]:
        if language_id == "python":
            server_command = self.python_lsp_server
            default_binary = "pyright-langserver"
            default_args = ["--stdio"]
        elif language_id == "typescript":
            server_command = self.typescript_lsp_server
            default_binary = "typescript-language-server"
            default_args = ["--stdio"]
        else:
            raise ValueError(f"LSP desteklenmeyen dil: {language_id}")

        tokens = shlex.split(server_command) if server_command else []
        binary = tokens[0] if tokens else default_binary
        configured_args = tokens[1:]
        args = configured_args or default_args

        binary_path = self._resolve_lsp_executable(binary)
        if binary_path:
            return [binary_path, *args]

        # Python LSP fallback chain:
        # 1. `uv run --frozen <binary>` uses the repo-locked pyright dev dependency
        #    and avoids ad-hoc downloads when the executable is absent from PATH.
        # 2. `uvx --from pyright <binary>` is the global-tool fallback for systems
        #    that have uvx but have not synced the project environment yet.
        if language_id == "python":
            uv_path = shutil.which("uv")
            if uv_path:
                return [uv_path, "run", "--frozen", binary, *args]
            if binary == "pyright-langserver":
                uvx_path = shutil.which("uvx")
                if uvx_path:
                    return [uvx_path, "--from", "pyright", binary, *args]

        return [binary, *args]

    @staticmethod
    def _lsp_install_hint(language_id: str) -> str:
        if language_id == "python":
            return "uv tool install pyright  # veya: uv add --dev pyright"
        return "npm install -g typescript-language-server typescript"

    def _lsp_target_binary(self, command: list[str], language_id: str) -> str:
        """uv/uvx ile sarmalanmış komutta hedef LSP binary adını döndür."""
        default = self.python_lsp_server if language_id == "python" else self.typescript_lsp_server
        if not command:
            return default
        head = Path(command[0]).name.lower()
        if head in {"uv", "uvx"}:
            # `--from <paket>` ve `--with <paket>` argümanları bir değer alır;
            # bunların değerlerini atlayarak gerçek binary'yi yakala.
            skip_next = False
            for token in command[1:]:
                if skip_next:
                    skip_next = False
                    continue
                if token in {"--from", "--with"}:
                    skip_next = True
                    continue
                if token in {"run", "--frozen", "tool"}:
                    continue
                if token.startswith("-"):
                    continue
                return token
        return default

    @staticmethod
    def _lsp_stderr_indicates_missing_binary(stderr_text: str) -> bool:
        """Sezgisel olarak 'binary bulunamadı' hatasını tespit et.

        uv/uvx benzeri sarmalayıcıların stderr çıktısını kontrol eder.
        """
        if not stderr_text:
            return False
        lowered = stderr_text.lower()
        missing_markers = (
            "failed to spawn",
            "no such file or directory",
            "command not found",
            "executable not found",
            "not found in",
        )
        return any(marker in lowered for marker in missing_markers)

    def _normalize_lsp_path(self, path: str) -> Path:
        target = Path(path)
        if not target.is_absolute():
            target = self.base_dir / target
        return target.resolve()

    def _build_lsp_initialize_payload(self, workspace_root: Path) -> dict[str, Any]:
        workspace_uri = _path_to_file_uri(workspace_root)
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "processId": os.getpid(),
                "rootUri": workspace_uri,
                "workspaceFolders": [
                    {"uri": workspace_uri, "name": workspace_root.name or "workspace"}
                ],
                "capabilities": {
                    "workspace": {
                        "workspaceEdit": {"documentChanges": True},
                    },
                    "textDocument": {
                        "definition": {"dynamicRegistration": False},
                        "references": {"dynamicRegistration": False},
                        "rename": {"dynamicRegistration": False},
                        "publishDiagnostics": {"relatedInformation": True},
                    },
                },
            },
        }

    def _run_lsp_sequence(
        self,
        *,
        primary_path: Path,
        request_method: str | None,
        request_params: dict[str, Any] | None = None,
        extra_open_files: list[Path] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.enable_lsp:
            raise RuntimeError("ENABLE_LSP devre dışı.")

        language_id = self._detect_language_id(primary_path)
        if language_id is None:
            raise ValueError(f"LSP için desteklenmeyen dosya türü: {primary_path.suffix}")

        workspace_root = self.base_dir.resolve()
        command = self._resolve_lsp_command(language_id)
        open_files = [primary_path]
        for extra_path in extra_open_files or []:
            resolved_extra = extra_path.resolve()
            if resolved_extra not in open_files and resolved_extra.exists():
                open_files.append(resolved_extra)

        messages: list[dict[str, Any]] = [self._build_lsp_initialize_payload(workspace_root)]
        messages.append({"jsonrpc": "2.0", "method": "initialized", "params": {}})

        for file_path in open_files:
            language = self._detect_language_id(file_path)
            if language is None:
                continue
            messages.append(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {
                            "uri": _path_to_file_uri(file_path),
                            "languageId": language,
                            "version": 1,
                            "text": file_path.read_text(encoding="utf-8", errors="replace"),
                        }
                    },
                }
            )

        if request_method is not None:
            messages.append(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": request_method,
                    "params": request_params or {},
                }
            )

        messages.append({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": None})
        messages.append({"jsonrpc": "2.0", "method": "exit", "params": {}})

        payload = b"".join(_encode_lsp_message(msg) for msg in messages)
        try:
            proc = subprocess.Popen(  # nosec B603
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(workspace_root),
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"LSP binary bulunamadı: {command[0]}. "
                f"Kurulum/doğrulama komutu: {self._lsp_install_hint(language_id)}"
            ) from exc
        try:
            stdout, stderr = proc.communicate(payload, timeout=self.lsp_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            raise RuntimeError("LSP isteği zaman aşımına uğradı.") from exc

        if proc.returncode not in (0, None):
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            # uv / uvx wrapper'ı dahili binary'yi bulamadıysa returncode != 0 ile döner;
            # bu durumu generic RuntimeError yerine FileNotFoundError olarak yükselt ki
            # üst katman (lsp_semantic_audit) "lsp-unavailable" statüsüyle eli boş çıkmasın.
            wrapper_was_used = command[0].endswith(("uv", "uvx")) or len(command) > 1
            if wrapper_was_used and self._lsp_stderr_indicates_missing_binary(stderr_text):
                hint = self._lsp_install_hint(language_id)
                raise FileNotFoundError(
                    f"LSP binary bulunamadı: {self._lsp_target_binary(command, language_id)}. "
                    f"Kurulum/doğrulama komutu: {hint}\n"
                    f"Detay: {stderr_text}"
                )
            raise RuntimeError(
                stderr_text or f"LSP sunucusu hata kodu ile sonlandı: {proc.returncode}"
            )

        return _decode_lsp_stream(stdout)

    @staticmethod
    def _extract_lsp_result(
        messages: list[dict[str, Any]], request_id: int = 2
    ) -> tuple[Any, list[dict[str, Any]]]:
        result = None
        notifications: list[dict[str, Any]] = []
        for message in messages:
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(str(message["error"]))
                result = message.get("result")
            elif "method" in message:
                notifications.append(message)
        return result, notifications

    @staticmethod
    def _format_lsp_locations(locations: Any, limit: int) -> str:
        if not locations:
            return "Sonuç bulunamadı."

        normalized: list[dict[str, Any]] = []
        for item in locations:
            if "targetUri" in item:
                normalized.append(
                    {
                        "uri": item["targetUri"],
                        "range": item.get("targetSelectionRange") or item.get("targetRange") or {},
                    }
                )
            else:
                normalized.append(item)

        lines = []
        for entry in normalized[:limit]:
            uri = entry.get("uri", "")
            rng = entry.get("range", {})
            start = rng.get("start", {})
            path = _file_uri_to_path(uri)
            line_no = int(start.get("line", 0)) + 1
            column_no = int(start.get("character", 0)) + 1
            lines.append(f"- {path}: satır {line_no}, sütun {column_no}")
        if len(normalized) > limit:
            lines.append(f"... ve {len(normalized) - limit} ek sonuç daha.")
        return "\n".join(lines)

    @staticmethod
    def _position_params(path: Path, line: int, character: int) -> dict[str, Any]:
        return {
            "textDocument": {"uri": _path_to_file_uri(path)},
            "position": {"line": line, "character": character},
        }

    def lsp_go_to_definition(self, path: str, line: int, character: int) -> tuple[bool, str]:
        """LSP üzerinden sembol tanımına gider."""
        target = self._normalize_lsp_path(path)
        try:
            messages = self._run_lsp_sequence(
                primary_path=target,
                request_method="textDocument/definition",
                request_params=self._position_params(target, line, character),
            )
            result, _ = self._extract_lsp_result(messages)
            return True, self._format_lsp_locations(
                result if isinstance(result, list) else [result], limit=20
            )
        except Exception as exc:
            return False, f"LSP tanım sorgusu hatası: {exc}"

    def lsp_find_references(
        self,
        path: str,
        line: int,
        character: int,
        include_declaration: bool = True,
    ) -> tuple[bool, str]:
        """LSP üzerinden tüm referansları listeler."""
        target = self._normalize_lsp_path(path)
        try:
            params = self._position_params(target, line, character)
            params["context"] = {"includeDeclaration": include_declaration}
            messages = self._run_lsp_sequence(
                primary_path=target,
                request_method="textDocument/references",
                request_params=params,
            )
            result, _ = self._extract_lsp_result(messages)
            return True, self._format_lsp_locations(result or [], limit=self.lsp_max_references)
        except Exception as exc:
            return False, f"LSP referans sorgusu hatası: {exc}"

    def _apply_workspace_edit(self, edit: dict[str, Any]) -> tuple[bool, str]:
        changes: dict[str, list[dict[str, Any]]] = {}
        for uri, items in (edit.get("changes") or {}).items():
            changes[uri] = list(items or [])

        for doc_change in edit.get("documentChanges") or []:
            text_document = doc_change.get("textDocument") or {}
            uri = text_document.get("uri")
            edits = doc_change.get("edits") or []
            if uri:
                changes.setdefault(uri, []).extend(edits)

        if not changes:
            return False, "Workspace edit boş döndü."

        changed_files = 0
        for uri, edits in changes.items():
            target = _file_uri_to_path(uri)
            if not self.security.can_write(str(target)):
                return False, f"[OpenClaw] LSP rename yazma yetkisi yok: {target}"

            content = Path(str(target)).read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines(keepends=True)
            line_offsets = [0]
            running_offset = 0
            for part in lines:
                running_offset += len(part)
                line_offsets.append(running_offset)

            def _offset(line_no: int, char_no: int, *, _offsets: list[int] = line_offsets) -> int:
                capped_line = max(0, min(line_no, len(_offsets) - 1))
                return _offsets[capped_line] + char_no

            ordered_edits = sorted(
                edits,
                key=lambda item: (
                    int(item.get("range", {}).get("start", {}).get("line", 0)),
                    int(item.get("range", {}).get("start", {}).get("character", 0)),
                ),
                reverse=True,
            )
            for item in ordered_edits:
                rng = item.get("range", {})
                start = rng.get("start", {})
                end = rng.get("end", {})
                start_offset = _offset(int(start.get("line", 0)), int(start.get("character", 0)))
                end_offset = _offset(int(end.get("line", 0)), int(end.get("character", 0)))
                new_text = str(item.get("newText", ""))
                content = content[:start_offset] + new_text + content[end_offset:]

            ok, msg = self.write_file(str(target), content, validate=target.suffix == ".py")
            if not ok:
                return False, msg
            changed_files += 1

        return True, f"LSP workspace edit uygulandı. Değişen dosya sayısı: {changed_files}"

    def lsp_rename_symbol(
        self,
        path: str,
        line: int,
        character: int,
        new_name: str,
        apply: bool = False,
    ) -> tuple[bool, str]:
        """LSP rename işlemini dry-run veya apply modunda yürütür."""
        if not new_name.strip():
            return False, "Yeni sembol adı boş olamaz."

        target = self._normalize_lsp_path(path)
        try:
            workspace_files = [
                candidate
                for candidate in self.base_dir.rglob("*")
                if candidate.is_file()
                and self._detect_language_id(candidate) == self._detect_language_id(target)
            ]
            messages = self._run_lsp_sequence(
                primary_path=target,
                request_method="textDocument/rename",
                request_params={
                    **self._position_params(target, line, character),
                    "newName": new_name,
                },
                extra_open_files=workspace_files[:200],
            )
            result, _ = self._extract_lsp_result(messages)
            if not result:
                return False, "LSP rename değişiklik üretmedi."

            changes = result.get("changes") or {}
            affected_files = len(changes) + len(result.get("documentChanges") or [])
            if not apply:
                return True, (
                    f"LSP rename dry-run hazır. Yeni ad: {new_name}. "
                    f"Etkilenen dosya sayısı: {affected_files}."
                )
            return self._apply_workspace_edit(result)
        except Exception as exc:
            return False, f"LSP rename hatası: {exc}"

    @staticmethod
    def _summarize_lsp_diagnostic_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Ham diagnostic girişlerini kalite kapısı için özetler."""
        severity_counts: dict[int, int] = {}
        for item in entries:
            try:
                severity = int(item.get("severity", 0) or 0)
            except (TypeError, ValueError):
                severity = 0
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

        errors = severity_counts.get(1, 0)
        warnings = severity_counts.get(2, 0)
        infos = severity_counts.get(3, 0) + severity_counts.get(4, 0)
        total = len(entries)

        if errors:
            risk = "yüksek"
            decision = "REJECT"
            status = "issues-found"
        elif warnings:
            risk = "orta"
            decision = "APPROVE"
            status = "issues-found"
        elif total:
            risk = "düşük"
            decision = "APPROVE"
            status = "info-only"
        else:
            risk = "düşük"
            decision = "APPROVE"
            status = "clean"

        summary = (
            "LSP diagnostics temiz."
            if total == 0
            else (
                f"LSP semantik denetimi {total} bulgu üretti"
                f" (error={errors}, warning={warnings}, info={infos})."
            )
        )
        return {
            "status": status,
            "risk": risk,
            "decision": decision,
            "counts": severity_counts,
            "total": total,
            "summary": summary,
        }

    def lsp_semantic_audit(self, paths: list[str] | None = None) -> tuple[bool, dict[str, Any]]:
        """Reviewer kalite kapısı için yapılandırılmış LSP semantik denetim raporu üretir."""
        candidate_paths: list[Path]
        if paths:
            normalized_paths = [self._normalize_lsp_path(p) for p in paths]
            candidate_paths = [
                path
                for path in normalized_paths
                if path.is_file() and self._detect_language_id(path) in {"python", "typescript"}
            ][:100]
        else:
            candidate_paths = [
                path
                for path in self.base_dir.rglob("*")
                if path.is_file() and self._detect_language_id(path) in {"python", "typescript"}
            ][:100]

        if not candidate_paths:
            return False, {
                "status": "no-targets",
                "risk": "orta",
                "decision": "APPROVE",
                "counts": {},
                "issues": [],
                "scanned_paths": [],
                "summary": "LSP tanılaması için uygun dosya bulunamadı.",
            }

        primary = candidate_paths[0]
        try:
            messages = self._run_lsp_sequence(
                primary_path=primary,
                request_method=None,
                extra_open_files=candidate_paths,
            )
            _, notifications = self._extract_lsp_result(messages, request_id=-1)
            diagnostics = [
                item
                for item in notifications
                if item.get("method") == "textDocument/publishDiagnostics"
            ]
            if not diagnostics:
                return True, {
                    "status": "no-signal",
                    "risk": "orta",
                    "decision": "APPROVE",
                    "counts": {},
                    "issues": [],
                    "scanned_paths": [str(path) for path in candidate_paths],
                    "summary": "LSP diagnostics bildirimi dönmedi.",
                }

            issues: list[dict[str, Any]] = []
            for item in diagnostics:
                params = item.get("params", {})
                path = _file_uri_to_path(params.get("uri", "file:///unknown"))
                for diag in params.get("diagnostics", []):
                    start = (diag.get("range") or {}).get("start", {})
                    issues.append(
                        {
                            "path": str(path),
                            "line": int(start.get("line", 0)) + 1,
                            "character": int(start.get("character", 0)) + 1,
                            "severity": int(diag.get("severity", 0) or 0),
                            "message": str(diag.get("message", "")).strip(),
                        }
                    )

            summary = self._summarize_lsp_diagnostic_entries(issues)
            return True, {
                **summary,
                "issues": issues,
                "scanned_paths": [str(path) for path in candidate_paths],
            }
        except FileNotFoundError as exc:
            return False, {
                "status": "lsp-unavailable",
                "risk": "düşük",
                "decision": "APPROVE",
                "counts": {},
                "issues": [],
                "scanned_paths": [str(path) for path in candidate_paths],
                "summary": (f"LSP sunucusu kurulu değil; semantik denetim atlandı. {exc}"),
            }
        except Exception as exc:
            return False, {
                "status": "tool-error",
                "risk": "orta",
                "decision": "APPROVE",
                "counts": {},
                "issues": [],
                "scanned_paths": [str(path) for path in candidate_paths],
                "summary": f"LSP diagnostics hatası: {exc}",
            }

    def lsp_workspace_diagnostics(self, paths: list[str] | None = None) -> tuple[bool, str]:
        """Açılan dosyalar için publishDiagnostics bildirimlerini toplar."""
        ok, audit = self.lsp_semantic_audit(paths)
        issues = list(audit.get("issues", []) or [])
        if issues:
            lines = [
                f"- {item['path']}: satır {item['line']}, sütun {item['character']} | "
                f"severity={item['severity']} | {item['message']}"
                for item in issues
            ]
            return ok, "\n".join(lines)
        return ok, str(audit.get("summary", "") or "LSP diagnostics temiz.")

    # ─────────────────────────────────────────────
    #  KOD DENETİMİ
    # ─────────────────────────────────────────────

    def audit_project(
        self,
        root: str = ".",
        exclude_dirs: list[str] | None = None,
        max_files: int = 5000,
    ) -> str:
        with self._lock:
            self._audits_done += 1

        target = Path(root).resolve()
        if exclude_dirs is None:
            exclude_dirs = [".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"]
        exclude_set = {name.strip() for name in exclude_dirs if name and name.strip()}

        py_files: list[Path] = []
        for cur_root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in exclude_set]
            for file_name in files:
                if not file_name.endswith(".py"):
                    continue
                py_files.append(Path(cur_root) / file_name)
                if len(py_files) >= max_files:
                    break
            if len(py_files) >= max_files:
                break

        errors: list[str] = []
        ok_count = 0

        for fp in py_files:
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                ok, msg = self.validate_python_syntax(content)
                if ok:
                    ok_count += 1
                else:
                    errors.append(f"  {fp.relative_to(target)}: {msg}")
            except Exception as exc:
                errors.append(f"  {fp}: Okunamadı — {exc}")

        report_lines = [
            f"[Sidar Denetim Raporu] — {root}",
            f"  Toplam Python dosyası : {len(py_files)}",
            f"  Geçerli             : {ok_count}",
            f"  Hatalı              : {len(errors)}",
        ]
        if len(py_files) >= max_files:
            report_lines.append(
                f"  Uyarı               : Dosya limiti nedeniyle ilk {max_files} dosya tarandı"
            )
        if errors:
            report_lines.append("\n  Hatalar:")
            report_lines.extend(errors)
        else:
            report_lines.append("  Tüm dosyalar sözdizimi açısından temiz. ✓")

        return "\n".join(report_lines)

    # ─────────────────────────────────────────────
    #  METRİKLER
    # ─────────────────────────────────────────────

    def get_metrics(self) -> dict[str, int]:
        with self._lock:
            return {
                "files_read": self._files_read,
                "files_written": self._files_written,
                "syntax_checks": self._syntax_checks,
                "audits_done": self._audits_done,
            }

    def status(self) -> str:
        """Docker ve sandbox durumunu özetleyen durum satırı döndürür."""
        lsp_status = "LSP on" if self.enable_lsp else "LSP off"
        if self.docker_available:
            return f"CodeManager: Docker Sandbox Aktif (imaj: {self.docker_image}) | {lsp_status}"
        return (
            "CodeManager: Subprocess Modu (Docker erişilemez — kod yerel Python ile çalışır)"
            f" | {lsp_status}"
        )

    def __repr__(self) -> str:
        m = self.get_metrics()
        return (
            f"<CodeManager reads={m['files_read']} "
            f"writes={m['files_written']} "
            f"checks={m['syntax_checks']} "
            f"docker={'on' if self.docker_available else 'off'}>"
        )
