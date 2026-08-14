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


def _build_rag_exports(
    tmp_path: Path,
    docs: Any,
    *,
    max_upload_bytes: int = 8,
    rag_required: bool = False,
) -> dict[str, Any]:
    agent = SimpleNamespace(
        memory=SimpleNamespace(active_session_id="session-1"),
        docs=docs,
        cfg=SimpleNamespace(RAG_REQUIRED_FOR_READINESS=rag_required),
    )

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


@pytest.mark.asyncio
async def test_rag_search_returns_503_when_required_runtime_is_not_ready(tmp_path: Path) -> None:
    docs = SimpleNamespace(
        runtime_readiness_report=lambda: {
            "ready": False,
            "metadata_seeded": True,
            "components": {
                "rag_vector": {"healthy": False, "status": "unavailable"},
                "rag_bm25": {"healthy": True, "status": "healthy"},
            },
        },
        search=lambda *_args: pytest.fail("search must not run before required RAG is ready"),
    )
    rag_search = _build_rag_exports(tmp_path, docs, rag_required=True)["rag_search"]

    response = await rag_search(q="sidar")

    assert response.status_code == 503
    payload = _json_body(response)
    assert payload["error"] == "rag_runtime_not_ready"
    assert payload["rag"]["metadata_seeded"] is True
    assert payload["rag"]["components"]["rag_vector"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_rag_search_continues_when_optional_runtime_is_not_ready(tmp_path: Path) -> None:
    search_calls: list[tuple[Any, ...]] = []
    docs = SimpleNamespace(
        runtime_readiness_report=lambda: {
            "ready": False,
            "metadata_seeded": True,
            "components": {
                "rag_vector": {"healthy": False, "status": "unavailable"},
                "rag_bm25": {"healthy": True, "status": "healthy"},
            },
        },
        search=lambda *args: search_calls.append(args) or (True, [{"id": "optional-rag"}]),
    )
    rag_search = _build_rag_exports(tmp_path, docs, rag_required=False)["rag_search"]

    response = await rag_search(q="sidar", mode="hybrid", top_k=4)

    assert response.status_code == 200
    assert _json_body(response) == {"success": True, "result": [{"id": "optional-rag"}]}
    assert search_calls == [("sidar", 4, "hybrid", "session-1")]


@pytest.mark.asyncio
async def test_rag_document_management_routes_cover_success_and_validation(tmp_path: Path) -> None:
    added_files: list[tuple[Any, ...]] = []
    docs = SimpleNamespace(
        get_index_info=lambda **kwargs: {"session_id": kwargs["session_id"]},
        add_document_from_file=lambda *args: added_files.append(args) or (True, "✓ indexed"),
        add_document_from_url=lambda url, **kwargs: _async_result((True, f"✓ {url}")),
        delete_document=lambda doc_id, session_id: f"✓ deleted {doc_id} from {session_id}",
    )
    exports = _build_rag_exports(tmp_path, docs)
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")

    assert _json_body(await exports["rag_list_docs"]()) == {
        "success": True,
        "docs": {"session_id": "session-1"},
        "count": 1,
    }
    outside = await exports["rag_add_file"](_JsonRequest({"path": "../outside.txt"}))
    assert outside.status_code == 403
    added = await exports["rag_add_file"](_JsonRequest({"path": "source.txt", "title": "Doc"}))
    assert _json_body(added) == {"success": True, "message": "✓ indexed"}
    assert added_files[-1][1:] == ("Doc", None, "session-1")

    blank_url = await exports["rag_add_url"](_JsonRequest({"url": " "}))
    assert blank_url.status_code == 400
    url = await exports["rag_add_url"](
        _JsonRequest({"url": "https://example.test", "title": "Site"})
    )
    assert _json_body(url) == {"success": True, "message": "✓ https://example.test"}
    deleted = await exports["rag_delete_doc"]("doc-1")
    assert _json_body(deleted) == {"success": True, "message": "✓ deleted doc-1 from session-1"}


async def _async_result(value: Any) -> Any:
    return value


def test_rag_upload_endpoint_handles_success_rejection_and_size_limit(tmp_path: Path) -> None:
    docs = SimpleNamespace(
        add_document_from_file=lambda _path, original_name, _metadata, _session_id: (
            (False, "rejected") if original_name == "reject.txt" else (True, "✓ uploaded")
        )
    )
    agent = SimpleNamespace(memory=SimpleNamespace(active_session_id="session-1"), docs=docs)
    router = rag_route.build_rag_router(
        resolve_agent_instance=lambda: _async_result(agent),
        await_if_needed=lambda value: value,
        max_rag_upload_bytes=lambda: 4,
        server_root=lambda: tmp_path,
        logger=SimpleNamespace(debug=lambda *_args: None),
    )
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    assert client.post("/api/rag/upload", files={"file": ("ok.txt", b"1234")}).json() == {
        "success": True,
        "message": "✓ uploaded",
    }
    rejected = client.post("/api/rag/upload", files={"file": ("reject.txt", b"1234")})
    assert rejected.status_code == 400
    assert rejected.json() == {"success": False, "error": "rejected"}
    oversized = client.post("/api/rag/upload", files={"file": ("large.txt", b"12345")})
    assert oversized.status_code == 413
