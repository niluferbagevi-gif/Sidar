"""
Sidar Project - Kod Yöneticisi
Dosya okuma, yazma, sözdizimi doğrulama ve DOCKER İZOLELİ kod analizi (REPL).
Sürüm: 2.7.0
"""

import ast
import contextlib
import fnmatch
import json
import logging
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path, PosixPath, PureWindowsPath
from typing import Any, cast
from urllib.parse import quote, unquote, urlparse

try:
    from config import SANDBOX_LIMITS, Config
except ImportError:
    from config import Config

    SANDBOX_LIMITS = {}
from .security import SANDBOX, SecurityManager

logger = logging.getLogger(__name__)
_OS_NAME = os.name


class _LSPProtocolError(RuntimeError):
    """Dil sunucusu oturum protokolü bozulduğunda yükseltilir."""


def _path_to_file_uri(path: Path) -> str:
    resolved = path.resolve()
    return f"file://{quote(str(resolved).replace(os.sep, '/'))}"


def _file_uri_to_path(uri: str) -> Path | PureWindowsPath:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Desteklenmeyen URI şeması: {uri}")
    raw_path = unquote(parsed.path)
    if _OS_NAME == "nt":
        normalized_path = raw_path[1:] if raw_path.startswith("/") else raw_path
        drive_path = re.match(r"^[A-Za-z]:[\\/]", normalized_path)
        if drive_path:
            return PureWindowsPath(normalized_path)
        return PureWindowsPath(normalized_path)
    return PosixPath(raw_path)


def _to_int(value: object, default: int) -> int:
    """object tipindeki potansiyel sayısal değerleri güvenle int'e çevirir."""
    try:
        return int(cast("int | float | str | bytes | bytearray", value))
    except (TypeError, ValueError):
        return default


