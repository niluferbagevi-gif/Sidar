"""
Sidar Project — DLP (Data Loss Prevention) & PII Maskeleme Modülü
Hassas verileri LLM API çağrılarından önce maskeler/temizler.

Desteklenen örüntüler:
- API anahtarları / token'lar (Bearer, sk-, ghp_, vb.)
- Şifreler (password=, parola= vb. anahtar=değer biçimler)
- Türkiye TC Kimlik No (11 haneli, algoritma doğrulamalı)
- E-posta adresleri
- Kredi kartı numaraları (Luhn algoritması isteğe bağlı)
- IPv4 / IPv6 adresleri (özel ağ hariç tutulabilir)
- JWT token'ları
- Genel uzun hex/base64 sırları

Kullanım:
    from core.dlp import mask_pii, get_dlp_engine

    safe_text = mask_pii(original_text)
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ─── Yapılandırma sabitleri ────────────────────────────────────────────────────

_DEFAULT_MASK = "[MASKED]"

# ─── Regex örüntüleri ─────────────────────────────────────────────────────────

# Bearer / Authorization token (sadece değer kısmı maskelenir)
_RE_BEARER = re.compile(
    r"(?i)(Authorization\s*[:=]\s*(?:Bearer|Token)\s+)([A-Za-z0-9\-._~+/]{20,})",
    re.MULTILINE,
)

# sk- / sk_live- / sk_test- (OpenAI, Stripe vb.)
_RE_SK_KEY = re.compile(r"\b(sk[-_](?:ant[-_]|proj[-_]|live[-_]|test[-_])?[A-Za-z0-9]{20,})\b")

# GitHub Personal Access Token  (ghp_ / github_pat_)
_RE_GITHUB_TOKEN = re.compile(r"\b(ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})\b")

# AWS Access Key ID
_RE_AWS_KEY = re.compile(r"\b(AKIA[0-9A-Z]{16})\b")

# Generic API Key/Token kv çiftleri  (api_key=... , token=... vb.)
_RE_KV_SECRET = re.compile(
    r"(?i)(?:api[_-]?key|api[_-]?secret|access[_-]?token|secret[_-]?key"
    r"|client[_-]?secret|auth[_-]?token|private[_-]?key)\s*[:=]\s*"
    r"(['\"]?)([A-Za-z0-9\-._~+/!@#$%^&*]{10,})(['\"]?)",
    re.MULTILINE,
)

# Parola kv çiftleri  (password=... , parola=... vb.)
_RE_PASSWORD = re.compile(
    r"(?i)(?:password|parola|passwd|pwd|şifre)\s*[:=]\s*" r"(['\"]?)([^\s,;'\"]{6,})(['\"]?)",
    re.MULTILINE,
)

# TC Kimlik No — 11 haneli, ilk hane ≠ 0
# Sayıların para birimi/ondalık bağlamındaki kullanımını azaltmak için
# nokta/virgül/₺/$ ile komşu değerleri eşleşmeden dışlarız.
_RE_TCKN = re.compile(r"(?<!\d)(?<!\.)([1-9][0-9]{10})(?!\d)(?![\.,₺$])")

# E-posta
_RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# Kredi kartı — 13-19 hane, gruplar arasında boşluk/tire isteğe bağlı
_RE_CREDIT_CARD = re.compile(
    r"\b(?:4[0-9]{12}(?:[0-9]{3,6})?|5[1-5][0-9]{14}"
    r"|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12,15}"
    r"|(?:2131|1800|35\d{3})\d{11})\b"
)

# JWT  (3 base64url bölümü . ile ayrılmış)
_RE_JWT = re.compile(r"\b(ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b")

# IPv4
_RE_IPV4 = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}" r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
)

# IPv6 (sık kullanılan tam/sıkıştırılmış biçimler)
_RE_IPV6 = re.compile(r"\b(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}\b")

# Uzun hex dizisi (64+ karakter) — SHA-1 / kısa commit hash false-positive riskini azaltır
_RE_LONG_HEX = re.compile(r"\b([0-9a-fA-F]{64,})\b")


# ─── TC Kimlik No doğrulama ────────────────────────────────────────────────────


def _is_valid_tckn(value: str) -> bool:
    """Basit TCKN algoritması doğrulaması."""
    if len(value) != 11 or value[0] == "0":
        return False
    try:
        digits = [int(c) for c in value]
    except ValueError:
        return False
    # 10. hane kontrolü
    odd_sum = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
    even_sum = digits[1] + digits[3] + digits[5] + digits[7]
    check10 = (odd_sum * 7 - even_sum) % 10
    if check10 != digits[9]:
        return False
    # 11. hane kontrolü
    if sum(digits[:10]) % 10 != digits[10]:
        return False
    return True


# ─── DLPDetection dataclass ───────────────────────────────────────────────────


@dataclass
class DLPDetection:
    """Tespit edilen tek bir hassas veri bulgusu."""

    pattern_name: str
    start: int
    end: int
    original_value: str  # log için (kısaltılmış)


# ─── Ana maskeleme mantığı ─────────────────────────────────────────────────────


class DLPEngine:
    """
    Yapılandırılabilir PII/hassas veri maskeleme motoru.

    Her örüntü bağımsız olarak açılıp kapatılabilir; bu sayede iş kurallarına
    göre ince ayar yapılabilir. Tüm işlemler bellekte gerçekleşir ve herhangi
    bir dış servis çağrısı yapılmaz.
    """

    def __init__(
        self,
        *,
        mask_bearer: bool = True,
        mask_sk_keys: bool = True,
        mask_github_tokens: bool = True,
        mask_aws_keys: bool = True,
        mask_kv_secrets: bool = True,
        mask_passwords: bool = True,
        mask_tckn: bool = True,
        mask_email: bool = True,
        mask_credit_cards: bool = True,
        mask_ipv4: bool = True,
        mask_ipv6: bool = True,
        mask_jwt: bool = True,
        mask_long_hex: bool = False,  # Varsayılan kapalı — çok sayıda false positive üretir
        replacement: str = _DEFAULT_MASK,
        log_detections: bool = False,
    ) -> None:
        self.mask_bearer = mask_bearer
        self.mask_sk_keys = mask_sk_keys
        self.mask_github_tokens = mask_github_tokens
        self.mask_aws_keys = mask_aws_keys
        self.mask_kv_secrets = mask_kv_secrets
        self.mask_passwords = mask_passwords
        self.mask_tckn = mask_tckn
        self.mask_email = mask_email
        self.mask_credit_cards = mask_credit_cards
        self.mask_ipv4 = mask_ipv4
        self.mask_ipv6 = mask_ipv6
        self.mask_jwt = mask_jwt
        self.mask_long_hex = mask_long_hex
        self.replacement = replacement
        self.log_detections = log_detections

    # ── İç yardımcılar ──────────────────────────────────────────────────────

    def _sub(
        self, pattern: re.Pattern, text: str, group_idx: int = 0, name: str = ""
    ) -> tuple[str, list[DLPDetection]]:
        """
        Örüntü eşleşmesini maskeleme değeriyle değiştirir.
        group_idx=0 → tüm eşleşme, >0 → belirtilen grup.
        """
        detections: list[DLPDetection] = []

        def _replace(m: re.Match) -> str:
            original = m.group(group_idx)
            start, end = m.span(group_idx)
            detections.append(
                DLPDetection(
                    pattern_name=name,
                    start=start,
                    end=end,
                    original_value=original[:8] + "…" if len(original) > 8 else "***",
                )
            )
            if group_idx == 0:
                return self.replacement
            # Prefix/suffix korunur; sadece yakalanan grup değiştirilir
            full = m.group(0)
            gstart, gend = m.span(group_idx)
            offset = m.start()
            return full[: gstart - offset] + self.replacement + full[gend - offset :]

        result = pattern.sub(_replace, text)
        return result, detections

    # ── Ana API ─────────────────────────────────────────────────────────────

    def mask(self, text: str) -> tuple[str, list[DLPDetection]]:
        """
        Metindeki tüm aktif örüntüleri maskeler.

        Returns:
            (masked_text, detections) çifti.
        """
        if not text:
            return text, []

        all_detections: list[DLPDetection] = []

        def _apply(cond: bool, pattern: re.Pattern, group_idx: int, name: str) -> None:
            nonlocal text
            if not cond:
                return
            text, dets = self._sub(pattern, text, group_idx, name)
            all_detections.extend(dets)

        # JWT — diğer örüntülerden önce; ey… prefix'li Base64 imzalı token
        _apply(self.mask_jwt, _RE_JWT, 1, "jwt")

        # API token'ları
        _apply(self.mask_bearer, _RE_BEARER, 2, "bearer_token")
        _apply(self.mask_sk_keys, _RE_SK_KEY, 1, "sk_key")
        _apply(self.mask_github_tokens, _RE_GITHUB_TOKEN, 1, "github_token")
        _apply(self.mask_aws_keys, _RE_AWS_KEY, 1, "aws_access_key")

        # KV çiftleri
        _apply(self.mask_kv_secrets, _RE_KV_SECRET, 2, "kv_secret")
        _apply(self.mask_passwords, _RE_PASSWORD, 2, "password")

        # Kişisel veriler
        if self.mask_tckn:

            def _tckn_replace(m: re.Match) -> str:
                val = m.group(1)
                if _is_valid_tckn(val):
                    all_detections.append(DLPDetection("tckn", m.start(1), m.end(1), val[:3] + "…"))
                    return self.replacement
                return m.group(0)

            text = _RE_TCKN.sub(_tckn_replace, text)

        _apply(self.mask_email, _RE_EMAIL, 0, "email")
        _apply(self.mask_credit_cards, _RE_CREDIT_CARD, 0, "credit_card")
        _apply(self.mask_ipv4, _RE_IPV4, 0, "ipv4")
        _apply(self.mask_ipv6, _RE_IPV6, 0, "ipv6")

        # Uzun hex (varsayılan kapalı)
        _apply(self.mask_long_hex, _RE_LONG_HEX, 1, "long_hex")

        if self.log_detections and all_detections:
            msg = "DLP Maskeleme: %d hassas veri tespit edildi ve maskelendi — %s"
            args = (len(all_detections), ", ".join(d.pattern_name for d in all_detections))
            logger.warning(msg, *args)
            logging.getLogger().warning(msg, *args)

        return text, all_detections

    def mask_messages(self, messages: list[dict]) -> tuple[list[dict], list[DLPDetection]]:
        """
        LLM mesaj listesinin `content` alanlarını maskeler.
        Orijinal listede değişiklik yapmaz; yeni bir liste döndürür.
        """
        result = []
        all_dets: list[DLPDetection] = []
        for msg in messages:
            content = msg.get("content") or ""
            if isinstance(content, str) and content:
                masked, dets = self.mask(content)
                if dets:
                    result.append({**msg, "content": masked})
                    all_dets.extend(dets)
                else:
                    result.append(msg)
            else:
                result.append(msg)
        return result, all_dets


# ─── Singleton ────────────────────────────────────────────────────────────────

_ENGINE: DLPEngine | None = None
_ENGINE_LOCK = threading.Lock()


def _build_engine_from_env() -> DLPEngine:
    enabled = os.getenv("DLP_ENABLED", "true").lower() not in ("0", "false", "no")
    log_dets = os.getenv("DLP_LOG_DETECTIONS", "false").lower() in ("1", "true", "yes")
    if not enabled:
        # DLP devre dışıysa hiçbir şeyi maskelemeyen pasif motor
        return DLPEngine(
            mask_bearer=False,
            mask_sk_keys=False,
            mask_github_tokens=False,
            mask_aws_keys=False,
            mask_kv_secrets=False,
            mask_passwords=False,
            mask_tckn=False,
            mask_email=False,
            mask_credit_cards=False,
            mask_ipv4=False,
            mask_ipv6=False,
            mask_jwt=False,
            mask_long_hex=False,
            log_detections=False,
        )
    return DLPEngine(log_detections=log_dets)


def get_dlp_engine() -> DLPEngine:
    """Süreç-geneli tek DLPEngine örneğini döndürür (lazy init)."""
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = _build_engine_from_env()
    return _ENGINE


def mask_pii(text: str) -> str:
    """Kolaylık fonksiyonu: tek metin maskeler, maskelenmiş metni döndürür."""
    masked, _ = get_dlp_engine().mask(text)
    return masked


def mask_messages(messages: list[dict]) -> list[dict]:
    """Kolaylık fonksiyonu: LLM mesaj listesini maskeler, yeni listeyi döndürür."""
    masked, _ = get_dlp_engine().mask_messages(messages)
    return masked
