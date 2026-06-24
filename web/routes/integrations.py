from __future__ import annotations

import inspect
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from web.routes import LegacyExportRouter


class SlackSendRequest(BaseModel):
    text: str = Field(..., description="Gönderilecek mesaj metni")
    channel: str | None = Field(None, description="Hedef kanal (ör. #general)")
    thread_ts: str | None = Field(None, description="Thread zaman damgası")


class JiraCreateRequest(BaseModel):
    project_key: str = Field(..., description="Jira proje anahtarı (ör. SIDAR)")
    summary: str = Field(..., description="Issue başlığı")
    description: str | None = Field(None, description="Issue açıklaması")
    issue_type: str = Field("Task", description="Issue türü: Task, Bug, Story")
    priority: str | None = Field(None, description="Öncelik: Highest, High, Medium, Low")


class TeamsSendRequest(BaseModel):
    text: str = Field(..., description="Gönderilecek mesaj metni")
    title: str | None = Field(None, description="Mesaj başlığı")


def build_integrations_router(
    *,
    cfg: Any,
    slack_cache: dict[str, Any],
    jira_cache: dict[str, Any],
    teams_cache: dict[str, Any],
) -> LegacyExportRouter:
    router = LegacyExportRouter()

    async def get_slack_manager() -> Any:
        if slack_cache.get("instance") is None:
            from managers.slack_manager import SlackManager

            slack_cache["instance"] = SlackManager(
                token=getattr(cfg, "SLACK_TOKEN", ""),
                webhook_url=getattr(cfg, "SLACK_WEBHOOK_URL", ""),
                default_channel=getattr(cfg, "SLACK_DEFAULT_CHANNEL", ""),
            )
            await slack_cache["instance"].initialize()
        return slack_cache["instance"]

    def get_jira_manager() -> Any:
        if jira_cache.get("instance") is None:
            from managers.jira_manager import JiraManager

            jira_cache["instance"] = JiraManager(
                base_url=getattr(cfg, "JIRA_BASE_URL", ""),
                email=getattr(cfg, "JIRA_EMAIL", ""),
                api_token=getattr(cfg, "JIRA_API_TOKEN", ""),
                default_project=getattr(cfg, "JIRA_DEFAULT_PROJECT", ""),
            )
        return jira_cache["instance"]

    def get_teams_manager() -> Any:
        if teams_cache.get("instance") is None:
            from managers.teams_manager import TeamsManager

            teams_cache["instance"] = TeamsManager(
                webhook_url=getattr(cfg, "TEAMS_WEBHOOK_URL", "")
            )
        return teams_cache["instance"]

    @router.post("/api/integrations/slack/send", summary="Slack Mesajı Gönder", tags=["Slack"])
    async def api_slack_send(req: SlackSendRequest) -> Any:
        maybe_mgr = get_slack_manager()
        mgr = await maybe_mgr if inspect.isawaitable(maybe_mgr) else maybe_mgr
        if not mgr.is_available():
            raise HTTPException(status_code=503, detail="Slack entegrasyonu yapılandırılmamış.")
        ok, err = await mgr.send_message(
            text=req.text, channel=req.channel, thread_ts=req.thread_ts
        )
        if not ok:
            raise HTTPException(status_code=502, detail=f"Slack hatası: {err}")
        return JSONResponse({"success": True})

    @router.get("/api/integrations/slack/channels", summary="Slack Kanal Listesi", tags=["Slack"])
    async def api_slack_channels() -> Any:
        maybe_mgr = get_slack_manager()
        mgr = await maybe_mgr if inspect.isawaitable(maybe_mgr) else maybe_mgr
        if not mgr.is_available():
            raise HTTPException(status_code=503, detail="Slack entegrasyonu yapılandırılmamış.")
        ok, channels, err = await mgr.list_channels()
        if not ok:
            raise HTTPException(status_code=502, detail=f"Slack hatası: {err}")
        return JSONResponse({"success": True, "channels": channels})

    @router.post("/api/integrations/jira/issue", summary="Jira Issue Oluştur", tags=["Jira"])
    async def api_jira_create_issue(req: JiraCreateRequest) -> Any:
        mgr = get_jira_manager()
        if not mgr.is_available():
            raise HTTPException(status_code=503, detail="Jira entegrasyonu yapılandırılmamış.")
        ok, issue, err = await mgr.create_issue(
            project_key=req.project_key,
            summary=req.summary,
            description=req.description or "",
            issue_type=req.issue_type,
            priority=req.priority,
        )
        if not ok:
            raise HTTPException(status_code=502, detail=f"Jira hatası: {err}")
        return JSONResponse({"success": True, "issue": issue})

    @router.get("/api/integrations/jira/issues", summary="Jira Issue Arama", tags=["Jira"])
    async def api_jira_search_issues(jql: str = "", max_results: int = 20) -> Any:
        mgr = get_jira_manager()
        if not mgr.is_available():
            raise HTTPException(status_code=503, detail="Jira entegrasyonu yapılandırılmamış.")
        ok, issues, err = await mgr.search_issues(jql=jql, max_results=max_results)
        if not ok:
            raise HTTPException(status_code=502, detail=f"Jira hatası: {err}")
        return JSONResponse({"success": True, "issues": issues, "total": len(issues)})

    @router.post("/api/integrations/teams/send", summary="Teams Mesajı Gönder", tags=["Teams"])
    async def api_teams_send(req: TeamsSendRequest) -> Any:
        mgr = get_teams_manager()
        if not mgr.is_available():
            raise HTTPException(status_code=503, detail="Teams entegrasyonu yapılandırılmamış.")
        ok, err = await mgr.send_message(text=req.text, title=req.title or "Sidar Bildirimi")
        if not ok:
            raise HTTPException(status_code=502, detail=f"Teams hatası: {err}")
        return JSONResponse({"success": True})

    router.legacy_exports = {
        "api_slack_send": api_slack_send,
        "api_slack_channels": api_slack_channels,
        "api_jira_create_issue": api_jira_create_issue,
        "api_jira_search_issues": api_jira_search_issues,
        "api_teams_send": api_teams_send,
        "_get_slack_manager": get_slack_manager,
        "_get_jira_manager": get_jira_manager,
        "_get_teams_manager": get_teams_manager,
    }
    return router
