from __future__ import annotations

import asyncio
import re
import subprocess  # nosec B404
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

_ALLOWED_GIT_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("git",),
    ("git", "rev-parse", "--abbrev-ref", "HEAD"),
    ("git", "remote", "get-url", "origin"),
    ("git", "symbolic-ref", "--short", "HEAD@{upstream}"),
    ("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"),
    ("git", "branch", "--format=%(refname:short)"),
)
_BRANCH_RE = re.compile(r"^[a-zA-Z0-9/_.-]+$")
_SAFE_EXTENSIONS = {
    ".py",
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".toml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".sh",
    ".gitignore",
    ".dockerignore",
    ".sql",
    ".csv",
    ".xml",
}


def _is_allowed_git_command(cmd: list[str]) -> bool:
    if not cmd or any("\x00" in str(part) for part in cmd):
        return False
    return tuple(str(part) for part in cmd) in _ALLOWED_GIT_COMMANDS


def _git_run(cmd: list[str], cwd: str, logger: Any, stderr: int = subprocess.DEVNULL) -> str:
    if not _is_allowed_git_command(cmd):
        logger.warning("Güvenli olmayan git komutu reddedildi: %s", cmd)
        return ""
    try:
        return (
            subprocess.check_output(cmd, cwd=cwd, stderr=stderr, shell=False)  # nosec
            .decode()
            .strip()
        )
    except Exception:
        return ""


