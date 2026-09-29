"""Tests for the fire-and-forget asyncio task registry."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from core.utils import background_tasks as bt


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    """Give every test an empty registry and restore the shared one afterwards."""
    saved = set(bt._BACKGROUND_TASKS)
    bt._BACKGROUND_TASKS.clear()
    yield
    bt._BACKGROUND_TASKS.clear()
    bt._BACKGROUND_TASKS.update(saved)


async def test_track_keeps_task_until_done_then_forgets_it() -> None:
    """A tracked task stays referenced while running and is dropped once done."""
    release = asyncio.Event()

    async def worker() -> str:
        await release.wait()
        return "ok"

    task = asyncio.get_running_loop().create_task(worker())
    assert bt.track_background_task(task) is task
    assert bt.pending_background_tasks() == [task]

    release.set()
    assert await task == "ok"
    await asyncio.sleep(0)  # let the done callback run
    assert task not in bt._BACKGROUND_TASKS
    assert bt.pending_background_tasks() == []


def test_track_returns_non_task_values_untracked() -> None:
    """Stand-ins returned by faked ``create_task`` pass through untouched."""
    sentinel = object()
    assert bt.track_background_task(None) is None
    assert bt.track_background_task(sentinel) is sentinel
    assert bt._BACKGROUND_TASKS == set()


async def test_drain_without_tasks_is_a_noop() -> None:
    """Draining an empty registry returns immediately."""
    await bt.drain_background_tasks()
    assert bt._BACKGROUND_TASKS == set()


async def test_drain_waits_for_tasks_that_finish_within_grace() -> None:
    """Tasks that complete inside the grace period finish normally, not cancelled."""
    finished: list[str] = []

    async def worker() -> None:
        await asyncio.sleep(0.01)
        finished.append("done")

    task = bt.track_background_task(asyncio.get_running_loop().create_task(worker()))
    await bt.drain_background_tasks(grace_seconds=1.0)

    assert finished == ["done"]
    assert task.done() and not task.cancelled()


async def test_drain_cancels_tasks_still_running_after_grace() -> None:
    """Tasks outliving the grace period are cancelled and awaited."""

    async def forever() -> None:
        await asyncio.Event().wait()

    task = bt.track_background_task(asyncio.get_running_loop().create_task(forever()))
    await bt.drain_background_tasks(grace_seconds=0.01)

    assert task.cancelled()


async def test_drain_skips_the_calling_task_and_finished_tasks() -> None:
    """The task running the drain and already-finished tasks are never awaited."""

    async def quick() -> None:
        return None

    done_task = bt.track_background_task(asyncio.get_running_loop().create_task(quick()))
    await done_task
    current = asyncio.current_task()
    assert current is not None
    bt._BACKGROUND_TASKS.update({current, done_task})

    await bt.drain_background_tasks(grace_seconds=0.01)

    assert not current.cancelled()
    bt._BACKGROUND_TASKS.discard(current)


def test_drain_drops_tasks_from_closed_loops_and_ignores_other_loops() -> None:
    """Tasks on a closed loop are forgotten; tasks on another live loop are left alone."""

    async def forever() -> None:
        await asyncio.Event().wait()

    closed_loop = asyncio.new_event_loop()
    stale = closed_loop.create_task(forever())
    bt.track_background_task(stale)
    stale.cancel()
    closed_loop.run_until_complete(asyncio.gather(stale, return_exceptions=True))
    closed_loop.close()
    # Simulate a task whose loop closed before its done-callback could deregister it.
    bt._BACKGROUND_TASKS.add(stale)

    other_loop = asyncio.new_event_loop()
    foreign = other_loop.create_task(forever())
    bt.track_background_task(foreign)

    try:
        asyncio.run(bt.drain_background_tasks(grace_seconds=0.01))
        assert stale not in bt._BACKGROUND_TASKS
        assert foreign in bt._BACKGROUND_TASKS
        assert not foreign.cancelled()
    finally:
        foreign.cancel()
        other_loop.run_until_complete(asyncio.gather(foreign, return_exceptions=True))
        other_loop.close()
