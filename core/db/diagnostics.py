"""PostgreSQL failure diagnostics for the phased database facade."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _doctor_database_env_failure_reason() -> str:
    """Return Doctor/database_env failure context without raising from fallback paths."""
    try:
        from core.doctor import check_database_env

        check = check_database_env()
    except Exception as exc:  # pragma: no cover - defensive diagnostic path
        logger.debug("Doctor/database_env teşhisi alınamadı: %s", exc)
        return ""

    status = str(getattr(check, "status", "") or "").lower()
    if status != "fail":
        return ""
    details = getattr(check, "details", {}) or {}
    if isinstance(details, dict):
        failure_reason = str(details.get("failure_reason", "") or "").strip()
        if failure_reason:
            return failure_reason
    return str(getattr(check, "message", "") or "").strip()


def postgres_failure_diagnosis(reason: str, exc: BaseException | None = None) -> str:
    """Return a concise, shared PostgreSQL failure diagnosis for DB and RAG fallbacks."""
    doctor_reason = _doctor_database_env_failure_reason()
    doctor_reason_lower = doctor_reason.lower()
    if doctor_reason and (
        "database_url was lost" in doctor_reason_lower
        or "database_url is not set" in doctor_reason_lower
    ):
        return "DATABASE_URL yok/kayboldu"

    combined = f"{type(exc).__name__ if exc else ''} {reason} {exc or ''}".lower()
    if any(
        marker in combined
        for marker in (
            "password authentication failed",
            "authentication failed",
            "invalid password",
            "invalidpassword",
            "invalidpassworderror",
            "28p01",
            "permission denied",
            "auth",
        )
    ):
        return "asyncpg auth reddi / yetki/parola hatası"
    if any(marker in combined for marker in ("timeout", "timed out", "zaman aş", "pool timeout")):
        return "TCP timeout / bağlantı havuzu zaman aşımı"
    if "asyncpg" in combined:
        return "asyncpg bağımlılığı kullanılamıyor"
    if "pool" in combined:
        return "bağlantı havuzu oluşturulamadı"
    if any(
        marker in combined
        for marker in (
            "connection refused",
            "could not connect",
            "server closed",
            "connection failed",
            "connection reset",
            "bağlantı",
        )
    ):
        return "TCP bağlantısı kurulamadı veya koptu"
    if "extension" in combined or "vector" in combined:
        return "pgvector hazırlığı / extension-migrasyon tamamlanamadı"
    if doctor_reason:
        return f"Doctor/database_env: {doctor_reason}"
    return "PostgreSQL bağlantı nedeni sınıflandırılamadı"


def postgres_user_action_message(reason: str, exc: BaseException | None = None) -> str:
    """Convert PostgreSQL failure state to a secret-safe, user-facing action message."""
    diagnosis = postgres_failure_diagnosis(reason, exc)
    if diagnosis == "DATABASE_URL yok/kayboldu":
        return (
            "PostgreSQL bağlantısı başlatılamadı (DATABASE_URL yok/kayboldu). "
            "Doctor/database_env sonucunu ve dotenv reload zincirini kontrol edin. "
            "SQLite degraded mode aktif edildi."
        )
    if diagnosis == "asyncpg auth reddi / yetki/parola hatası":
        return (
            "PostgreSQL bağlantısı başarısız (yetki/parola hatası). "
            ".env dosyanızdaki DATABASE_URL, SIDAR_CONTAINER_DATABASE_URL ve "
            "POSTGRES_PASSWORD değerlerinin aynı olduğundan emin olun. "
            f"Teşhis: {diagnosis}. SQLite degraded mode aktif edildi."
        )
    if diagnosis == "TCP timeout / bağlantı havuzu zaman aşımı":
        return (
            "PostgreSQL bağlantısı zaman aşımına uğradı. Veritabanı servisinin çalıştığını, "
            "host/port değerlerini ve ağ erişimini kontrol edin. "
            f"Teşhis: {diagnosis}. SQLite degraded mode aktif edildi."
        )
    if diagnosis == "TCP bağlantısı kurulamadı veya koptu":
        return (
            "PostgreSQL (asyncpg) bağlantısı kurulamadı veya bağlantı koptu. Veritabanı servisinin "
            "çalıştığını, DATABASE_URL host/port bilgisini ve container ağını kontrol edin. "
            f"Teşhis: {diagnosis}. SQLite degraded mode aktif edildi."
        )
    if diagnosis == "asyncpg bağımlılığı kullanılamıyor":
        return (
            "PostgreSQL bağlantısı için asyncpg bağımlılığı kullanılamıyor. "
            "Kurulumu `uv sync --all-extras` ile tamamlayın veya postgres extras kurulumunu "
            "doğrulayın. "
            f"Teşhis: {diagnosis}. SQLite degraded mode aktif edildi."
        )
    if diagnosis == "bağlantı havuzu oluşturulamadı":
        return (
            "PostgreSQL bağlantı havuzu kullanılamıyor/oluşturulamadı. "
            "DB_POOL_SIZE, POSTGRES_MAX_CONNECTIONS "
            f"ve veritabanı erişimini kontrol edin. Teşhis: {diagnosis}. "
            "SQLite degraded mode aktif edildi."
        )
    return (
        "PostgreSQL bağlantısı başarısız. .env dosyanızdaki DATABASE_URL/POSTGRES_* değerlerini "
        f"ve veritabanı servis durumunu kontrol edin. Teşhis: {diagnosis}. "
        "SQLite degraded mode aktif edildi."
    )
