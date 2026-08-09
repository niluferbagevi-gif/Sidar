"""Rotate Sidar production-only secrets without disclosing their values."""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import stat
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from scripts.secret_strength import is_weak_secret

ROTATION_KEYS = (
    "API_KEY",
    "JWT_SECRET_KEY",
    "MEMORY_ENCRYPTION_KEY",
    "AUTONOMY_WEBHOOK_SECRET",
    "SWARM_FEDERATION_SHARED_SECRET",
    "GITHUB_WEBHOOK_SECRET",
    "GRAFANA_ADMIN_PASSWORD",
    "METRICS_TOKEN",
)


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _replace_values(content: str, replacements: dict[str, str]) -> str:
    lines = content.splitlines()
    seen: set[str] = set()
    for index, line in enumerate(lines):
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key = line.split("=", 1)[0].strip()
        if key in replacements:
            lines[index] = f"{key}={replacements[key]}"
            seen.add(key)
    lines.extend(f"{key}={replacements[key]}" for key in ROTATION_KEYS if key not in seen)
    return "\n".join(lines) + "\n"


def _generate_accepted_secret(factory: Callable[[], str], *, max_attempts: int = 100) -> str:
    """Generate a secret that satisfies the same policy used by the post-write audit."""
    for _attempt in range(max_attempts):
        candidate = factory()
        if not is_weak_secret(candidate):
            return candidate
    raise RuntimeError(f"could not generate an accepted secret after {max_attempts} attempts")


def _generate_values() -> dict[str, str]:
    generated = {
        key: _generate_accepted_secret(lambda: secrets.token_urlsafe(48)) for key in ROTATION_KEYS
    }
    generated["MEMORY_ENCRYPTION_KEY"] = _generate_accepted_secret(
        lambda: base64.urlsafe_b64encode(os.urandom(32)).decode()
    )
    return generated


def _audit(production: Path, references: list[Path]) -> list[str]:
    production_values = _read_dotenv(production)
    reference_values = [_read_dotenv(path) for path in references if path.is_file()]
    findings: list[str] = []
    for key in ROTATION_KEYS:
        value = production_values.get(key, "")
        if is_weak_secret(value):
            findings.append(f"{key}: missing_or_weak")
        if value and any(values.get(key) == value for values in reference_values):
            findings.append(f"{key}: shared_with_non_production")
    return findings


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """Run a secret audit or explicitly rotate a local production dotenv file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env.production"))
    parser.add_argument(
        "--reference-env",
        action="append",
        type=Path,
        default=None,
        help="Non-production dotenv to compare; repeatable.",
    )
    parser.add_argument("--apply", action="store_true", help="Generate and atomically write values")
    parser.add_argument(
        "--ack-memory-key-impact",
        action="store_true",
        help="Confirm the Fernet recovery/re-encryption decision has been recorded.",
    )
    args = parser.parse_args(argv)
    references = args.reference_env or [
        Path(".env"),
        Path(".env.development"),
        Path(".env.test"),
        Path(".env.advanced"),
    ]

    if args.apply:
        if not args.ack_memory_key_impact:
            parser.error("--apply requires --ack-memory-key-impact")
        if not args.env_file.is_file():
            parser.error(f"production env file does not exist: {args.env_file}")
        content = _replace_values(args.env_file.read_text(encoding="utf-8"), _generate_values())
        _atomic_write(args.env_file, content)
        print(f"Rotated {len(ROTATION_KEYS)} production secrets; values were not logged.")

    findings = _audit(args.env_file, references)
    if findings:
        print("Production secret audit failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(f"Production secret audit passed for {len(ROTATION_KEYS)} isolated strong secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
