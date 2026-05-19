from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse


def build_rag_router(
    *,
    resolve_agent_instance: Callable[[], Awaitable[Any]],
    await_if_needed: Callable[[Any], Awaitable[Any]],
    max_rag_upload_bytes: int,
) -> APIRouter:
    router = APIRouter()

    @router.get("/rag/docs")
    async def rag_list_docs() -> Any:
        agent = await resolve_agent_instance()
        session_id = agent.memory.active_session_id or "global"
        docs = agent.docs.get_index_info(session_id=session_id)
        return JSONResponse({"success": True, "docs": docs, "count": len(docs)})

    @router.post("/rag/add-file")
    async def rag_add_file(request: Request) -> Any:
        body = await request.json()
        path = body.get("path", "").strip()
        title = body.get("title", "").strip()
        if not path:
            return JSONResponse({"success": False, "error": "Dosya yolu boş."}, status_code=400)

        root = Path(__file__).resolve().parents[2]
        target = (root / path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return JSONResponse(
                {"success": False, "error": "Güvenlik: proje dışına çıkılamaz."}, status_code=403
            )

        agent = await resolve_agent_instance()
        session_id = agent.memory.active_session_id or "global"
        ok, msg = await asyncio.to_thread(
            agent.docs.add_document_from_file, str(target), title or target.name, None, session_id
        )
        return JSONResponse({"success": ok, "message": msg})

    @router.post("/rag/add-url")
    async def rag_add_url(request: Request) -> Any:
        body = await request.json()
        url = body.get("url", "").strip()
        title = body.get("title", "").strip()
        if not url:
            return JSONResponse({"success": False, "error": "URL boş."}, status_code=400)

        agent = await resolve_agent_instance()
        session_id = agent.memory.active_session_id or "global"
        ok, msg = await agent.docs.add_document_from_url(url, title=title, session_id=session_id)
        return JSONResponse({"success": ok, "message": msg})

    @router.delete("/rag/docs/{doc_id}")
    async def rag_delete_doc(doc_id: str) -> Any:
        agent = await resolve_agent_instance()
        session_id = agent.memory.active_session_id or "global"
        msg = await asyncio.to_thread(agent.docs.delete_document, doc_id, session_id)
        success = msg.startswith("✓")
        return JSONResponse({"success": success, "message": msg})

    @router.post("/api/rag/upload")
    async def upload_rag_file(file: UploadFile = File(...)) -> Any:
        agent = await await_if_needed(resolve_agent_instance())
        session_id = agent.memory.active_session_id or "global"

        temp_dir = None
        try:
            data = await file.read(max_rag_upload_bytes + 1)
            if len(data) > max_rag_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail={
                        "detail": "Dosya çok büyük. Maksimum izin verilen boyut: "
                        f"{max_rag_upload_bytes // (1024 * 1024)} MB"
                    },
                )

            temp_dir = Path(tempfile.mkdtemp())
            original_name = file.filename or "uploaded_file.txt"
            safe_filename = "".join(c for c in original_name if c.isalnum() or c in ".-_ ")
            if not safe_filename:
                safe_filename = "uploaded_file.txt"
            tmp_path = temp_dir / safe_filename
            tmp_path.write_bytes(data)

            ok, msg = await asyncio.to_thread(
                agent.docs.add_document_from_file,
                str(tmp_path),
                original_name,
                None,
                session_id,
            )
            return JSONResponse({"success": ok, "message": msg})
        finally:
            await file.close()
            if temp_dir:
                for child in temp_dir.glob("*"):
                    child.unlink(missing_ok=True)
                temp_dir.rmdir()

    return router
