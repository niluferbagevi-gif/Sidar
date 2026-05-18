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


def test_alembic_default_url_is_documented_as_local_only() -> None:
    for relative_path in ("alembic.ini", "sidar_assets/alembic.ini"):
        config_text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "Local development fallback only" in config_text
        assert "DATABASE_URL or -x database_url=..." in config_text
        assert "postgresql+asyncpg://sidar:sidar@127.0.0.1:5432/sidar" in config_text


def test_alembic_env_rejects_local_fallback_in_production() -> None:
    for relative_path in ("migrations/env.py", "sidar_assets/migrations/env.py"):
        env_text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "LOCAL_DEV_FALLBACK_DATABASE_URL" in env_text
        assert 'SIDAR_ENV", "").strip().lower() in PRODUCTION_ENV_NAMES' in env_text
        assert "Set DATABASE_URL or pass" in env_text
        assert '_ensure_database_url_allowed(url, source="alembic.ini")' in env_text


def test_alembic_documentation_uses_supported_asyncpg_driver() -> None:
    for relative_path in (
        "README.md",
        "docs/module-notes/runbooks/production-cutover-playbook.md.md",
    ):
        doc_text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "postgresql+psycopg://" not in doc_text
        assert "postgresql+asyncpg://user:pass@host:5432/sidar" in doc_text


def test_alembic_revision_creation_uses_modern_naming_defaults() -> None:
    expected_options = {
        "file_template": "%(year)d_%(month).2d_%(day).2d_%(rev)s_%(slug)s",
        "truncate_slug_length": "60",
        "timezone": "UTC",
        "path_separator": "os",
    }
    for relative_path in ("alembic.ini", "sidar_assets/alembic.ini"):
        cfg = Config(str(PROJECT_ROOT / relative_path))
        for option, expected_value in expected_options.items():
            assert cfg.get_main_option(option) == expected_value