def _encode_lsp_message(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _decode_lsp_stream(raw: bytes) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(raw):
        header_end = raw.find(b"\r\n\r\n", cursor)
        if header_end == -1:
            break
        header_blob = raw[cursor:header_end].decode("ascii", errors="replace")
        headers = {}
        for line in header_blob.split("\r\n"):
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        content_length = int(headers.get("content-length", "0") or 0)
        cursor = header_end + 4
        body = raw[cursor : cursor + content_length]
        if len(body) < content_length:
            raise _LSPProtocolError("Eksik LSP mesaj gövdesi alındı.")
        cursor += content_length
        messages.append(json.loads(body.decode("utf-8")))
    return messages


class CodeManager:
    """
    PEP 8 uyumlu dosya işlemleri ve sözdizimi doğrulama.
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
        self.base_dir = Path(base_dir).resolve()
        self.cfg = cfg or Config()
        self.docker_runtime = str(
            getattr(self.cfg, "DOCKER_RUNTIME", os.getenv("DOCKER_RUNTIME", "")) or ""
        ).strip()
        self.docker_allowed_runtimes = list(
            getattr(self.cfg, "DOCKER_ALLOWED_RUNTIMES", ["", "runc", "runsc", "kata-runtime"])
            or [""]
        )
        self.docker_microvm_mode = (
            str(getattr(self.cfg, "DOCKER_MICROVM_MODE", "off") or "off").strip().lower()
        )
        self.docker_mem_limit = str(
            getattr(self.cfg, "DOCKER_MEM_LIMIT", os.getenv("DOCKER_MEM_LIMIT", "256m")) or "256m"
        ).strip()
        self.docker_network_disabled = bool(
            getattr(
                self.cfg,
                "DOCKER_NETWORK_DISABLED",
                os.getenv("DOCKER_NETWORK_DISABLED", "true").lower() in ("1", "true", "yes", "on"),
            )
        )
        self.docker_nano_cpus = int(
            getattr(self.cfg, "DOCKER_NANO_CPUS", os.getenv("DOCKER_NANO_CPUS", "1000000000"))
            or 1000000000
        )
        self.docker_image: str = str(
            docker_image
            or os.getenv("DOCKER_IMAGE", "")
            or os.getenv("DOCKER_PYTHON_IMAGE", "python:3.11-alpine")
        )
        self.docker_exec_timeout = (
            int(docker_exec_timeout)
            if docker_exec_timeout is not None
            else int(os.getenv("DOCKER_EXEC_TIMEOUT", str(SANDBOX_LIMITS.get("timeout", 10))))
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
        self._init_docker()

    def _resolve_runtime(self) -> str:
        runtime = self.docker_runtime
        if self.docker_microvm_mode in ("gvisor", "runsc") and not runtime:
            runtime = "runsc"
        elif self.docker_microvm_mode in ("kata", "firecracker") and not runtime:
            runtime = "kata-runtime"

        if runtime not in self.docker_allowed_runtimes:
            logger.warning(
                "Docker runtime '%s' izinli listede değil (%s); varsayılan runtime kullanılacak.",
                runtime,
                self.docker_allowed_runtimes,
            )
            return ""
        return runtime

    def _resolve_sandbox_limits(self) -> dict[str, object]:
        """Docker çalıştırma limitlerini normalize eder (cgroups)."""
        limits = dict(SANDBOX_LIMITS)
        cfg = getattr(self, "cfg", None)
        cfg_limits = getattr(cfg, "SANDBOX_LIMITS", {}) or {}
        limits.update(cfg_limits)

        # Bellek limitinde öncelik sırası:
        # 1) instance cfg.SANDBOX_LIMITS['memory']
        # 2) DOCKER_MEM_LIMIT
        # 3) modül/genel SANDBOX_LIMITS['memory']
        memory = str(
            cfg_limits.get("memory") or self.docker_mem_limit or limits.get("memory") or "256m"
        ).strip()
        cpus = str(limits.get("cpus") or "0.5").strip()
        pids_limit = _to_int(limits.get("pids_limit", 64), 64)
        timeout = _to_int(limits.get("timeout", self.docker_exec_timeout or 10), 10)
        network_mode = str(limits.get("network") or "none").strip().lower()

        nano_cpus = self.docker_nano_cpus
        if cpus:  # pragma: no cover
            try:
                cpu_val = float(cpus)
                if cpu_val > 0:
                    nano_cpus = int(cpu_val * 1_000_000_000)
            except (TypeError, ValueError):
                logger.warning(
                    "Geçersiz SANDBOX_LIMITS['cpus'] değeri: %s. DOCKER_NANO_CPUS kullanılacak.",
                    cpus,
                )

        if pids_limit < 1:
            pids_limit = 64
        if timeout < 1:
            timeout = 10

        return {
            "memory": memory,
            "cpus": cpus,
            "nano_cpus": nano_cpus,
            "pids_limit": pids_limit,
            "timeout": timeout,
            "network_mode": network_mode,
        }

    def _build_docker_cli_command(self, code: str, limits: dict[str, object]) -> list[str]:
        """Docker CLI ile sandbox çalıştırma komutunu oluşturur."""
        return [
            "docker",
            "run",
            "--rm",
            f"--memory={limits['memory']}",
            f"--cpus={limits['cpus']}",
            f"--pids-limit={limits['pids_limit']}",
            f"--network={limits['network_mode']}",
            self.docker_image,
            "python",
            "-c",
            code,
        ]

    def _execute_code_with_docker_cli(
        self, code: str, limits: dict[str, object]
    ) -> tuple[bool, str]:
        """Docker SDK başarısız olursa docker CLI ile çalıştırmayı dener."""
        docker_cmd = self._build_docker_cli_command(code, limits)
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=_to_int(limits["timeout"], 10),
            cwd=str(self.base_dir),
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > self.max_output_chars:
            output = output[: self.max_output_chars] + (
                f"\n\n... [ÇIKTI KIRPILDI: Maksimum {self.max_output_chars} karakter sınırı aşıldı] ..."
            )
        if result.returncode != 0:
            return False, f"REPL Hatası (Docker CLI Sandbox):\n{output or '(çıktı yok)'}"
        return True, f"REPL Çıktısı (Docker CLI Sandbox):\n{output or '(kod çalıştı, çıktı yok)'}"

    def _try_wsl_socket_fallback(self, docker_module: Any) -> bool:
        """Docker Desktop/WSL2 socket yollarını deneyerek istemci başlatır."""
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
            except Exception:
                continue
            self.docker_client = candidate
            self.docker_available = True
            logger.info("Docker bağlantısı WSL2 socket ile kuruldu: %s", socket_path)
            return True
        return False

    def _try_docker_cli_fallback(self) -> bool:
        """Docker SDK yoksa CLI üzerinden daemon erişimini doğrular."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(self.base_dir),
            )
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
            return False

        if result.returncode != 0:
            return False

        self.docker_client = None
        self.docker_available = True
        logger.info(
            "Docker SDK bulunamadı ancak docker CLI erişilebilir; CLI fallback etkinleştirildi."
        )
        return True

    def _init_docker(self) -> None:
        """Docker daemon'a bağlanmayı dener. WSL2 ortamında alternatif socket yollarını dener."""
        self.docker_available = False
        self.docker_client = None
        docker_module: Any | None = sys.modules.get("docker")
        try:
            if docker_module is None:
                import docker

                docker_module = docker

            client = docker_module.from_env()
            client.ping()
            self.docker_client = client
            self.docker_available = True
            logger.info("Docker bağlantısı başarılı. REPL işlemleri izole konteynerde çalışacak.")
        except ImportError:
            if docker_module is not None and self._try_wsl_socket_fallback(docker_module):
                return
            if self._try_docker_cli_fallback():
                return
            logger.warning("Docker SDK kurulu değil. (pip install docker)")
        except Exception as first_err:
            # WSL2 fallback: Docker Desktop alternatif socket yollarını dene
            # (docker modülü try bloğunda import edildiyse kullan; yoksa yeniden import dene)
            fallback_module = docker_module
            if fallback_module is None:
                try:
                    import docker as fallback_module  # type: ignore[no-redef]
                except ImportError:
                    fallback_module = None

            if fallback_module is not None and self._try_wsl_socket_fallback(fallback_module):
                return
            # SDK kurulu ama daemon/socket erişimi başarısız olduğunda CLI fallback'e
            # geçmeyiz; bu durum mevcut daemon erişim problemini maskeleyip test/üretim
            # davranışını belirsizleştirebilir. CLI fallback yalnızca SDK yoksa denenir.
            logger.warning(
                "Docker Daemon'a bağlanılamadı. Kod çalıştırma kapalı. "
                "WSL2 kullanıcıları: Docker Desktop'u açın ve "
                "Settings > Resources > WSL Integration'dan bu dağıtımı etkinleştirin. "
                "Hata: %s",
                first_err,
            )

    # ─────────────────────────────────────────────
    #  DOSYA OKUMA
    # ─────────────────────────────────────────────

    def read_file(self, path: str, line_numbers: bool = True) -> tuple[bool, str]:
        """
        Dosya içeriğini oku. Claude Code gibi satır numaralarıyla gösterir.

        Güvenlik: path traversal (../), tehlikeli kalıplar ve sembolik bağlantı
        geçişleri security.can_read() ve base_dir doğrulaması ile engellenir.

        Args:
            path: Okunacak dosya yolu
            line_numbers: True ise her satır başına satır numarası eklenir (cat -n formatı)

        Returns:
            (başarı, içerik_veya_hata_mesajı)
        """
        if not self.security.can_read(path):
            return False, "[OpenClaw] Okuma yetkisi yok veya tehlikeli yol reddedildi."

        try:
            target = Path(path).resolve()
            if not target.exists():
                return False, f"Dosya bulunamadı: {path}"
            if target.is_dir():
                return False, f"Belirtilen yol bir dizin: {path}"

            with self._lock:
                with open(target, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                self._files_read += 1

            logger.debug("Dosya okundu: %s (%d karakter)", path, len(content))

            if line_numbers:
                lines = content.splitlines()
                width = len(str(len(lines)))
                numbered = "\n".join(
                    f"{str(i + 1).rjust(width)}\t{line}" for i, line in enumerate(lines)
                )
                return True, numbered

            return True, content

        except PermissionError:
            return False, f"[OpenClaw] Erişim reddedildi: {path}"
        except Exception as exc:
            return False, f"Okuma hatası: {exc}"

    # ─────────────────────────────────────────────
    #  DOSYA YAZMA
    # ─────────────────────────────────────────────

    def write_file(self, path: str, content: str, validate: bool = True) -> tuple[bool, str]:
        """
        Dosyaya içerik yaz (Tam üzerine yazma).

        Returns:
            (başarı, mesaj)
        """
        if not self.security.can_write(path):
            safe = str(self.security.get_safe_write_path(Path(path).name))
            return False, (f"[OpenClaw] Yazma yetkisi yok: {path}\n  Güvenli alternatif: {safe}")

        # Python dosyaları için sözdizimi kontrolü
        if validate and path.endswith(".py"):
            ok, msg = self.validate_python_syntax(content)
            if not ok:
                return False, f"Sözdizimi hatası, dosya kaydedilmedi:\n{msg}"

        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)

            with self._lock:
                with open(target, "w", encoding="utf-8") as f:
                    f.write(content)
                self._files_written += 1
                self._post_process_written_file(target)

            logger.info("Dosya yazıldı: %s", path)
            return True, f"Dosya başarıyla kaydedildi: {path}"

        except PermissionError:
            return False, f"[OpenClaw] Yazma erişimi reddedildi: {path}"
        except Exception as exc:
            return False, f"Yazma hatası: {exc}"

    @staticmethod
    def _strip_markdown_code_fences(content: str) -> str:
        text = str(content or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):  # pragma: no cover
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def _post_process_written_file(self, target: Path) -> None:
        """Otonom ajanların yazdığı kodu kayıttan sonra normalize eder."""
        if target.suffix != ".py":
            return
        ruff_bin = shutil.which("ruff")
        if not ruff_bin:
            return
        try:
            subprocess.run(
                [ruff_bin, "format", str(target)],
                cwd=str(self.base_dir),
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:  # pragma: no cover
            logger.debug("Post-process ruff format atlandı (%s): %s", target, exc)

    def write_generated_test(
        self,
        path: str,
        content: str,
        *,
        append: bool = True,
    ) -> tuple[bool, str]:
        """Coverage ajanı için üretilen pytest içeriğini güvenli biçimde yazar.

        - Markdown kod çitlerini temizler.
        - Varsayılan olarak mevcut test dosyasına ekleme yapar.
        - Aynı içerik zaten varsa idempotent davranır.
        """
        normalized = self._strip_markdown_code_fences(content)
        if not normalized.strip():
            return False, "Yazılacak pytest içeriği boş."

        target = Path(path)
        if append and target.exists():
            ok, current = self.read_file(str(target), line_numbers=False)
            if not ok:
                return False, current
            if normalized in current:
                return True, f"Test içeriği zaten mevcut: {path}"
            separator = "\n\n" if current.strip() else ""
            return self.write_file(
                str(target), f"{current.rstrip()}{separator}{normalized.rstrip()}\n", validate=True
            )

        return self.write_file(str(target), f"{normalized.rstrip()}\n", validate=True)

    # ─────────────────────────────────────────────
    #  AKILLI YAMA (PATCH)
    # ─────────────────────────────────────────────

    def patch_file(self, path: str, target_block: str, replacement_block: str) -> tuple[bool, str]:
        """
        Dosyadaki belirli bir kod bloğunu yenisiyle değiştirir.
        """
        ok, content = self.read_file(path, line_numbers=False)
        if not ok:
            return False, content

        count = content.count(target_block)

        if count == 0:
            return False, (
                "⚠ Yama uygulanamadı: 'Hedef kod bloğu' dosyada bulunamadı.\n"
                "Lütfen boşluklara ve girintilere (indentation) dikkat ederek, "
                "dosyada var olan kodu birebir kopyaladığından emin ol."
            )

        if count > 1:
            return False, (
                f"⚠ Yama uygulanamadı: Hedef kod bloğu dosyada {count} kez geçiyor.\n"
                "Hangi bloğun değiştirileceği belirsiz. Lütfen daha fazla bağlam (context) ekle."
            )

        new_content = content.replace(target_block, replacement_block)
        return self.write_file(path, new_content, validate=True)

    # ─────────────────────────────────────────────
    #  GÜVENLİ KOD ÇALIŞTIRMA (DOCKER SANDBOX)
    # ─────────────────────────────────────────────

    def execute_code(self, code: str) -> tuple[bool, str]:
        """
        Kodu tamamen İZOLE ve geçici bir Docker konteynerinde çalıştırır.
        - Ağ erişimi kapalı (network_disabled=True)
        - Dosya sistemi okunaksız/geçici
        - Bellek/CPU/PID kotaları (cgroups)
        - Zaman aşımı koruması (configurable)
        """
        if not self.security.can_execute():
            return False, "[OpenClaw] Kod çalıştırma yetkisi yok (Restricted Mod)."

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

            # Kodu konteynere komut satırı argümanı olarak gönderiyoruz
            # 'python -c "kod"' formatında çalışacak
            command = ["python", "-c", code]

            sandbox_limits = self._resolve_sandbox_limits()

            # Konteyneri başlat (Arka planda ayrılmış olarak)
            run_kwargs = {
                "image": self.docker_image,
                "command": command,
                "detach": True,
                "remove": False,
                "working_dir": "/tmp",  # nosec B108 - Docker konteyner içi geçici çalışma dizini.
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
                    f"\n\n... [ÇIKTI KIRPILDI: Maksimum {self.max_output_chars} karakter sınırı aşıldı] ..."
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
        """
        Docker kullanılamadığında Python kodu güvenli subprocess ile çalıştırır.
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
            result = subprocess.run(
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
                    f"\n\n... [ÇIKTI KIRPILDI: Maksimum {self.max_output_chars} karakter sınırı aşıldı] ..."
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

    def run_shell_in_sandbox(
        self,
        command: str,
        cwd: str | None = None,
    ) -> tuple[bool, str]:
        """Kabuk komutunu Docker sandbox içinde shell yetkisine ihtiyaç duymadan çalıştırır."""
        if not self.security.can_execute():
            return False, "[OpenClaw] Sandbox komutu çalıştırma yetkisi yok."

        if not command or not command.strip():
            return False, "⚠ Çalıştırılacak komut belirtilmedi."

        work_dir = Path(cwd or self.base_dir).resolve()
        if not work_dir.exists() or not work_dir.is_dir():
            return False, f"Geçersiz çalışma dizini: {work_dir}"
        if not self.security.is_path_under(str(work_dir), self.base_dir):
            return False, f"[OpenClaw] Sandbox çalışma dizini proje kökü dışında: {work_dir}"

        docker_bin = shutil.which("docker")
        if not docker_bin:
            return False, "Docker CLI bulunamadı; sandbox komutu çalıştırılamadı."

        limits = self._resolve_sandbox_limits()
        docker_cmd = [
            docker_bin,
            "run",
            "--rm",
            f"--memory={limits['memory']}",
            f"--cpus={limits['cpus']}",
            f"--pids-limit={limits['pids_limit']}",
            f"--network={limits['network_mode']}",
            "-v",
            f"{work_dir}:/workspace",
            "-w",
            "/workspace",
        ]

        runtime = self._resolve_runtime()
        if runtime:
            docker_cmd.extend(["--runtime", runtime])

        docker_cmd.extend([self.docker_image, "sh", "-lc", command])

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                    timeout=_to_int(limits["timeout"], 10),
                cwd=str(self.base_dir),
            )
        except FileNotFoundError:
            return False, "Docker CLI bulunamadı; sandbox komutu çalıştırılamadı."
        except subprocess.TimeoutExpired:
            return False, (
                f"⚠ Zaman aşımı! Sandbox komutu {limits['timeout']} saniyeden uzun sürdü ve durduruldu."
            )
        except Exception as exc:
            return False, f"Sandbox komutu hatası: {exc}"

        output_parts = []
        if result.stdout.strip():
            output_parts.append(result.stdout.strip())
        if result.stderr.strip():
            output_parts.append(f"[stderr]\n{result.stderr.strip()}")

        combined = "\n".join(output_parts) if output_parts else "(komut çıktı üretmedi)"
        if len(combined) > self.max_output_chars:
            combined = combined[: self.max_output_chars] + (
                f"\n\n... [ÇIKTI KIRPILDI: Maksimum {self.max_output_chars} karakter sınırı aşıldı] ..."
            )

        if result.returncode != 0:
            return False, f"Sandbox komutu başarısız (çıkış kodu: {result.returncode}):\n{combined}"
        return True, combined

    @staticmethod
    def analyze_pytest_output(output: str) -> dict[str, Any]:
        text = str(output or "")
        findings: list[dict[str, Any]] = []
        coverage_targets: list[dict[str, Any]] = []
        failure_targets: list[dict[str, Any]] = []

        summary_match = re.search(
            r"(?P<failed>\d+)\s+failed|(?P<passed>\d+)\s+passed|(?P<errors>\d+)\s+error",
            text.lower(),
        )
        summary = summary_match.group(0) if summary_match else ""

        coverage_pattern = re.compile(
            r"^(?P<path>[A-Za-z0-9_./\\-]+)\s+(?P<stmts>\d+)\s+(?P<miss>\d+)\s+(?P<cover>\d+)%\s+(?P<missing>.+)$",
            re.MULTILINE,
        )
        for match in coverage_pattern.finditer(text):
            path = match.group("path").strip()
            if path.upper() == "TOTAL" or path.startswith("tests/"):
                continue
            missing = match.group("missing").strip()
            missing_segments = [item.strip() for item in missing.split(",") if item.strip()]
            missing_branches = [item for item in missing_segments if "->" in item]
            missing_lines = [item for item in missing_segments if "->" not in item]
            finding = {
                "finding_type": "missing_coverage",
                "target_path": path,
                "summary": f"Eksik coverage satırları: {missing}",
                "missing_lines": missing,
                "coverage_percent": int(match.group("cover")),
                "missing_line_ranges": missing_lines,
                "missing_branch_arcs": missing_branches,
            }
            coverage_targets.append(finding)
            findings.append(finding)

        failure_pattern = re.compile(
            r"_{3,}\s+(?P<target>[^_\n]+?)\s+_{3,}\n(?P<body>.*?)(?=\n_{3,}|\n=+|\Z)",
            re.DOTALL,
        )
        for match in failure_pattern.finditer(text):
            target = match.group("target").strip()
            body = match.group("body").strip()
            path_match = re.search(r"([A-Za-z0-9_./\\-]+\.py):\d+", body)
            target_path = path_match.group(1) if path_match else ""
            finding = {
                "finding_type": "test_failure",
                "target_path": target_path,
                "summary": target,
                "details": body[:1000],
            }
            failure_targets.append(finding)
            findings.append(finding)

        if not failure_targets and re.search(r"\b\d+\s+failed\b", text.lower()):
            path_match = re.search(r"([A-Za-z0-9_./\\-]+\.py):\d+", text)
            failure_targets.append(
                {
                    "finding_type": "test_failure",
                    "target_path": path_match.group(1) if path_match else "",
                    "summary": "pytest failure detected",
                    "details": text[:1000],
                }
            )
            findings.append(failure_targets[-1])

        return {
            "summary": summary,
            "findings": findings,
            "coverage_targets": coverage_targets,
            "failure_targets": failure_targets,
            "has_failures": bool(failure_targets),
            "has_coverage_gaps": bool(coverage_targets),
        }

    def run_pytest_and_collect(
        self,
        command: str = "pytest -q",
        cwd: str | None = None,
    ) -> dict[str, Any]:
        normalized = (command or "").strip() or "pytest -q"
        if "pytest" not in normalized:
            return {
                "success": False,
                "command": normalized,
                "output": "Yalnızca pytest komutları desteklenir.",
                "analysis": self.analyze_pytest_output(""),
            }

        ok, output = self.run_shell_in_sandbox(normalized, cwd=cwd)
        return {
            "success": ok,
            "command": normalized,
            "output": output,
            "analysis": self.analyze_pytest_output(output),
        }

    def run_shell(
        self,
        command: str,
        cwd: str | None = None,
        allow_shell_features: bool = False,
    ) -> tuple[bool, str]:
        """
        Kabuk komutunu güvenli subprocess ile çalıştırır.
        Claude Code'daki Bash aracına eşdeğer.

        Güvenlik: Yalnızca FULL erişim seviyesinde çalışır.
        - Varsayılan modda `shell=False` ve `shlex.split(...)` kullanır.
        - Pipe/redirect gibi shell operatörleri için `allow_shell_features=True` gerekir.
        - 60 saniyelik zaman aşımı koruması vardır.

        Args:
            command: Çalıştırılacak komut
            cwd: Çalışma dizini (None ise base_dir kullanılır)
            allow_shell_features: True ise shell operatörleri (|, >, &&, vb.) aktif edilir.

        Returns:
            (başarı, çıktı_veya_hata)
        """
        if not self.security.can_run_shell():
            return False, (
                "[OpenClaw] Kabuk komutu çalıştırma yetkisi yok.\n"
                "Shell erişimi yalnızca ACCESS_LEVEL=full modunda aktiftir.\n"
                "Değiştirmek için: .env → ACCESS_LEVEL=full"
            )

        if not command or not command.strip():
            return False, "⚠ Çalıştırılacak komut belirtilmedi."

        work_dir = cwd or str(self.base_dir)

        shell_meta_chars = ("|", "&", ";", ">", "<", "$(", "`")
        uses_shell_features = any(token in command for token in shell_meta_chars)
        if uses_shell_features and not allow_shell_features:
            return False, (
                "⚠ Komut shell operatörleri içeriyor (|, >, &&, vb.).\n"
                "Güvenlik için varsayılan modda bu operatörler kapalıdır.\n"
                "Gerekliyse allow_shell_features=True ile tekrar deneyin."
            )

        # allow_shell_features=True yolunda yıkıcı komut kalıplarını engelle
        _BLOCKED_SHELL_PATTERNS = (
            "rm -rf /",
            "rm -fr /",
            ":(){ :|:& };",
            "> /dev/sda",
            "dd if=/dev/zero of=/dev/",
            "mkfs",
            "chmod -R 777 /",
            "chown -R root /",
            "> /etc/passwd",
            "> /etc/shadow",
            "shred /dev/",
            "wipefs /dev/",
        )
        if allow_shell_features:
            cmd_lower = command.lower()
            for _pat in _BLOCKED_SHELL_PATTERNS:
                if _pat in cmd_lower:
                    return False, (
                        f"⛔ Engellendi: tehlikeli kabuk komutu kalıbı algılandı ({_pat!r}). "
                        "Bu işlem yıkıcı olabilir ve izin verilmemektedir."
                    )

        try:
            if allow_shell_features:
                # Güvenlik uyarısı: shell=True ile komut yorumlanıyor, injection riski mevcut.
                # Bu mod yalnızca FULL seviyede ve güvenilir kaynaklardan gelen komutlar için kullanılmalıdır.
                logger.warning(
                    "[GÜVENLİK] Shell özellikleri etkin (shell=True). "
                    "Komut pipe/redirect/subshell içerebilir — yalnızca güvenilir kaynaklardan çalıştırılmalıdır. "
                    "Komut (ilk 200 kar): %.200s",
                    command,
                )
                result = subprocess.run(
                    command,
                    shell=True,  # nosec B602 - FULL modda bilerek shell özellikleri (pipe/redirection) için etkin.
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=work_dir,
                    env={**os.environ},
                )
            else:
                args = shlex.split(command)
                result = subprocess.run(
                    args,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=work_dir,
                    env={**os.environ},
                )
            output_parts = []
            if result.stdout.strip():
                output_parts.append(result.stdout.strip())
            if result.stderr.strip():
                output_parts.append(f"[stderr]\n{result.stderr.strip()}")

            combined = "\n".join(output_parts) if output_parts else "(komut çıktı üretmedi)"

            # Çıktı Boyutu Limiti (Güvenlik)
            if len(combined) > self.max_output_chars:
                combined = combined[: self.max_output_chars] + (
                    f"\n\n... [ÇIKTI KIRPILDI: Maksimum {self.max_output_chars} karakter sınırı aşıldı] ..."
                )

            if result.returncode != 0:
                return False, (f"Komut başarısız (çıkış kodu: {result.returncode}):\n{combined}")
            return True, combined

        except ValueError as exc:
            return False, f"Komut ayrıştırılamadı: {exc}"
        except subprocess.TimeoutExpired:
            return False, "⚠ Zaman aşımı! Komut 60 saniyeden uzun sürdü ve durduruldu."
        except Exception as exc:
            return False, f"Kabuk hatası: {exc}"

    # ─────────────────────────────────────────────
    #  GLOB DOSYA ARAMA
    # ─────────────────────────────────────────────

    def glob_search(self, pattern: str, base_path: str = ".") -> tuple[bool, str]:
        """
        Glob deseni ile dosya ara. Claude Code'daki Glob aracına eşdeğer.

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
        if not pattern:
            return False, "⚠ Glob deseni belirtilmedi."

        try:
            base = Path(base_path).resolve()
            if not base.exists():
                return False, f"Dizin bulunamadı: {base_path}"

            # pathlib.rglob ile desenin ** kısmını işle
            if "**" in pattern:
                parts = pattern.split("**", 1)
                sub = parts[1].lstrip("/\\")
                matches = list(base.rglob(sub))
            else:
                matches = list(base.glob(pattern))

            # Güvenlik: base_dir dışına çıkma (sadece okuma ama yine de kısıtla)
            safe_matches = []
            for m in matches:
                try:
                    m.resolve().relative_to(base)
                    safe_matches.append(m)
                except ValueError:
                    pass

            # Dizin/dosya ayırt ederek listele, değişiklik zamanına göre sırala
            safe_matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            if not safe_matches:
                return True, f"Eşleşen dosya bulunamadı: `{pattern}` ({base_path})"

            lines = [f"Glob sonuçları — `{pattern}` ({len(safe_matches)} eşleşme):"]
            for m in safe_matches:
                rel = m.relative_to(base)
                tag = "📂" if m.is_dir() else "📄"
                lines.append(f"  {tag} {rel}")

            return True, "\n".join(lines)

        except Exception as exc:
            return False, f"Glob arama hatası: {exc}"

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
        """
        Regex ile dosya içeriği ara. Claude Code'daki Grep aracına eşdeğer.

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
        if not pattern:
            return False, "⚠ Arama kalıbı belirtilmedi."

        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            return False, f"Geçersiz regex kalıbı: {exc}"

        try:
            target = Path(path).resolve()
            files_to_search: list[Path] = []

            if target.is_file():
                files_to_search = [target]
            elif target.is_dir():
                # Glob filtresi uygula
                if "**" in file_glob or "/" in file_glob:
                    files_to_search = [f for f in target.rglob(file_glob) if f.is_file()]
                else:
                    files_to_search = [
                        f
                        for f in target.rglob("*")
                        if f.is_file() and fnmatch.fnmatch(f.name, file_glob)
                    ]
            else:
                return False, f"Yol bulunamadı: {path}"

            results: list[str] = []
            match_count = 0
            files_with_matches = 0

            for fp in sorted(files_to_search):
                try:
                    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
                except Exception:
                    continue

                file_matches: list[str] = []
                for i, line in enumerate(lines):
                    if compiled.search(line):
                        if match_count >= max_results:
                            break
                        match_count += 1

                        # Bağlam satırları
                        start = max(0, i - context_lines)
                        end = min(len(lines), i + context_lines + 1)
                        ctx_lines = []
                        for j in range(start, end):
                            prefix = ">" if j == i else " "
                            ctx_lines.append(f"  {prefix} {j + 1:4d}: {lines[j]}")
                        file_matches.append("\n".join(ctx_lines))

                if file_matches:
                    files_with_matches += 1
                    try:
                        rel = fp.relative_to(target if target.is_dir() else target.parent)
                    except ValueError:
                        rel = fp
                    results.append(f"📄 {rel}")
                    results.extend(file_matches)
                    results.append("")

                if match_count >= max_results:
                    results.append(
                        f"⚠ Maksimum eşleşme sayısına ulaşıldı ({max_results}). Desen daraltılabilir."
                    )
                    break

            if not results:
                return True, f"Eşleşme bulunamadı: `{pattern}` ({path}, filtre: {file_glob})"

            header = (
                f"Grep sonuçları — `{pattern}`\n"
                f"  {files_with_matches} dosyada {match_count} eşleşme"
            )
            return True, header + "\n\n" + "\n".join(results)

        except Exception as exc:
            return False, f"Grep arama hatası: {exc}"

    # ─────────────────────────────────────────────
    #  DİZİN LİSTELEME
    # ─────────────────────────────────────────────

    def list_directory(self, path: str = ".") -> tuple[bool, str]:
        """Dizin içeriğini listele."""
        try:
            target = Path(path).resolve()
            if not target.exists():
                return False, f"Dizin bulunamadı: {path}"
            if not target.is_dir():
                return False, f"Belirtilen yol bir dizin değil: {path}"

            items = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            lines = [f"📁 {path}/"]
            for item in items:
                if item.is_dir():
                    lines.append(f"  📂 {item.name}/")
                else:
                    size_kb = item.stat().st_size / 1024
                    lines.append(f"  📄 {item.name}  ({size_kb:.1f} KB)")

            return True, "\n".join(lines)

        except Exception as exc:
            return False, f"Dizin listeleme hatası: {exc}"

    # ─────────────────────────────────────────────
    #  SÖZDİZİMİ DOĞRULAMA
    # ─────────────────────────────────────────────

    def validate_python_syntax(self, code: str) -> tuple[bool, str]:
        """Python sözdizimini doğrula."""
        with self._lock:
            self._syntax_checks += 1
        try:
            ast.parse(code)
            return True, "Sözdizimi geçerli."
        except SyntaxError as exc:
            return False, f"Sözdizimi hatası — Satır {exc.lineno}: {exc.msg}"

    def validate_json(self, content: str) -> tuple[bool, str]:
        """JSON sözdizimini doğrula."""
        try:
            json.loads(content)
            return True, "Geçerli JSON."
        except json.JSONDecodeError as exc:
            return False, f"JSON hatası — Satır {exc.lineno}: {exc.msg}"

    # ─────────────────────────────────────────────
    #  LSP (LANGUAGE SERVER PROTOCOL) YARDIMCILARI
    # ─────────────────────────────────────────────

    def _detect_language_id(self, path: Path) -> str | None:
        suffix = path.suffix.lower()
        if suffix == ".py":
            return "python"
        if suffix in {".ts", ".tsx", ".js", ".jsx"}:
            return "typescript"
        return None

    def _resolve_lsp_command(self, language_id: str) -> list[str]:
        if language_id == "python":
            binary = self.python_lsp_server
            args = ["--stdio"]
        elif language_id == "typescript":
            binary = self.typescript_lsp_server
            args = ["--stdio"]
        else:
            raise ValueError(f"LSP desteklenmeyen dil: {language_id}")

        binary_path = shutil.which(binary)
        return [binary_path or binary, *args]

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
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(workspace_root),
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"LSP binary bulunamadı: {command[0]}") from exc
        try:
            stdout, stderr = proc.communicate(payload, timeout=self.lsp_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            raise RuntimeError("LSP isteği zaman aşımına uğradı.") from exc

        if proc.returncode not in (0, None):
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
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
            lines.append(
                f"- {path}: satır {int(start.get('line', 0)) + 1}, sütun {int(start.get('character', 0)) + 1}"
            )
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
            else f"LSP semantik denetimi {total} bulgu üretti (error={errors}, warning={warnings}, info={infos})."
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
        return f"CodeManager: Subprocess Modu (Docker erişilemez — kod yerel Python ile çalışır) | {lsp_status}"

    def __repr__(self) -> str:
        m = self.get_metrics()
        return (
            f"<CodeManager reads={m['files_read']} "
            f"writes={m['files_written']} "
            f"checks={m['syntax_checks']} "
            f"docker={'on' if self.docker_available else 'off'}>"
        )
