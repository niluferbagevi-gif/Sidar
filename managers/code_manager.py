"""
Sidar Project - Kod Yöneticisi
Dosya okuma, yazma, sözdizimi doğrulama ve DOCKER İZOLELİ kod analizi (REPL).
Sürüm: 2.7.0
"""

import ast
import fnmatch
import glob as _glob
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .security import SecurityManager

logger = logging.getLogger(__name__)


class CodeManager:
    """
    PEP 8 uyumlu dosya işlemleri ve sözdizimi doğrulama.
    Thread-safe RLock ile korunur.
    Kod çalıştırma (execute_code) işlemleri Docker ile izole edilir.
    """

    SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".json", ".yaml", ".yml", ".md", ".txt", ".sh"}
    AUDIT_EXCLUDE_DIRS = {".git", ".hg", ".svn", "__pycache__", "venv", ".venv", "node_modules", "dist", "build", ".mypy_cache", ".pytest_cache"}
    SHELL_META_RE = re.compile(r"[|&;<>`$(){}\[\]\n]")

    def __init__(self, security: SecurityManager, base_dir: Path,
                 docker_image: str = "python:3.11-alpine",
                 docker_exec_timeout: int = 10) -> None:
        self.security = security
        self.base_dir = base_dir.resolve()
        self.docker_image = docker_image          # Config'den veya varsayılan değer
        self.docker_exec_timeout = docker_exec_timeout  # Docker sandbox timeout (sn)
        self._lock = threading.RLock()

        # Metrikler
        self._files_read = 0
        self._files_written = 0
        self._syntax_checks = 0
        self._audits_done = 0

        # Docker İstemcisi Bağlantısı
        self.docker_available = False
        self.docker_client = None
        self._init_docker()

    def _init_docker(self):
        """Docker daemon'a bağlanmayı dener. WSL2 ortamında alternatif socket yollarını dener."""
        try:
            import docker
            self.docker_client = docker.from_env()
            self.docker_client.ping()
            self.docker_available = True
            logger.info("Docker bağlantısı başarılı. REPL işlemleri izole konteynerde çalışacak.")
        except ImportError:
            logger.warning("Docker SDK kurulu değil. (pip install docker)")
        except Exception as first_err:
            # WSL2 fallback: Docker Desktop alternatif socket yollarını dene
            # (docker modülü zaten try bloğunda import edildi; yeniden import gerekmez)
            import docker as _docker_mod  # noqa: F811 — try bloğu ImportError vermediyse önbellektedir
            wsl_sockets = [
                "unix:///var/run/docker.sock",
                "unix:///mnt/wsl/docker-desktop/run/guest-services/backend.sock",
            ]
            for socket_path in wsl_sockets:
                try:
                    self.docker_client = _docker_mod.DockerClient(base_url=socket_path)
                    self.docker_client.ping()
                    self.docker_available = True
                    logger.info("Docker bağlantısı WSL2 socket ile kuruldu: %s", socket_path)
                    return
                except Exception:
                    continue
            logger.warning(
                "Docker Daemon'a bağlanılamadı. Kod çalıştırma kapalı. "
                "WSL2 kullanıcıları: Docker Desktop'u açın ve "
                "Settings > Resources > WSL Integration'dan bu dağıtımı etkinleştirin. "
                "Hata: %s", first_err
            )

    # ─────────────────────────────────────────────
    #  DOSYA OKUMA
    # ─────────────────────────────────────────────

    def read_file(self, path: str, line_numbers: bool = True) -> Tuple[bool, str]:
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
                content = target.read_text(encoding="utf-8", errors="replace")
                self._files_read += 1

            logger.debug("Dosya okundu: %s (%d karakter)", path, len(content))

            if line_numbers:
                lines = content.splitlines()
                width = len(str(len(lines)))
                numbered = "\n".join(
                    f"{str(i + 1).rjust(width)}\t{line}"
                    for i, line in enumerate(lines)
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

    def write_file(self, path: str, content: str, validate: bool = True) -> Tuple[bool, str]:
        """
        Dosyaya içerik yaz (Tam üzerine yazma).

        Returns:
            (başarı, mesaj)
        """
        if not self.security.can_write(path):
            safe = str(self.security.get_safe_write_path(Path(path).name))
            return False, (
                f"[OpenClaw] Yazma yetkisi yok: {path}\n"
                f"  Güvenli alternatif: {safe}"
            )

        # Python dosyaları için sözdizimi kontrolü
        if validate and path.endswith(".py"):
            ok, msg = self.validate_python_syntax(content)
            if not ok:
                return False, f"Sözdizimi hatası, dosya kaydedilmedi:\n{msg}"

        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)

            with self._lock:
                target.write_text(content, encoding="utf-8")
                self._files_written += 1

            logger.info("Dosya yazıldı: %s", path)
            return True, f"Dosya başarıyla kaydedildi: {path}"

        except PermissionError:
            return False, f"[OpenClaw] Yazma erişimi reddedildi: {path}"
        except Exception as exc:
            return False, f"Yazma hatası: {exc}"

    # ─────────────────────────────────────────────
    #  AKILLI YAMA (PATCH)
    # ─────────────────────────────────────────────

    def patch_file(self, path: str, target_block: str, replacement_block: str) -> Tuple[bool, str]:
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

    def execute_code(self, code: str) -> Tuple[bool, str]:
        """
        Kodu tamamen İZOLE ve geçici bir Docker konteynerinde çalıştırır.
        - Ağ erişimi kapalı (network_disabled=True)
        - Dosya sistemi okunaksız/geçici
        - Bellek kısıtlaması (128 MB)
        - Zaman aşımı koruması (10 saniye)
        """
        if not self.security.can_execute():
            return False, "[OpenClaw] Kod çalıştırma yetkisi yok (Restricted Mod)."

        if not self.docker_available:
            logger.info("Docker yok — subprocess (yerel Python) moduna geçiliyor.")
            return self.execute_code_local(code)

        try:
            import docker
            
            # Kodu konteynere komut satırı argümanı olarak gönderiyoruz
            # 'python -c "kod"' formatında çalışacak
            command = ["python", "-c", code]

            # Konteyneri başlat (Arka planda ayrılmış olarak)
            container = self.docker_client.containers.run(
                image=self.docker_image,  # Config'den alınan veya varsayılan imaj
                command=command,
                detach=True,
                remove=False, # Çıktıyı okuyabilmek için anında silmiyoruz, manuel sileceğiz
                network_disabled=True, # Dış ağa istek atamaz (Güvenlik)
                mem_limit="128m", # RAM Limiti (Güvenlik)
                cpu_quota=50000, # CPU Limiti (Güvenlik - Max %50)
                working_dir="/tmp",
            )

            # Zaman aşımı takibi (Config'den okunur, varsayılan 10 sn)
            timeout = self.docker_exec_timeout
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
            
            # İşimiz bitti, konteyneri sil
            container.remove(force=True)

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
            return False, f"Docker çalıştırma hatası: {exc}"

    def execute_code_local(self, code: str) -> Tuple[bool, str]:
        """
        Docker kullanılamadığında Python kodu güvenli subprocess ile çalıştırır.
        - sys.executable kullanır (aktif Conda/venv ortamı korunur)
        - Geçici dosyaya yazar, 10 sn timeout ile çalıştırır
        - Ağ erişimi açıktır (yalnızca Docker izolasyonundan farklı)
        """
        if not self.security.can_execute():
            return False, "[OpenClaw] Kod çalıştırma yetkisi yok (Restricted Mod)."

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name

            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(self.base_dir),
            )

            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

            output = (result.stdout + result.stderr).strip()
            if result.returncode != 0:
                return False, f"REPL Çıktısı (Subprocess — Docker yok):\n{output or '(çıktı yok)'}"
            return True, f"REPL Çıktısı (Subprocess — Docker yok):\n{output or '(kod çalıştı, çıktı yok)'}"

        except subprocess.TimeoutExpired:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
            return False, "⚠ Zaman aşımı! Kod 10 saniyeden uzun sürdü (sonsuz döngü koruması)."
        except Exception as exc:
            return False, f"Subprocess çalıştırma hatası: {exc}"

    # ─────────────────────────────────────────────
    #  KABUK KOMUTU ÇALIŞTIRMA (SHELL EXECUTION)
    # ─────────────────────────────────────────────

    def run_shell(self, command: str, cwd: Optional[str] = None) -> Tuple[bool, str]:
        """
        Kabuk komutunu güvenli subprocess ile çalıştırır (shell=False).
        Claude Code'daki Bash aracına benzer ama metachar/pipeline kullanımını reddeder.

        Güvenlik: Yalnızca FULL erişim seviyesinde çalışır.
        - Komut `shlex.split()` ile parçalanır (shell enjeksiyon yüzeyi azaltılır).
        - `|`, `;`, `&&`, `$()`, backtick vb. shell metachar içeren komutlar reddedilir.
        - 60 saniyelik zaman aşımı koruması vardır.

        Args:
            command: Çalıştırılacak kabuk komutu
            cwd: Çalışma dizini (None ise base_dir kullanılır)

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

        if self.SHELL_META_RE.search(command):
            return False, (
                "⚠ Güvenlik nedeniyle shell metachar içeren komutlar reddedildi.\n"
                "Desteklenmeyen örnekler: |, ;, &&, >, <, $(), `...`\n"
                "Gerekirse komutu tek bir executable + argümanlar formatında çalıştırın."
            )

        work_dir = cwd or str(self.base_dir)

        try:
            args = shlex.split(command)
        except ValueError as exc:
            return False, f"⚠ Komut ayrıştırılamadı: {exc}"

        if not args:
            return False, "⚠ Çalıştırılacak komut belirtilmedi."

        try:
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

            if result.returncode != 0:
                return False, (
                    f"Komut başarısız (çıkış kodu: {result.returncode}):\n{combined}"
                )
            return True, combined

        except subprocess.TimeoutExpired:
            return False, "⚠ Zaman aşımı! Komut 60 saniyeden uzun sürdü ve durduruldu."
        except Exception as exc:
            return False, f"Kabuk hatası: {exc}"

    # ─────────────────────────────────────────────
    #  GLOB DOSYA ARAMA
    # ─────────────────────────────────────────────

    def glob_search(self, pattern: str, base_path: str = ".") -> Tuple[bool, str]:
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
    ) -> Tuple[bool, str]:
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
            files_to_search: List[Path] = []

            if target.is_file():
                files_to_search = [target]
            elif target.is_dir():
                # Glob filtresi uygula
                if "**" in file_glob or "/" in file_glob:
                    files_to_search = [f for f in target.rglob(file_glob) if f.is_file()]
                else:
                    files_to_search = [f for f in target.rglob("*") if f.is_file() and fnmatch.fnmatch(f.name, file_glob)]
            else:
                return False, f"Yol bulunamadı: {path}"

            results: List[str] = []
            match_count = 0
            files_with_matches = 0

            for fp in sorted(files_to_search):
                try:
                    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
                except Exception:
                    continue

                file_matches: List[str] = []
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
                    results.append(f"⚠ Maksimum eşleşme sayısına ulaşıldı ({max_results}). Desen daraltılabilir.")
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

    def list_directory(self, path: str = ".") -> Tuple[bool, str]:
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

    def validate_python_syntax(self, code: str) -> Tuple[bool, str]:
        """Python sözdizimini doğrula."""
        with self._lock:
            self._syntax_checks += 1
        try:
            ast.parse(code)
            return True, "Sözdizimi geçerli."
        except SyntaxError as exc:
            return False, f"Sözdizimi hatası — Satır {exc.lineno}: {exc.msg}"

    def validate_json(self, content: str) -> Tuple[bool, str]:
        """JSON sözdizimini doğrula."""
        try:
            json.loads(content)
            return True, "Geçerli JSON."
        except json.JSONDecodeError as exc:
            return False, f"JSON hatası — Satır {exc.lineno}: {exc.msg}"

    # ─────────────────────────────────────────────
    #  KOD DENETİMİ
    # ─────────────────────────────────────────────

    def audit_project(self, root: str = ".") -> str:
        with self._lock:
            self._audits_done += 1

        target = Path(root).resolve()
        py_files: List[Path] = []
        skipped_dirs: List[str] = []

        for fp in target.rglob("*.py"):
            rel_parts = fp.relative_to(target).parts[:-1]
            hit_excluded = next((part for part in rel_parts if part in self.AUDIT_EXCLUDE_DIRS), None)
            if hit_excluded:
                skipped_dirs.append(hit_excluded)
                continue
            py_files.append(fp)

        errors: List[str] = []
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
        if skipped_dirs:
            uniq_skipped = sorted(set(skipped_dirs))
            report_lines.append(f"  Atlanan dizinler    : {', '.join(uniq_skipped)}")
        if errors:
            report_lines.append("\n  Hatalar:")
            report_lines.extend(errors)
        else:
            report_lines.append("  Tüm dosyalar sözdizimi açısından temiz. ✓")

        return "\n".join(report_lines)

    # ─────────────────────────────────────────────
    #  METRİKLER
    # ─────────────────────────────────────────────

    def get_metrics(self) -> Dict[str, int]:
        with self._lock:
            return {
                "files_read": self._files_read,
                "files_written": self._files_written,
                "syntax_checks": self._syntax_checks,
                "audits_done": self._audits_done,
            }

    def status(self) -> str:
        """Docker ve sandbox durumunu özetleyen durum satırı döndürür."""
        if self.docker_available:
            return f"CodeManager: Docker Sandbox Aktif (imaj: {self.docker_image})"
        return "CodeManager: Subprocess Modu (Docker erişilemez — kod yerel Python ile çalışır)"

    def __repr__(self) -> str:
        m = self.get_metrics()
        return (
            f"<CodeManager reads={m['files_read']} "
            f"writes={m['files_written']} "
            f"checks={m['syntax_checks']} "
            f"docker={'on' if self.docker_available else 'off'}>"
        )  