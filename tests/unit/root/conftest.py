"""Isolation fixtures for tests/unit/root/test_config.py.

config.py's dotenv precedence chain is process-global by design (it backs a
real runtime "reload secrets without restarting" feature): loading a dotenv
file mutates the *live* ``os.environ`` directly (via python-dotenv's
``load_dotenv(override=...)``) and records bookkeeping in module-level
globals (``_DOTENV_MANAGED_KEYS``, ``_DOTENV_ORIGINAL_ENV_VALUES``,
``_DOTENV_KEY_SOURCES``, ``_DOTENV_LOAD_EVENTS``). test_config.py exercises
that chain through two different mechanisms across ~20 call sites --
``importlib.reload(config)`` (full module re-exec) and
``config.reload_environment()`` (the lighter in-place refresh) -- and both
write straight into the real process environment.

pytest's ``monkeypatch`` fixture cannot see or undo that: it only reverts
env vars it was itself told to set/delete. A throwaway dotenv fixture that
defines e.g. ``JWT_SECRET_KEY=jwt-from-keys-file`` therefore leaks that value
into the *real* ``os.environ`` (and into ``Config``'s class attributes) for
the remaining lifetime of the pytest worker process, invisible to
monkeypatch's teardown. Whether a later test in the same worker observes the
leak depends purely on collection/xdist scheduling order -- exactly the kind
of nondeterministic, order-dependent failure this fixture exists to prevent.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Generator

import pytest

import config


@pytest.fixture(autouse=True)
def _isolate_config_dotenv_state() -> Generator[None, None, None]:
    """Force a real process-environment + config-module reset after each test.

    A snapshot/restore of the actual ``os.environ`` (rather than relying on
    ``monkeypatch``) is required here because the leak happens *outside*
    monkeypatch's tracking. Restoring the environment alone is not enough --
    ``importlib.reload(config)`` also reassigns ``Config`` class attributes
    and the module's dotenv-tracking globals directly, which persist as
    process-global state independent of ``os.environ`` -- so a real
    ``importlib.reload(config)`` follows to rebuild them from the
    now-restored environment. This runs unconditionally (not only when the
    snapshot actually changed) because ``importlib.reload`` mutates
    ``Config`` class attributes and module globals even when the underlying
    ``os.environ`` values happen to already match the snapshot.
    """
    environ_snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(environ_snapshot)
    importlib.reload(config)
