"""Pure doctor check-result models and serialization helpers."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

_STATUS_VALUES = {"pass", "warn", "fail"}
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|api[_-]?key)=([^\s&;,'\"]+)"
)
_URL_PASSWORD_RE = re.compile(r"([a-z][a-z0-9+.-]*://[^:/@\s]+:)([^@/\s]+)(@)", re.IGNORECASE)
_AUTO_FIX_ARG_RE = re.compile(r"^[A-Za-z0-9_./:=,@+\-]+$")
_AUTO_FIX_MODULE_RE = re.compile(r"^(scripts|core\.doctor)(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_ALLOWED_DOCKER_COMPOSE_AUTO_FIXES = {
    ("ps", "postgres"),
    ("pull", "postgres"),
    ("up", "-d", "postgres"),
}


@runtime_checkable
class DoctorCheckContract(Protocol):
    """Formal contract implemented by all doctor check results."""

    name: str
    status: str
    message: str
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable doctor check payload."""


def redact_sensitive_text(value: str) -> str:
    """Mask credentials in free-form doctor details, errors and command output."""
    text = _URL_PASSWORD_RE.sub(r"\1***\3", str(value or ""))
    return _SENSITIVE_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=***", text)


def sanitize_doctor_details(value: Any) -> Any:
    """Recursively redact sensitive scalar values before report serialization."""
    if isinstance(value, dict):
        return {str(key): sanitize_doctor_details(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_doctor_details(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_doctor_details(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def validate_auto_fix_command(auto_fix: str) -> list[str]:
    """Validate and tokenize a Doctor auto-fix command for sandboxed shell-free execution."""
    command = str(auto_fix or "").strip()
    if not command:
        raise ValueError("Doctor auto_fix command is empty")
    tokens = shlex.split(command)
    if tokens[:4] == ["uv", "run", "python", "-m"] and len(tokens) >= 5:
        module = tokens[4]
        if not _AUTO_FIX_MODULE_RE.fullmatch(module):
            raise ValueError(f"Doctor auto_fix module is not allowlisted: {module}")
        for arg in tokens[5:]:
            if not _AUTO_FIX_ARG_RE.fullmatch(arg):
                raise ValueError(f"Doctor auto_fix argument is not safe: {arg}")
        return tokens
    if (
        tokens[:2] == ["docker", "compose"]
        and tuple(tokens[2:]) in _ALLOWED_DOCKER_COMPOSE_AUTO_FIXES
    ):
        return tokens
    raise ValueError("Doctor auto_fix command is not allowlisted for sandboxed execution")


def validate_doctor_check_contract(check: DoctorCheckContract) -> DoctorCheckContract:
    """Validate the formal DoctorCheck result contract fail-fast."""
    if not isinstance(getattr(check, "name", None), str) or not check.name.strip():
        raise TypeError("Doctor check contract violation: non-empty string name is required")
    if getattr(check, "status", None) not in _STATUS_VALUES:
        raise ValueError("Doctor check contract violation: status must be one of pass, warn, fail")
    if not isinstance(getattr(check, "message", None), str):
        raise TypeError("Doctor check contract violation: string message is required")
    if not isinstance(getattr(check, "details", None), dict):
        raise TypeError("Doctor check contract violation: details must be a dict")
    if not callable(getattr(check, "as_dict", None)):
        raise TypeError("Doctor check contract violation: as_dict() is required")
    return check


@dataclass
class DoctorCheck:
    """Serializable result for a single doctor readiness check."""

    name: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a redacted JSON-ready doctor check payload."""
        validate_doctor_check_contract(self)
        return {
            "name": self.name,
            "status": self.status,
            "message": redact_sensitive_text(self.message),
            "details": sanitize_doctor_details(self.details),
        }
