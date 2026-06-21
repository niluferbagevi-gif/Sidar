"""Authentication boundary for the phased ``core.db`` split.

The implementation still lives in ``core.db`` during Phase 1; this module gives
callers a stable import target before the auth implementation is physically
moved out of the compatibility facade.
"""

from __future__ import annotations

from core.db import (
    AuthTokenRecord,
    UserRecord,
    _auth_hash_slo_ms,
    _current_pbkdf2_iterations,
    _hash_password,
    _record_auth_hash_latency,
    _verify_password,
)

__all__ = [
    "AuthTokenRecord",
    "UserRecord",
    "_auth_hash_slo_ms",
    "_current_pbkdf2_iterations",
    "_hash_password",
    "_record_auth_hash_latency",
    "_verify_password",
]
