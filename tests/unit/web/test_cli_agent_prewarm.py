"""Regression tests for the web CLI agent pre-warm and browser WS subprotocol contract."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import web.cli as web_cli
from web.security import SIDAR_WS_CHAT_PROTOCOL, SIDAR_WS_VOICE_PROTOCOL

REPO_ROOT = Path(__file__).resolve().parents[3]


class _LoopBoundDb:
    """Mimics an asyncpg-backed Database: its pool belongs to the loop that opened it."""

    def __init__(self) -> None:
        self.opened_loop: asyncio.AbstractEventLoop | None = None
        self.closed_loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> None:
        self.opened_loop = asyncio.get_running_loop()

    async def close(self) -> None:
        self.closed_loop = asyncio.get_running_loop()


class _Agent:
    VERSION = "9.9.9"

    def __init__(self, *, fail: bool = False) -> None:
        self.memory = SimpleNamespace(db=_LoopBoundDb())
        self._fail = fail

    async def initialize(self) -> None:
        await self.memory.db.connect()
        if self._fail:
            raise RuntimeError("init failed after pool opened")


def test_prewarm_closes_db_pool_on_the_loop_that_opened_it() -> None:
    agent = _Agent()

    asyncio.run(web_cli._prewarm_agent(agent))

    db = agent.memory.db
    assert db.opened_loop is not None
    assert db.closed_loop is db.opened_loop


def test_prewarm_still_releases_pool_when_initialize_fails() -> None:
    agent = _Agent(fail=True)

    with pytest.raises(RuntimeError, match="init failed"):
        asyncio.run(web_cli._prewarm_agent(agent))

    assert agent.memory.db.closed_loop is agent.memory.db.opened_loop


def test_prewarm_tolerates_agents_without_memory_or_async_initialize() -> None:
    asyncio.run(web_cli._prewarm_agent(SimpleNamespace(initialize=lambda: None)))
    asyncio.run(web_cli._prewarm_agent(SimpleNamespace(memory=SimpleNamespace(db=None))))
    sync_db = SimpleNamespace(closed=False)
    sync_db.close = lambda: setattr(sync_db, "closed", True)
    asyncio.run(web_cli._prewarm_agent(SimpleNamespace(memory=SimpleNamespace(db=sync_db))))
    assert sync_db.closed is True


@pytest.mark.parametrize("fail", [False, True])
def test_main_never_hands_prewarmed_agent_to_server(monkeypatch, fail: bool) -> None:
    import web_server

    class _Args:
        host = "127.0.0.1"
        port = 9195
        level = None
        provider = None
        log = "info"

    class _Parser:
        def add_argument(self, *_, **__):
            return None

        def parse_known_args(self):
            return _Args(), []

    printed: list[str] = []
    run_calls: list[tuple] = []
    monkeypatch.setattr(web_cli.argparse, "ArgumentParser", lambda **_: _Parser())
    monkeypatch.setattr(
        web_cli, "uvicorn", SimpleNamespace(run=lambda *a, **k: run_calls.append((a, k)))
    )
    monkeypatch.setattr("builtins.print", lambda *a, **_: printed.append(" ".join(map(str, a))))
    agent = _Agent(fail=fail)
    monkeypatch.setattr(web_cli, "SidarAgent", lambda _cfg: agent)
    monkeypatch.setattr(web_server, "_agent", object())

    web_cli.main()

    # The served agent must be created lazily inside uvicorn's own event loop.
    assert web_server._agent is None
    assert agent.memory.db.closed_loop is agent.memory.db.opened_loop
    assert any("v9.9.9" in line for line in printed)
    assert run_calls


@pytest.mark.parametrize(
    ("relative_path", "constant_name", "expected"),
    [
        (
            "web_ui_react/src/hooks/useWebSocket.ts",
            "SIDAR_WS_CHAT_PROTOCOL",
            SIDAR_WS_CHAT_PROTOCOL,
        ),
        (
            "web_ui_react/src/hooks/useVoiceAssistant.ts",
            "SIDAR_WS_VOICE_PROTOCOL",
            SIDAR_WS_VOICE_PROTOCOL,
        ),
    ],
)
def test_frontend_offers_server_subprotocol_before_token(
    relative_path: str, constant_name: str, expected: str
) -> None:
    """Browsers abort the WS handshake unless a requested subprotocol is echoed.

    The server echoes only the fixed protocol (never the token), so the client
    must offer that fixed value alongside the token.
    """
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    declared = re.search(rf'export const {constant_name} = "([^"]+)";', source)
    assert declared is not None
    assert declared.group(1) == expected
    assert re.search(rf"new WebSocket\([A-Z_]+\(\), \[{constant_name}, token\]\)", source)
