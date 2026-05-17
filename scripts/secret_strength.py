"""Offline weak-secret detection helpers for installer/runtime guardrails.

The checker intentionally avoids network calls and optional dependencies.  It is
not a password manager replacement; it is a deterministic safety net for common
human-chosen or placeholder secrets that should be rotated during installation.
"""

from __future__ import annotations

import argparse
import math
import re
from collections import Counter

DEFAULT_MIN_LENGTH = 24
DEFAULT_MIN_ENTROPY_BITS = 80.0
DEFAULT_MIN_SHANNON_BITS = 55.0

WEAK_TOKENS = (
    "password",
    "passwd",
    "admin",
    "changeme",
    "change_me",
    "change-me",
    "replacewith",
    "replace-with",
    "secret",
    "default",
    "example",
    "test",
    "sidar",
    "postgres",
    "root",
    "qwerty",
    "letmein",
    "welcome",
    "monkey",
    "dragon",
    "iloveyou",
    "abc",
    "asdf",
    "zxcv",
)

SEQUENCES = (
    "0123456789",
    "9876543210",
    "abcdefghijklmnopqrstuvwxyz",
    "zyxwvutsrqponmlkjihgfedcba",
    "qwertyuiop",
    "poiuytrewq",
    "asdfghjkl",
    "lkjhgfdsa",
    "zxcvbnm",
    "mnbvcxz",
)

LEETSPEAK_TRANSLATION = str.maketrans(
    {
        "0": "o",
        "1": "l",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "@": "a",
        "$": "s",
        "!": "i",
    }
)


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "", value.lower().translate(LEETSPEAK_TRANSLATION))


def _has_repeated_chunk(value: str) -> bool:
    max_chunk = min(12, len(value) // 2)
    for size in range(1, max_chunk + 1):
        if len(value) % size == 0 and value[:size] * (len(value) // size) == value:
            return True
    return False


def _has_sequence(value: str, min_run: int = 4) -> bool:
    lowered = value.lower()
    for sequence in SEQUENCES:
        for start in range(0, len(sequence) - min_run + 1):
            if sequence[start : start + min_run] in lowered:
                return True
    return False


def _charset_pool(value: str) -> int:
    pool = 0
    if re.search(r"[a-z]", value):
        pool += 26
    if re.search(r"[A-Z]", value):
        pool += 26
    if re.search(r"\d", value):
        pool += 10
    if re.search(r"[^A-Za-z0-9]", value):
        pool += 33
    return max(pool, 1)


def _shannon_bits(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    if length == 0:
        return 0.0
    return -sum((count / length) * math.log2(count / length) for count in counts.values()) * length


def estimated_entropy_bits(value: str) -> float:
    """Return a conservative entropy estimate for deterministic policy checks."""

    pool_entropy = len(value) * math.log2(_charset_pool(value))
    shannon_entropy = _shannon_bits(value)
    unique_bonus = min(len(set(value)) * 2.0, 40.0)
    return min(pool_entropy, shannon_entropy + unique_bonus)


def is_weak_secret(
    value: str,
    *,
    min_length: int = DEFAULT_MIN_LENGTH,
    min_entropy_bits: float = DEFAULT_MIN_ENTROPY_BITS,
    min_shannon_bits: float = DEFAULT_MIN_SHANNON_BITS,
) -> bool:
    """Return True when *value* is missing, placeholder-like, or low entropy."""

    stripped = value.strip()
    if not stripped:
        return True

    normalized = _normalized(stripped)
    if normalized in WEAK_TOKENS:
        return True
    if any(token in normalized for token in WEAK_TOKENS):
        return True
    if len(stripped) < min_length:
        return True
    if len(set(stripped)) <= 4:
        return True
    if re.search(r"(.)\1{3,}", stripped):
        return True
    if _has_repeated_chunk(stripped):
        return True
    if _has_sequence(stripped):
        return True

    return (
        estimated_entropy_bits(stripped) < min_entropy_bits
        or _shannon_bits(stripped) < min_shannon_bits
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect weak/placeholder Sidar secret values.")
    parser.add_argument("value", help="Secret value to evaluate")
    parser.add_argument("--min-length", type=int, default=DEFAULT_MIN_LENGTH)
    parser.add_argument("--min-entropy-bits", type=float, default=DEFAULT_MIN_ENTROPY_BITS)
    parser.add_argument("--quiet", action="store_true", help="Only use the exit code")
    args = parser.parse_args(argv)

    weak = is_weak_secret(
        args.value,
        min_length=args.min_length,
        min_entropy_bits=args.min_entropy_bits,
    )
    if not args.quiet:
        verdict = "weak" if weak else "strong"
        print(f"{verdict} entropy_bits={estimated_entropy_bits(args.value):.1f}")
    return 0 if weak else 1


if __name__ == "__main__":
    raise SystemExit(main())
