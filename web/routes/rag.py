from __future__ import annotations

import asyncio
import inspect
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from web.routes import LegacyExportRouter
from fastapi.responses import JSONResponse


def build_rag_router(
    *,
    resolve_agent_instance: Callable[[], Awaitable[Any]],
    await_if_needed: Callable[[Any], Awaitable[Any]],
    max_rag_upload_bytes: int,
    server_root: Path,
    logger: Any,
) -> APIRouter:
    """Build router for RAG document management endpoints."""
    router = LegacyExportRouter()

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

        target = (server_root / path).resolve()
        try:
            target.relative_to(server_root)
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
        return JSONResponse({"success": msg.startswith("✓"), "message": msg})

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

            async with await anyio.open_file(tmp_path, "wb") as buffer:
                await buffer.write(data)

            ok, msg = await asyncio.to_thread(
                agent.docs.add_document_from_file,
                str(tmp_path),
                original_name,
                None,
                session_id,
            )
            if ok:
                return JSONResponse({"success": True, "message": msg})
            return JSONResponse({"success": False, "error": msg}, status_code=400)
        except HTTPException:
            raise
        except Exception as exc:
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)
        finally:
            try:
                await file.close()
            except Exception as exc:
                logger.debug("Yüklenen dosya kapatılamadı: %s", exc)
            if temp_dir is not None:
                try:
                    shutil.rmtree(temp_dir)
                except Exception as exc:
                    logger.debug("Geçici dizin silinemedi (%s): %s", temp_dir, exc)

    @router.get("/rag/search")
    async def rag_search(q: str = "", mode: str = "auto", top_k: int = 3) -> Any:
        if not q.strip():
            return JSONResponse({"success": False, "error": "Sorgu boş."}, status_code=400)
        agent = await resolve_agent_instance()
        session_id = agent.memory.active_session_id or "global"
        search_call = agent.docs.search
        if asyncio.iscoroutinefunction(search_call):
            ok, result = await search_call(q.strip(), min(top_k, 10), mode, session_id)
        else:
            maybe_result = await asyncio.to_thread(
                search_call, q.strip(), min(top_k, 10), mode, session_id
            )
            if inspect.isawaitable(maybe_result):
                ok, result = await maybe_result
            else:
                ok, result = maybe_result
        return JSONResponse({"success": ok, "result": result})

    router.legacy_exports = {
        "rag_add_file": rag_add_file,
        "rag_add_url": rag_add_url,
        "upload_rag_file": upload_rag_file,
        "rag_search": rag_search,
    }
    return router
