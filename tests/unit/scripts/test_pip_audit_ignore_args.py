from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.pip_audit_ignore_args import DEFAULT_POLICY_PATH, build_ignore_args, parse_policy


def test_parse_policy_builds_dated_ignore_args(tmp_path: Path) -> None:
    policy = tmp_path / "pip-audit-ignores.tsv"
    policy.write_text(
        "# vuln_id\tpackage\texpires\treason\n"
        "CVE-2025-3000\ttorch\t2026-07-11\tTemporary PyTorch resolver acceptance.\n",
        encoding="utf-8",
    )

    ignores = parse_policy(policy, today=date(2026, 6, 11))

    assert [(ignore.vuln_id, ignore.package) for ignore in ignores] == [("CVE-2025-3000", "torch")]
    assert build_ignore_args(ignores) == ["--ignore-vuln", "CVE-2025-3000"]


def test_parse_policy_rejects_expired_entries(tmp_path: Path) -> None:
    policy = tmp_path / "pip-audit-ignores.tsv"
    policy.write_text(
        "CVE-2025-3000\ttorch\t2026-06-10\tExpired acceptance.\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="expired on 2026-06-10"):
        parse_policy(policy, today=date(2026, 6, 11))


def test_parse_policy_requires_tab_separated_reason(tmp_path: Path) -> None:
    policy = tmp_path / "pip-audit-ignores.tsv"
    policy.write_text("CVE-2025-3000 torch 2026-07-11 missing-tabs\n", encoding="utf-8")

    with pytest.raises(ValueError, match="expected 4 tab-separated fields"):
        parse_policy(policy, today=date(2026, 6, 11))


def test_repository_torch_policy_exception_expires_fail_closed() -> None:
    ignores = parse_policy(DEFAULT_POLICY_PATH, today=date(2026, 9, 15))

    assert any(
        ignore.vuln_id == "GHSA-rrmf-rvhw-rf47"
        and ignore.package == "torch"
        and ignore.expires == date(2026, 9, 15)
        for ignore in ignores
    )

    with pytest.raises(RuntimeError, match="GHSA-rrmf-rvhw-rf47 .* expired on 2026-09-15"):
        parse_policy(DEFAULT_POLICY_PATH, today=date(2026, 9, 16))
