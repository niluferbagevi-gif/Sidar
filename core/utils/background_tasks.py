"""Strong-reference registry for fire-and-forget asyncio tasks.

``loop.create_task(...)`` only returns a task; the event loop itself keeps a
*weak* reference to it. A background task whose caller drops the returned
object can therefore be garbage-collected before it finishes (see the
``asyncio.create_task`` documentation). When that happens in the middle of an
``async with engine.begin()`` block, the SQLAlchemy connection it had checked
out of the pool is never returned and the pool later reports
``The garbage collector is trying to clean up non-checked-in connection``.

``track_background_task`` keeps such tasks alive until they complete, and
``drain_background_tasks`` lets a caller that is about to close its event loop
(e.g. a test teardown) finish them first instead of cancelling them mid-query.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

_T = TypeVar("_T")

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def track_background_task(task: _T) -> _T:
    """Keep ``task`` strongly referenced until it finishes and return it unchanged.

    Non-task values (for example the stand-in objects some unit tests return
    from a faked ``loop.create_task``) are returned as-is and not tracked.
    """
    if isinstance(task, asyncio.Task):
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


def pending_background_tasks() -> list[asyncio.Task[Any]]:
    """Return tracked tasks that have not finished yet."""
    return [task for task in _BACKGROUND_TASKS if not task.done()]


async def drain_background_tasks(grace_seconds: float = 2.0) -> None:
    """Finish the tracked tasks that belong to the running event loop.

    Tasks get up to ``grace_seconds`` seconds to complete normally; any still running
    after that are cancelled and awaited so none is left pending when the loop
    closes. Tracked tasks bound to an already closed loop can never run again
    and are dropped from the registry.
    """
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    own: list[asyncio.Task[Any]] = []
    for task in list(_BACKGROUND_TASKS):
        task_loop = task.get_loop()
        if task_loop.is_closed():
            _BACKGROUND_TASKS.discard(task)
        elif task_loop is loop and task is not current and not task.done():
            own.append(task)
    if not own:
        return
    _done, still_pending = await asyncio.wait(own, timeout=grace_seconds)
    for task in still_pending:
        task.cancel()
    if still_pending:
        await asyncio.gather(*still_pending, return_exceptions=True)
