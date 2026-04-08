

"""
Sidar Project - Güvenlik Yöneticisi
OpenClaw erişim kontrol sistemi.
Sürüm: 2.7.0
"""

import logging
import re
from pathlib import Path
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)

# Erişim seviyesi sabitleri
RESTRICTED = 0   # Yalnızca okuma, denetim ve analiz
SANDBOX = 1      # Okuma + yalnızca /temp dizinine yazma
FULL = 2         # Tam erişim (terminal dahil)

LEVEL_NAMES = {
    "restricted": RESTRICTED,
    "sandbox": SANDBOX,
    "full": FULL,
}

# Tehlikeli yol kalıpları — path traversal saldırılarına karşı ek koruma
_DANGEROUS_PATH_RE = re.compile(r"\.\.[/\\]|^/etc/|^/proc/|^/sys/|^[a-zA-Z]:[/\\](windows|program files)", re.IGNORECASE)

_BLOCKED_PATTERNS = [
    re.compile(r"(^|[/\\])\.env$", re.IGNORECASE),
    re.compile(r"(^|[/\\])sessions([/\\]|$)", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.git([/\\]|$)", re.IGNORECASE),
    re.compile(r"(^|[/\\])__pycache__([/\\]|$)", re.IGNORECASE),
]


class SecurityManager:
    """
    OpenClaw erişim kontrol sistemi.
    Sidar'ın dosya/sistem işlemlerine yetki verir veya reddeder.

    Güvenlik katmanları:
      1. Erişim seviyesi kontrolü (RESTRICTED / SANDBOX / FULL)
      2. Yol geçişi (path traversal) koruması — "../" dizileri ve tehlikeli sistem yolları
      3. Sembolik bağlantı (symlink) koruması — resolve() ile gerçek yol doğrulama
    """

    def __init__(
        self,
        access_level: Optional[str] = None,
        base_dir: Optional[Path] = None,
        cfg: Optional[Config] = None,
    ) -> None:
        self.cfg = cfg or Config()
        raw_level = access_level if access_level is not None else getattr(self.cfg, "ACCESS_LEVEL", "sandbox")
        raw_base_dir = base_dir if base_dir is not None else getattr(self.cfg, "BASE_DIR", Path("."))

        normalized_level = self._normalize_level_name(raw_level)
        self.level: int = LEVEL_NAMES[normalized_level]
        self.level_name: str = normalized_level
        self.base_dir: Path = Path(raw_base_dir).resolve()
        self.temp_dir: Path = (self.base_dir / "temp").resolve()
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info("SecurityManager başlatıldı — seviye: %s (%d)", self.level_name, self.level)

    # ─────────────────────────────────────────────
    #  YARDIMCI — YOL GÜVENLİĞİ
    # ─────────────────────────────────────────────

    @staticmethod
    def _normalize_level_name(access_level: str) -> str:
        """Bilinmeyen seviyeleri güvenli varsayılan SANDBOX'a normalize eder."""
        level = (access_level or "").strip().lower()
        if level not in LEVEL_NAMES:
            logger.warning(
                "SecurityManager: bilinmeyen access level '%s' — SANDBOX varsayılanı kullanılacak.",
                access_level,
            )
            return "sandbox"
        return level

    @staticmethod
    def _has_dangerous_pattern(path_str: str) -> bool:
        """
        Ham yol dizesinde path traversal veya kritik sistem yolu kalıplarını arar.

        Returns:
            True → tehlikeli kalıp bulundu (yol reddedilmeli)
        """
        return bool(_DANGEROUS_PATH_RE.search(path_str))

    def _resolve_safe(self, path_str: str) -> Optional[Path]:
        """
        Yolu güvenle çözümler. Hata durumunda None döndürür.

        Sembolik bağlantılar resolve() ile takip edilir; gerçek hedef döner.
        Bu sayede symlink traversal saldırıları da yakalanır.

        Returns:
            Çözümlenmiş Path veya None (çözümleme başarısız)
        """
        try:
            candidate = Path(path_str)
            if not candidate.is_absolute():
                candidate = self.base_dir / candidate
            return candidate.resolve()
        except Exception:
            return None

    def is_path_under(self, path_str: str, base: Path) -> bool:
        """
        Verilen yolun base dizini altında olup olmadığını doğrular.
        Sembolik bağlantılar takip edilerek gerçek hedef kontrol edilir.

        Args:
            path_str: Doğrulanacak ham yol dizesi
            base:     İzin verilen kök dizin (önceden resolve() edilmiş olmalı)

        Returns:
            True → yol güvenli ve base altında
        """
        base = base.resolve()
        if self._has_dangerous_pattern(path_str):
            logger.warning("SecurityManager: tehlikeli yol kalıbı reddedildi: %s", path_str)
            return False
        resolved = self._resolve_safe(path_str)
        if resolved is None:
            return False
        try:
            resolved.relative_to(base)
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_blocked_path(path_str: str) -> bool:
        return any(pattern.search(path_str) for pattern in _BLOCKED_PATTERNS)

    def is_safe_path(self, path_str: str) -> bool:
        """Path traversal + base_dir + hassas yol desenleri doğrulaması."""
        try:
            if self._has_dangerous_pattern(path_str):
                return False
            resolved = Path(path_str).resolve()
            resolved_str = str(resolved)
            if self._is_blocked_path(resolved_str):
                return False
            resolved.relative_to(self.base_dir)
            return True
        except Exception:
            return False

    # ─────────────────────────────────────────────
    #  OKUMA YETKİSİ
    # ─────────────────────────────────────────────

    def can_read(self, path: Optional[str] = None) -> bool:
        """Dosyanın okunup okunamayacağını kontrol eder."""
        if not path:
            return True

        if self._has_dangerous_pattern(path):
            logger.warning("SecurityManager: okuma — tehlikeli yol reddedildi: %s", path)
            return False

        resolved = self._resolve_safe(path)
        if resolved is None:
            return False

        if self._is_blocked_path(str(resolved)):
            logger.warning("SecurityManager: okuma — hassas yol reddedildi: %s", path)
            return False

        if not self.is_path_under(str(resolved), self.base_dir):
            logger.warning("SecurityManager: okuma — kök dizin dışı yol reddedildi: %s", resolved)
            return False

        return True

    # ─────────────────────────────────────────────
    #  YAZMA YETKİSİ
    # ─────────────────────────────────────────────

    def can_write(self, path: str) -> bool:
        """
        Yazma iznini kontrol et.
        - RESTRICTED: hiçbir zaman
        - SANDBOX: yalnızca temp/ dizini (symlink korumalı)
        - FULL: base_dir altındaki her yere (symlink + traversal korumalı)

        Returns:
            True → yazma izni var
        """
        if self.level == RESTRICTED:
            return False

        if not path or not path.strip():
            return False

        # Tehlikeli kalıp erken ret
        if self._has_dangerous_pattern(path):
            logger.warning("SecurityManager: yazma — path traversal reddedildi: %s", path)
            return False

        resolved = self._resolve_safe(path)
        if resolved is None:
            return False

        if self._is_blocked_path(str(resolved)):
            logger.warning("SecurityManager: yazma — hassas yol reddedildi: %s", path)
            return False

        if self.level == SANDBOX:
            # SANDBOX: yalnızca temp dizinine — sembolik bağlantı takip edilerek kontrol
            try:
                resolved.relative_to(self.temp_dir)
                return True
            except ValueError:
                return False

        # FULL: base_dir altındaki her yere izin (kritik sistem yolları zaten bloklandı)
        try:
            resolved.relative_to(self.base_dir)
            return True
        except ValueError:
            logger.warning(
                "SecurityManager: FULL modda proje kökü dışına yazma reddedildi: %s", path
            )
            return False

    # ─────────────────────────────────────────────
    #  TERMİNAL YETKİSİ
    # ─────────────────────────────────────────────

    def can_execute(self) -> bool:
        """
        Kod/REPL çalıştırma izni.
        - RESTRICTED : yasak
        - SANDBOX    : izinli (yalnızca /temp üzerinde çalışır)
        - FULL       : izinli (tam erişim)
        """
        return self.level >= SANDBOX

    def can_run_shell(self) -> bool:
        """
        Terminal/Shell komut çalıştırma izni.
        - RESTRICTED : yasak
        - SANDBOX    : yasak (yalnızca Docker izole Python REPL izinli)
        - FULL       : izinli (git, npm, pip vb. tüm kabuk komutları)
        """
        return self.level == FULL

    # ─────────────────────────────────────────────
    #  YARDIMCILAR
    # ─────────────────────────────────────────────

    def get_safe_write_path(self, filename: str) -> Path:
        """Sandbox modunda güvenli yazma yolu döndürür."""
        # Dosya adındaki tehlikeli karakterleri temizle
        safe_name = Path(filename).name  # yalnızca dosya adı bileşeni
        return self.temp_dir / safe_name

    def set_level(self, new_level: str) -> bool:
        """Erişim seviyesini çalışma zamanında değiştirir."""
        normalized = self._normalize_level_name(new_level)
        if normalized == self.level_name:
            return False
        self.level = LEVEL_NAMES[normalized]
        self.level_name = normalized
        logger.info("SecurityManager erişim seviyesi güncellendi -> %s", self.level_name)
        return True

    def status_report(self) -> str:
        """Erişim seviyesi ve izin özetini döndürür."""
        perms = []
        perms.append("Okuma   : ✓ (tehlikeli yol koruması aktif)")
        perms.append(
            f"Yazma   : {'✓ (tam — proje kökü)' if self.level == FULL else ('✓ (yalnızca /temp)' if self.level == SANDBOX else '✗')}"
        )
        perms.append(f"Terminal: {'✓' if self.level >= SANDBOX else '✗'}")
        perms.append(f"Shell   : {'✓ (git, npm, pip vb.)' if self.level == FULL else '✗'}")
        perms.append("Symlink : ✓ korumalı (resolve() ile doğrulama)")
        return (
            f"[OpenClaw] Erişim Seviyesi: {self.level_name.upper()}\n"
            + "\n".join(f"  {p}" for p in perms)
        )

    def __repr__(self) -> str:
        return f"<SecurityManager level={self.level_name}>"
  
