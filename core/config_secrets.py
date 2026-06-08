from __future__ import annotations

DEFAULT_WEAK_SECRET_VALUES: frozenset[str] = frozenset(
    {
        "",
        "sidar",
        "admin",
        "password",
        "changeme",
        "change_me",
        "secret",
        "default",
        "test",
        "example",
        "postgres",
        "root",
        "123456",
        "12345678",
    }
)


def is_nonempty_secret(value: str | None) -> bool:
    """Return whether a secret-like config value is present and not obviously malformed."""
    if value is None:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    return not any(char in stripped for char in ("\n", "\r", "\x00"))


def is_weak_secret(
    value: str | None,
    *,
    known_weak_values: set[str] | frozenset[str] = DEFAULT_WEAK_SECRET_VALUES,
    min_length: int = 24,
) -> bool:
    """Return whether a secret is empty, well-known, or too short for production use."""
    normalized = (value or "").strip()
    return normalized.lower() in known_weak_values or len(normalized) < min_length
