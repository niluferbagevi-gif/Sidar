"""Tests for private dotenv persistence."""

from __future__ import annotations

import stat

from scripts.private_env_file import write_private_env


def test_write_private_env_replaces_content_with_owner_only_permissions(tmp_path) -> None:
    target = tmp_path / ".env"
    target.write_text("SECRET=old\n", encoding="utf-8")
    target.chmod(0o644)

    write_private_env(target, "SECRET=new\n")

    assert target.read_text(encoding="utf-8") == "SECRET=new\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
