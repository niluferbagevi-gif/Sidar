"""Sidar CLI launcher (``main.py``) helper package.

``main.py`` stays the entrypoint and keeps thin, monkeypatch-stable wrappers
for backward compatibility; the underlying logic is split into focused
modules here (starting with ``launcher.process`` for command building and
subprocess streaming) instead of living entirely in one file.
"""

from __future__ import annotations
