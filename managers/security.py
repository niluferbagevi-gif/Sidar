"""
Sidar Project - Güvenlik Yöneticisi
OpenClaw erişim kontrol sistemi.
Sürüm: 2.7.0
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import Config

logger = logging.getLogger(__name__)

# Erişim seviyesi sabitleri
RESTRICTED = 0  # Yalnızca okuma, denetim ve analiz
SANDBOX = 1  # Okuma + yalnızca /temp dizinine yazma
FULL = 2  # Tam erişim (terminal dahil)

LEVEL_NAMES = {
    "restricted": RESTRICTED,
    "sandbox": SANDBOX,
    "full": FULL,
}

# Tehlikeli yol kalıpları — path traversal saldırılarına karşı ek koruma
_DANGEROUS_PATH_RE = re.compile(
    r"\.\.[/\\]|^/etc/|^/proc/|^/sys/|^[a-zA-Z]:[/\\](windows|program files)", re.IGNORECASE
)

_BLOCKED_PATTERNS = [
    re.compile(r"(^|[/\\])\.env$", re.IGNORECASE),
    re.compile(r"(^|[/\\])sessions([/\\]|$)", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.git([/\\]|$)", re.IGNORECASE),
    re.compile(r"(^|[/\\])__pycache__([/\\]|$)", re.IGNORECASE),
]

_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore (all|any|previous|prior) (instructions|rules|prompts)", re.IGNORECASE),
    re.compile(
        r"(reveal|show|print).*(system prompt|developer message|hidden prompt)", re.IGNORECASE
    ),
    re.compile(r"(jailbreak|bypass|override).*(policy|safety|guardrail|security)", re.IGNORECASE),
    re.compile(r"(do not follow|stop following).*(policy|rules|instructions)", re.IGNORECASE),
    re.compile(r"(act as|pretend to be).*(system|developer|admin)", re.IGNORECASE),
    re.compile(r"(exfiltrate|leak).*(secret|token|credential|api key|password)", re.IGNORECASE),
]

_SUSPICIOUS_OUTPUT_PATTERNS = [
    re.compile(r"(BEGIN|START).*(SYSTEM|DEVELOPER).*(PROMPT|MESSAGE)", re.IGNORECASE),
    re.compile(r"(api[_ -]?key|token|password|secret)\s*[:=]\s*[A-Za-z0-9_\-]{8,}", re.IGNORECASE),
]


@dataclass(frozen=True)
class ValidationResult:
    allowed: bool
    risk_score: int = 0
    reasons: list[str] = field(default_factory=list)
    source: str = "unknown"


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
        access_level: str | None = None,
        base_dir: Path | None = None,
        cfg: Config | None = None,
    ) -> None:
        self.cfg = cfg or Config()
        raw_level = (
            access_level
            if access_level is not None
            else getattr(self.cfg, "ACCESS_LEVEL", "sandbox")
        )
        raw_base_dir = (
            base_dir if base_dir is not None else getattr(self.cfg, "BASE_DIR", Path("."))
        )

        normalized_level = self._normalize_level_name(raw_level)
        self.level: int = LEVEL_NAMES[normalized_level]
        self.level_name: str = normalized_level
        self.base_dir: Path = Path(raw_base_dir).resolve()
        self.temp_dir: Path = (self.base_dir / "temp").resolve()
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.prompt_guard_enabled = bool(getattr(self.cfg, "PROMPT_GUARD_ENABLED", True))
        self._guardrails_engine: Any = None
        if self.prompt_guard_enabled:
            self._init_guardrails()
        logger.info("SecurityManager başlatıldı — seviye: %s (%d)", self.level_name, self.level)

    def _init_guardrails(self) -> None:
        """NeMo Guardrails motorunu başlatır."""
        try:
            from nemoguardrails import LLMRails  # type: ignore
        except Exception as exc:  # pragma: no cover - ortama bağlı import hatası
            logger.warning("NeMo Guardrails başlatılamadı, guardrails devre dışı: %s", exc)
            self._guardrails_engine = None
            return
        self._guardrails_engine = LLMRails

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

    def _resolve_safe(self, path_str: str) -> Path | None:
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

    @staticmethod
    def _scan_prompt_injection_patterns(text: str) -> list[str]:
        findings: list[str] = []
        for pattern in _PROMPT_INJECTION_PATTERNS:
            if pattern.search(text):
                findings.append(pattern.pattern)
        return findings

    @staticmethod
    def _scan_output_leak_patterns(text: str) -> list[str]:
        findings: list[str] = []
        for pattern in _SUSPICIOUS_OUTPUT_PATTERNS:
            if pattern.search(text):
                findings.append(pattern.pattern)
        return findings

    def _run_guardrails_engine(self, text: str, *, source: str) -> list[str]:
        """Guardrails motorunu best-effort çalıştırır; başarısız olursa boş döner."""
        if not self._guardrails_engine:
            return []
        try:
            # Entegrasyon noktası intentionally gevşek tutulur:
            # farklı guardrails engine adaptörleri bu metodu override edebilir.
            checker = getattr(self._guardrails_engine, "validate", None)
            if callable(checker):
                result = checker(text=text, source=source)
                if isinstance(result, dict) and result.get("allowed") is False:
                    reason = str(result.get("reason") or "guardrails_blocked")
                    return [reason]
        except Exception as exc:  # pragma: no cover
            logger.debug("Guardrails motoru çalıştırılamadı (%s): %s", source, exc)
        return []

    def validate_prompt_text(self, text: str, *, source: str = "user") -> ValidationResult:
        """Kullanıcı girdisi / ajan çıktısında prompt injection benzeri riskleri tarar."""
        normalized = str(text or "")
        if not normalized.strip():
            return ValidationResult(allowed=True, risk_score=0, reasons=[], source=source)

        reasons = self._scan_prompt_injection_patterns(normalized)
        output_leak_reasons: list[str] = []
        if source == "agent_output":
            output_leak_reasons = self._scan_output_leak_patterns(normalized)
            reasons.extend(output_leak_reasons)
        reasons.extend(self._run_guardrails_engine(normalized, source=source))

        unique_reasons = sorted(set(reasons))
        risk_score = min(100, len(unique_reasons) * 20)
        has_secret_like_leak = bool(output_leak_reasons)
        allowed = (risk_score < 40) and (not has_secret_like_leak)
        return ValidationResult(
            allowed=allowed, risk_score=risk_score, reasons=unique_reasons, source=source
        )

    def validate_user_input(self, text: str) -> ValidationResult:
        return self.validate_prompt_text(text, source="user")

    def validate_agent_output(self, text: str) -> ValidationResult:
        return self.validate_prompt_text(text, source="agent_output")

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

    def can_read(self, path: str | None = None) -> bool:
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
        return f"[OpenClaw] Erişim Seviyesi: {self.level_name.upper()}\n" + "\n".join(
            f"  {p}" for p in perms
        )

    def __repr__(self) -> str:
        return f"<SecurityManager level={self.level_name}>"
