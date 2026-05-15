"""Environment bootstrap helpers for Sidar secret generation."""

from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SecretKind = Literal["urlsafe", "hex", "fernet"]

WEAK_SECRET_VALUES = {
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
    "replace-with-a-strong-24-plus-character-password",
    "replace-with-a-local-development-api-key",
}


@dataclass(frozen=True)
class SecretSpec:
    key: str
    kind: SecretKind
    nbytes: int
    min_length: int = 24


@dataclass(frozen=True)
class EnvKeyResult:
    env_path: Path
    created: bool
    updated: tuple[str, ...]
    skipped: tuple[str, ...]


SECRET_SPECS: tuple[SecretSpec, ...] = (
    SecretSpec("POSTGRES_PASSWORD", "urlsafe", 32),
    SecretSpec("API_KEY", "urlsafe", 32),
    SecretSpec("JWT_SECRET_KEY", "urlsafe", 64),
    SecretSpec("MEMORY_ENCRYPTION_KEY", "fernet", 32, min_length=44),
    SecretSpec("AUTONOMY_WEBHOOK_SECRET", "hex", 32),
    SecretSpec("SWARM_FEDERATION_SHARED_SECRET", "hex", 32),
    SecretSpec("GITHUB_WEBHOOK_SECRET", "hex", 20),
    SecretSpec("GRAFANA_ADMIN_PASSWORD", "urlsafe", 32),
    SecretSpec("METRICS_TOKEN", "urlsafe", 32),
)


def generate_secret(spec: SecretSpec) -> str:
    if spec.kind == "urlsafe":
        return secrets.token_urlsafe(spec.nbytes)
    if spec.kind == "hex":
        return secrets.token_hex(spec.nbytes)
    if spec.kind == "fernet":
        # Fernet keys are url-safe base64-encoded 32-byte keys.
        return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    raise ValueError(f"Unsupported secret kind: {spec.kind}")


def _is_weak_or_placeholder(value: str, spec: SecretSpec) -> bool:
    normalized = value.strip().strip('"\'')
    if normalized.lower() in WEAK_SECRET_VALUES:
        return True
    if len(normalized) < spec.min_length:
        return True
    if spec.kind == "fernet":
        try:
            decoded = base64.urlsafe_b64decode(normalized.encode("ascii"))
        except Exception:
            return True
        return len(decoded) != 32
    return False


def _split_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.lstrip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, value.rstrip("\n\r")


def _needs_update(lines: list[str], spec: SecretSpec, *, force: bool) -> tuple[bool, int | None]:
    for idx, line in enumerate(lines):
        parsed = _split_env_line(line)
        if not parsed:
            continue
        key, value = parsed
        if key != spec.key:
            continue
        return force or _is_weak_or_placeholder(value, spec), idx
    return True, None


def initialize_env_file(
    *,
    env_path: str | Path = ".env",
    example_path: str | Path = ".env.example",
    force: bool = False,
    create: bool = True,
) -> EnvKeyResult:
    """Create/update an env file and fill local Sidar security secrets.

    Cloud/provider API keys are intentionally not generated; they must remain real
    provider credentials supplied by the operator.
    """

    env_target = Path(env_path)
    example = Path(example_path)
    created = False

    if not env_target.exists():
        if not create:
            raise FileNotFoundError(f"Environment file not found: {env_target}")
        if not example.exists():
            raise FileNotFoundError(f"Example environment file not found: {example}")
        env_target.parent.mkdir(parents=True, exist_ok=True)
        env_target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        created = True

    lines = env_target.read_text(encoding="utf-8").splitlines(keepends=True)
    updated: list[str] = []
    skipped: list[str] = []

    for spec in SECRET_SPECS:
        should_update, idx = _needs_update(lines, spec, force=force)
        if not should_update:
            skipped.append(spec.key)
            continue
        value = generate_secret(spec)
        new_line = f"{spec.key}={value}\n"
        if idx is None:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] = lines[-1] + "\n"
            lines.append(new_line)
        else:
            lines[idx] = new_line
        updated.append(spec.key)

    env_target.write_text("".join(lines), encoding="utf-8")
    try:
        env_target.chmod(0o600)
    except OSError:
        pass

    return EnvKeyResult(
        env_path=env_target,
        created=created,
        updated=tuple(updated),
        skipped=tuple(skipped),
    )
