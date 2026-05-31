from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

import web.routes.rag as rag_route


class _JsonRequest:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def json(self) -> dict[str, Any]:
        return self.payload


def _build_rag_exports(tmp_path: Path, docs: Any, *, max_upload_bytes: int = 8) -> dict[str, Any]:
    agent = SimpleNamespace(memory=SimpleNamespace(active_session_id="session-1"), docs=docs)

    async def _resolve_agent_instance() -> Any:
        return agent

    router = rag_route.build_rag_router(
        resolve_agent_instance=_resolve_agent_instance,
        await_if_needed=lambda value: value,
        max_rag_upload_bytes=max_upload_bytes,
        server_root=tmp_path,
        logger=SimpleNamespace(debug=lambda *_args: None),
    )
    return router.legacy_exports


def _json_body(response: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(response.body))


@pytest.mark.asyncio
async def test_rag_add_file_rejects_missing_and_oversized_files(tmp_path: Path) -> None:
    rag_add_file = _build_rag_exports(tmp_path, SimpleNamespace())["rag_add_file"]

    with pytest.raises(HTTPException, match="Dosya bulunamadı") as missing:
        await rag_add_file(_JsonRequest({"path": "missing.txt"}))
    assert missing.value.status_code == 404

    oversized = tmp_path / "oversized.txt"
    oversized.write_text("123456789", encoding="utf-8")
    with pytest.raises(HTTPException, match="Dosya çok büyük") as too_large:
        await rag_add_file(_JsonRequest({"path": oversized.name}))
    assert too_large.value.status_code == 413


@pytest.mark.asyncio
async def test_rag_search_rejects_blank_and_oversized_queries(tmp_path: Path) -> None:
    rag_search = _build_rag_exports(tmp_path, SimpleNamespace())["rag_search"]

    blank = await rag_search(q="   ")
    oversized = await rag_search(q="x" * (rag_route._MAX_RAG_SEARCH_QUERY_CHARS + 1))

    assert blank.status_code == 400
    assert _json_body(blank)["error"] == "Sorgu boş."
    assert oversized.status_code == 400
    assert "Sorgu çok uzun" in _json_body(oversized)["error"]


@pytest.mark.asyncio
async def test_rag_search_accepts_sync_result_marked_as_coroutine_function(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    docs = SimpleNamespace(search=lambda *_args: (True, [{"id": "sync-coroutine-marker"}]))
    rag_search = _build_rag_exports(tmp_path, docs)["rag_search"]
    monkeypatch.setattr(asyncio, "iscoroutinefunction", lambda _call: True)

    response = await rag_search(q="sidar")

    assert _json_body(response) == {"success": True, "result": [{"id": "sync-coroutine-marker"}]}


@pytest.mark.asyncio
async def test_rag_search_accepts_non_awaitable_thread_adapter_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    docs = SimpleNamespace(search=lambda *_args: (True, [{"id": "thread-adapter"}]))
    rag_search = _build_rag_exports(tmp_path, docs)["rag_search"]
    monkeypatch.setattr(asyncio, "to_thread", lambda call, *args: call(*args))

    response = await rag_search(q="sidar")

    assert _json_body(response) == {"success": True, "result": [{"id": "thread-adapter"}]}


@pytest.mark.asyncio
async def test_rag_search_awaits_async_search_result(tmp_path: Path) -> None:
    async def _search(*_args: Any) -> tuple[bool, list[dict[str, str]]]:
        return True, [{"id": "async-search"}]

    rag_search = _build_rag_exports(tmp_path, SimpleNamespace(search=_search))["rag_search"]

    response = await rag_search(q="sidar")

    assert _json_body(response) == {"success": True, "result": [{"id": "async-search"}]}


@pytest.mark.asyncio
async def test_rag_search_awaits_coroutine_returned_from_thread(tmp_path: Path) -> None:
    async def _result() -> tuple[bool, list[dict[str, str]]]:
        return True, [{"id": "thread-coroutine"}]

    rag_search = _build_rag_exports(tmp_path, SimpleNamespace(search=lambda *_args: _result()))[
        "rag_search"
    ]

    response = await rag_search(q="sidar")

    assert _json_body(response) == {"success": True, "result": [{"id": "thread-coroutine"}]}


@pytest.mark.asyncio
async def test_rag_search_accepts_query_at_maximum_length(tmp_path: Path) -> None:
    docs = SimpleNamespace(search=lambda *_args: (True, []))
    rag_search = _build_rag_exports(tmp_path, docs)["rag_search"]

    response = await rag_search(q="x" * rag_route._MAX_RAG_SEARCH_QUERY_CHARS)

    assert _json_body(response) == {"success": True, "result": []}
