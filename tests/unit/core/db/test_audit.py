"""Audit persistence module split contract tests."""

from pathlib import Path

import core.db.audit as audit
import core.db.audit_log as audit_log


def test_audit_module_is_primary_and_legacy_wrapper_reexports_helpers() -> None:
    assert audit.record_audit_log is audit_log.record_audit_log
    assert audit.list_audit_logs is audit_log.list_audit_logs


def test_monolith_delegates_audit_persistence_to_audit_module() -> None:
    source = Path("core/db/monolith.py").read_text(encoding="utf-8")

    assert "from core.db import audit as db_audit" in source
    assert "db_audit.record_audit_log" in source
    assert "db_audit.list_audit_logs" in source
    assert "from core.db import audit_log as db_audit_log" not in source