def build_project_ops_router(
    *,
    get_request_user: Callable[..., Any],
    resolve_agent_instance: Callable[[], Awaitable[Any]],
    max_file_content_bytes: int,
    server_root: Path,
    cfg: Any,
    logger: Any,
) -> APIRouter:
    router = APIRouter()

    @router.get("/sessions")
    async def get_sessions(request: Request, user: Any = Depends(get_request_user)) -> Any:
        agent = await resolve_agent_instance()
        sessions = await agent.memory.db.list_sessions(user.id)
        return JSONResponse(
            {
                "active_session": None,
                "sessions": [
                    {
                        "id": row.id,
                        "title": row.title,
                        "updated_at": row.updated_at,
                        "message_count": len(await agent.memory.db.get_session_messages(row.id)),
                    }
                    for row in sessions
                ],
            }
        )

    @router.get("/sessions/{session_id}")
    async def load_session(session_id: str, request: Request, user: Any = Depends(get_request_user)) -> Any:
        agent = await resolve_agent_instance()
        session = await agent.memory.db.load_session(session_id, user.id)
        if not session:
            return JSONResponse({"success": False, "error": "Oturum bulunamadı."}, status_code=404)
        messages = await agent.memory.db.get_session_messages(session_id)
        history = [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": agent.memory._safe_ts(m.created_at),
                "tokens_used": m.tokens_used,
            }
            for m in messages
        ]
        return JSONResponse({"success": True, "history": history})

    @router.post("/sessions/new")
    async def new_session(request: Request, user: Any = Depends(get_request_user)) -> Any:
        agent = await resolve_agent_instance()
        session = await agent.memory.db.create_session(user.id, "Yeni Sohbet")
        return JSONResponse({"success": True, "session_id": session.id})

    @router.delete("/sessions/{session_id}")
    async def delete_session(session_id: str, request: Request, user: Any = Depends(get_request_user)) -> Any:
        agent = await resolve_agent_instance()
        deleted = await agent.memory.db.delete_session(session_id, user.id)
        if deleted:
            return JSONResponse({"success": True})
        return JSONResponse({"success": False, "error": "Silinemedi."}, status_code=500)

    @router.get("/files")
    async def list_project_files(path: str = "") -> Any:
        target = (server_root / path).resolve()
        try:
            target.relative_to(server_root)
        except ValueError:
            return JSONResponse({"error": "Güvenlik: proje dışına çıkılamaz."}, status_code=403)
        if not target.exists():
            return JSONResponse({"error": f"Dizin bulunamadı: {path}"}, status_code=404)
        if not target.is_dir():
            return JSONResponse({"error": f"Belirtilen yol bir dizin değil: {path}"}, status_code=400)
        items = []
        for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if item.name.startswith(".") or item.name in ("__pycache__", "node_modules"):
                continue
            rel = str(item.relative_to(server_root))
            items.append(
                {
                    "name": item.name,
                    "path": rel,
                    "type": "file" if item.is_file() else "dir",
                    "size": item.stat().st_size if item.is_file() else 0,
                }
            )
        return JSONResponse({"path": str(target.relative_to(server_root)) if path else ".", "items": items})

    @router.get("/file-content")
    async def file_content(path: str) -> Any:
        target = (server_root / path).resolve()
        try:
            target.relative_to(server_root)
        except ValueError:
            return JSONResponse({"error": "Güvenlik: proje dışına çıkılamaz."}, status_code=403)
        if not target.exists():
            return JSONResponse({"error": f"Dosya bulunamadı: {path}"}, status_code=404)
        if target.is_dir():
            return JSONResponse({"error": "Belirtilen yol bir dizin."}, status_code=400)
        if target.suffix.lower() not in _SAFE_EXTENSIONS:
            return JSONResponse({"error": f"Desteklenmeyen dosya türü: {target.suffix}"}, status_code=415)
        size_bytes = target.stat().st_size
        if size_bytes > max_file_content_bytes:
            return JSONResponse(
                {"error": f"Dosya boyutu limiti aşıldı: {size_bytes} bayt (maksimum {max_file_content_bytes} bayt)"},
                status_code=413,
            )
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            return JSONResponse({"path": path, "content": content, "size": len(content)})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @router.get("/git-info")
    async def git_info() -> Any:
        root = str(server_root)
        branch = await asyncio.to_thread(_git_run, ["git", "rev-parse", "--abbrev-ref", "HEAD"], root, logger) or "main"
        remote = await asyncio.to_thread(_git_run, ["git", "remote", "get-url", "origin"], root, logger) or ""
        default_branch_raw = await asyncio.to_thread(
            _git_run, ["git", "symbolic-ref", "--short", "HEAD@{upstream}"], root, logger
        ) or ""
        if not default_branch_raw:
            default_branch_raw = await asyncio.to_thread(
                _git_run, ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], root, logger
            ) or ""
        default_branch = default_branch_raw.replace("origin/", "").strip() or "main"
        repo = ""
        if remote:
            repo = remote.removesuffix(".git")
            repo = repo.split("github.com/")[-1].split("github.com:")[-1]
        return JSONResponse({"branch": branch, "repo": repo or "Sidar", "default_branch": default_branch})

    @router.get("/git-branches")
    async def git_branches() -> Any:
        root = str(server_root)
        branches_raw = await asyncio.to_thread(
            _git_run, ["git", "branch", "--format=%(refname:short)"], root, logger
        )
        branches = [b.strip() for b in branches_raw.split("\n") if b.strip()]
        current = await asyncio.to_thread(_git_run, ["git", "rev-parse", "--abbrev-ref", "HEAD"], root, logger) or "main"
        return JSONResponse({"branches": branches or ["main"], "current": current})

    @router.post("/set-branch")
    async def set_branch(request: Request) -> Any:
        body = await request.json()
        branch_name = body.get("branch", "").strip()
        if not branch_name:
            return JSONResponse({"success": False, "error": "Dal adı boş."}, status_code=400)
        if not _BRANCH_RE.match(branch_name):
            return JSONResponse({"success": False, "error": "Geçersiz dal adı: yalnızca harf, rakam, '/', '_', '-', '.' kullanılabilir."}, status_code=400)
        root = str(server_root)
        try:
            await asyncio.to_thread(
                subprocess.check_output,
                ["git", "checkout", branch_name],
                cwd=root,
                stderr=subprocess.STDOUT,
            )
            return JSONResponse({"success": True, "branch": branch_name})
        except subprocess.CalledProcessError as exc:
            detail = exc.output.decode().strip() if exc.output else str(exc)
            return JSONResponse({"success": False, "error": detail}, status_code=400)

    @router.get("/github-repos")
    async def github_repos(owner: str = "", q: str = "") -> Any:
        agent = await resolve_agent_instance()
        active_repo = (getattr(agent.github, "repo_name", "") or cfg.GITHUB_REPO or "").strip()
        effective_owner = owner.strip()
        if not effective_owner and "/" in active_repo:
            effective_owner = active_repo.split("/", 1)[0]
        ok, repos = agent.github.list_repos(owner=effective_owner, limit=200)
        if not ok:
            return JSONResponse({"success": False, "error": "Repo listesi alınamadı.", "repos": []}, status_code=400)
        query = q.strip().lower()
        if query:
            repos = [r for r in repos if query in r.get("full_name", "").lower()]
        repos = sorted(repos, key=lambda r: r.get("full_name", "").lower())
        return JSONResponse({"success": True, "owner": effective_owner, "repos": repos, "active_repo": active_repo})

    @router.get("/github-prs")
    async def github_prs(state: str = "open", limit: int = 10) -> Any:
        agent = await resolve_agent_instance()
        if not agent.github.is_available():
            return JSONResponse({"success": False, "error": "GitHub token ayarlanmamış.", "prs": []}, status_code=503)
        ok, prs, err = agent.github.get_pull_requests_detailed(state=state, limit=min(limit, 50))
        if not ok:
            return JSONResponse({"success": False, "error": err, "prs": []}, status_code=500)
        return JSONResponse({"success": True, "prs": prs, "repo": agent.github.repo_name})

    @router.get("/github-prs/{number}")
    async def github_pr_detail(number: int) -> Any:
        agent = await resolve_agent_instance()
        if not agent.github.is_available():
            return JSONResponse({"success": False, "error": "GitHub token ayarlanmamış."}, status_code=503)
        ok, result = agent.github.get_pull_request(number)
        if not ok:
            return JSONResponse({"success": False, "error": result}, status_code=404)
        return JSONResponse({"success": True, "detail": result})

    @router.post("/set-repo")
    async def set_repo(request: Request) -> Any:
        body = await request.json()
        repo_name = body.get("repo", "").strip()
        if not repo_name:
            return JSONResponse({"success": False, "error": "Depo adı boş."}, status_code=400)
        agent = await resolve_agent_instance()
        ok, msg = agent.github.set_repo(repo_name)
        if ok:
            cfg.GITHUB_REPO = repo_name
        return JSONResponse({"success": ok, "message": msg})

    return router
