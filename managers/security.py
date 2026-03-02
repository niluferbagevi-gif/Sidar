
"""
Sidar Project - Güvenlik Yöneticisi
OpenClaw erişim kontrol sistemi.
Sürüm: 2.6.1
"""

import logging
import re
from pathlib import Path
from typing import Optional

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
_DANGEROUS_PATH_RE = re.compile(r"\.\.[/\\]|^/etc/|^/proc/|^/sys/", re.IGNORECASE)


class SecurityManager:
    """
    OpenClaw erişim kontrol sistemi.
    Sidar'ın dosya/sistem işlemlerine yetki verir veya reddeder.

    Güvenlik katmanları:
      1. Erişim seviyesi kontrolü (RESTRICTED / SANDBOX / FULL)
      2. Yol geçişi (path traversal) koruması — "../" dizileri ve tehlikeli sistem yolları
      3. Sembolik bağlantı (symlink) koruması — resolve() ile gerçek yol doğrulama
    """

    def __init__(self, access_level: str, base_dir: Path) -> None:
        self.level: int = LEVEL_NAMES.get(access_level.lower(), SANDBOX)
        self.level_name: str = access_level.lower()
        self.base_dir: Path = base_dir.resolve()
        self.temp_dir: Path = (base_dir / "temp").resolve()
        self.temp_dir.mkdir(exist_ok=True)
        logger.info("SecurityManager başlatıldı — seviye: %s (%d)", self.level_name, self.level)

    # ─────────────────────────────────────────────
    #  YARDIMCI — YOL GÜVENLİĞİ
    # ─────────────────────────────────────────────

    @staticmethod
    def _has_dangerous_pattern(path_str: str) -> bool:
        """
        Ham yol dizesinde path traversal veya kritik sistem yolu kalıplarını arar.

        Returns:
            True → tehlikeli kalıp bulundu (yol reddedilmeli)
        """
        return bool(_DANGEROUS_PATH_RE.search(path_str))

    @staticmethod
    def _resolve_safe(path_str: str) -> Optional[Path]:
        """
        Yolu güvenle çözümler. Hata durumunda None döndürür.

        Sembolik bağlantılar resolve() ile takip edilir; gerçek hedef döner.
        Bu sayede symlink traversal saldırıları da yakalanır.

        Returns:
            Çözümlenmiş Path veya None (çözümleme başarısız)
        """
        try:
            return Path(path_str).resolve()
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

    # ─────────────────────────────────────────────
    #  OKUMA YETKİSİ
    # ─────────────────────────────────────────────

    def can_read(self, path: Optional[str] = None) -> bool:
        """
        Her erişim seviyesinde okuma serbesttir.

        Args:
            path: Kontrol edilecek yol (ileride yol bazlı ACL için ayrılmıştır;
                  şu an kullanılmamaktadır — tehlikeli kalıp yoksa True döner).
        """
        if path and self._has_dangerous_pattern(path):
            logger.warning("SecurityManager: okuma — tehlikeli yol reddedildi: %s", path)
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

        # Tehlikeli kalıp erken ret
        if self._has_dangerous_pattern(path):
            logger.warning("SecurityManager: yazma — path traversal reddedildi: %s", path)
            return False

        resolved = self._resolve_safe(path)
        if resolved is None:
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
 