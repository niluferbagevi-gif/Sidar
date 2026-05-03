"""Migration CI guard rails.

Referenced from `.github/workflows/migration-cutover-checks.yml`. The job
already exercises the alembic upgrade/downgrade chain against PostgreSQL; this
test module verifies the *static* invariants of the migration directory so that
a malformed revision graph fails CI before it ever touches a database.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "migrations" / "versions"


@pytest.fixture(scope="module")
def script_directory() -> ScriptDirectory:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return ScriptDirectory.from_config(cfg)


def test_migrations_directory_is_populated() -> None:
    assert MIGRATIONS_DIR.is_dir(), "migrations/versions/ must exist"
    revisions = sorted(p.name for p in MIGRATIONS_DIR.glob("*.py") if p.name != "__init__.py")
    assert revisions, "at least one alembic revision must be present"


def test_revision_filenames_use_zero_padded_prefix() -> None:
    pattern = re.compile(r"^\d{4}_[a-z0-9_]+\.py$")
    bad = [
        path.name
        for path in MIGRATIONS_DIR.glob("*.py")
        if path.name != "__init__.py" and not pattern.match(path.name)
    ]
    assert not bad, f"revision filenames must match NNNN_description.py: {bad}"


def test_revision_chain_is_linear_and_unique(script_directory: ScriptDirectory) -> None:
    revisions = list(script_directory.walk_revisions())

    seen_ids: set[str] = set()
    for revision in revisions:
        assert (
            revision.revision not in seen_ids
        ), f"duplicate revision id detected: {revision.revision}"
        seen_ids.add(revision.revision)

    heads = script_directory.get_heads()
    bases = script_directory.get_bases()

    assert len(heads) == 1, f"alembic should have a single head, found: {heads}"
    assert len(bases) == 1, f"alembic should have a single base, found: {bases}"


def test_revision_chain_walks_from_head_to_base(script_directory: ScriptDirectory) -> None:
    head = script_directory.get_current_head()
    assert head is not None

    visited: list[str] = []
    revision = script_directory.get_revision(head)
    while revision is not None:
        visited.append(revision.revision)
        down = revision.down_revision
        if down is None:
            break
        if isinstance(down, tuple):
            assert len(down) == 1, "merge revisions are not expected in this migration tree"
            down = down[0]
        revision = script_directory.get_revision(down)

    assert visited[-1] == script_directory.get_bases()[0]
    assert len(visited) == len(set(visited)), "circular linkage detected in migration chain"


def test_each_revision_defines_upgrade_and_downgrade_callables(
    script_directory: ScriptDirectory,
) -> None:
    for revision in script_directory.walk_revisions():
        module = revision.module
        assert hasattr(module, "upgrade") and callable(
            module.upgrade
        ), f"revision {revision.revision} is missing a callable upgrade()"
        assert hasattr(module, "downgrade") and callable(
            module.downgrade
        ), f"revision {revision.revision} is missing a callable downgrade()"
