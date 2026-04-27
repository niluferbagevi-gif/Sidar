"""Jira Entegrasyon Yöneticisi (v6.0)

Jira Cloud REST API v3 üzerinden issue yönetimi sağlar.
jira paketi kurulu değilse httpx ile doğrudan REST API kullanılır.

Kullanım:
    mgr = JiraManager(url=cfg.JIRA_URL, token=cfg.JIRA_TOKEN, email=cfg.JIRA_EMAIL)
    ok, issue, err = await mgr.create_issue(project="PROJ", summary="Bug: ...", issue_type="Bug")
    issues = await mgr.search_issues('project = PROJ AND status = "To Do"')
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_TIMEOUT = 20.0


class _JiraRetryableError(RuntimeError):
    """Rate limit / geçici servis hatalarında retry tetiklemek için iç hata türü."""


class JiraManager:
    """
    Jira Cloud REST API v3 istemcisi.

    Kimlik doğrulama: Basic Auth (e-posta + API token) veya Bearer token.
    """

    def __init__(
        self,
        url: str = "",
        token: str = "",
        email: str = "",
        default_project: str = "",
        base_url: str = "",
        api_token: str = "",
    ) -> None:
        resolved_url = url or base_url
        resolved_token = token or api_token
        self.url = (resolved_url or "").rstrip("/")
        self.token = (resolved_token or "").strip()
        self.email = (email or "").strip()
        self.default_project = (default_project or "").strip()
        self._available = False
        self._auth: tuple[str, str] | None = None
        self._headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._init_client()

    # ─────────────────────────────────────────────
    #  BAŞLATMA
    # ─────────────────────────────────────────────

    def _init_client(self) -> None:
        if not self.url or not self.token:
            logger.debug("Jira URL veya token ayarlanmamış. Jira özellikleri devre dışı.")
            return
        if self.email:
            # Atlassian Cloud: e-posta + API token
            self._auth = (self.email, self.token)
        else:
            # Bearer token (Jira Data Center / Server)
            self._headers["Authorization"] = f"Bearer {self.token}"
        self._available = True
        logger.info("Jira bağlantısı yapılandırıldı: %s", self.url)

    def is_available(self) -> bool:
        return self._available

    # ─────────────────────────────────────────────
    #  YARDIMCI HTTP
    # ─────────────────────────────────────────────

    async def _request(self, method: str, endpoint: str, **kwargs) -> tuple[bool, Any, str]:
        if not self._available:
            return False, None, "Jira bağlantısı mevcut değil"
        url = f"{self.url}/rest/api/3/{endpoint.lstrip('/')}"
        try:
            async for attempt in AsyncRetrying(
                reraise=True,
                stop=stop_after_attempt(5),
                wait=wait_exponential(multiplier=1, min=1, max=16),
                retry=retry_if_exception_type(_JiraRetryableError),
            ):
                with attempt:
                    async with httpx.AsyncClient(
                        timeout=_TIMEOUT, auth=self._auth, headers=self._headers
                    ) as client:
                        try:
                            resp = await client.request(method, url, **kwargs)
                        except (httpx.TimeoutException, httpx.TransportError) as exc:
                            raise _JiraRetryableError(str(exc)) from exc
                    if resp.status_code in (429, 502, 503, 504):
                        raise _JiraRetryableError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            if resp.status_code in (200, 201, 204):
                body = resp.json() if resp.content else {}
                return True, body, ""
            return False, None, f"HTTP {resp.status_code}: {resp.text[:300]}"
        except _JiraRetryableError as exc:
            logger.error("Jira._request retry limiti aşıldı [%s %s]: %s", method, endpoint, exc)
            return False, None, str(exc)
        except Exception as exc:
            logger.error("Jira._request hatası [%s %s]: %s", method, endpoint, exc)
            return False, None, str(exc)

    # ─────────────────────────────────────────────
    #  ISSUE İŞLEMLERİ
    # ─────────────────────────────────────────────

    async def create_issue(
        self,
        summary: str,
        project: str | None = None,
        issue_type: str = "Task",
        description: str = "",
        priority: str = "Medium",
        labels: list[str] | None = None,
        assignee_account_id: str | None = None,
    ) -> tuple[bool, dict, str]:
        """Yeni Jira issue oluşturur. Döner: (success, issue_dict, error)"""
        proj = project or self.default_project
        if not proj:
            return False, {}, "Proje anahtarı belirtilmedi"

        fields: dict[str, Any] = {
            "project": {"key": proj},
            "summary": summary,
            "issuetype": {"name": issue_type},
            "priority": {"name": priority},
        }
        if description:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            }
        if labels:
            fields["labels"] = labels
        if assignee_account_id:
            fields["assignee"] = {"accountId": assignee_account_id}

        ok, data, err = await self._request("POST", "issue", json={"fields": fields})
        return ok, data or {}, err

    async def get_issue(self, issue_key: str) -> tuple[bool, dict, str]:
        """Issue detaylarını döner."""
        ok, data, err = await self._request("GET", f"issue/{issue_key}")
        return ok, data or {}, err

    async def update_issue(
        self,
        issue_key: str,
        fields: dict[str, Any],
    ) -> tuple[bool, str]:
        """Issue alanlarını günceller. Döner: (success, error)"""
        ok, _, err = await self._request("PUT", f"issue/{issue_key}", json={"fields": fields})
        return ok, err

    async def transition_issue(
        self,
        issue_key: str,
        transition_name: str,
    ) -> tuple[bool, str]:
        """Issue durumunu geçiş adıyla değiştirir (örn. 'In Progress', 'Done')."""
        ok, data, err = await self._request("GET", f"issue/{issue_key}/transitions")
        if not ok:
            return False, err
        transitions = (data or {}).get("transitions", [])
        match = next((t for t in transitions if t["name"].lower() == transition_name.lower()), None)
        if not match:
            available = [t["name"] for t in transitions]
            return False, f"Geçiş bulunamadı: '{transition_name}'. Mevcut: {available}"
        ok, _, err = await self._request(
            "POST",
            f"issue/{issue_key}/transitions",
            json={"transition": {"id": match["id"]}},
        )
        return ok, err

    async def add_comment(self, issue_key: str, comment: str) -> tuple[bool, dict, str]:
        """Issue'ya yorum ekler."""
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": comment}],
                    }
                ],
            }
        }
        ok, data, err = await self._request("POST", f"issue/{issue_key}/comment", json=payload)
        return ok, data or {}, err

    async def search_issues(
        self,
        jql: str,
        fields: list[str] | None = None,
        max_results: int = 50,
    ) -> tuple[bool, list[dict], str]:
        """JQL sorgusuyla issue arar."""
        params: dict[str, Any] = {
            "jql": jql,
            "maxResults": min(max_results, 100),
            "fields": fields or ["summary", "status", "assignee", "priority", "issuetype"],
        }
        ok, data, err = await self._request("GET", "search", params=params)
        if not ok:
            return False, [], err
        issues = (data or {}).get("issues", [])
        simplified = [
            {
                "key": i.get("key", ""),
                "summary": (i.get("fields") or {}).get("summary", ""),
                "status": ((i.get("fields") or {}).get("status") or {}).get("name", ""),
                "assignee": (
                    ((i.get("fields") or {}).get("assignee") or {}).get("displayName", "")
                ),
                "priority": ((i.get("fields") or {}).get("priority") or {}).get("name", ""),
                "type": ((i.get("fields") or {}).get("issuetype") or {}).get("name", ""),
            }
            for i in issues
        ]
        return True, simplified, ""

    # ─────────────────────────────────────────────
    #  PROJE BİLGİSİ
    # ─────────────────────────────────────────────

    async def list_projects(self) -> tuple[bool, list[dict], str]:
        """Erişilebilir projeleri listeler."""
        ok, data, err = await self._request("GET", "project")
        if not ok:
            return False, [], err
        projects = [
            {"key": p.get("key", ""), "name": p.get("name", ""), "id": p.get("id", "")}
            for p in (data or [])
        ]
        return True, projects, ""

    async def get_project_statuses(self, project_key: str) -> tuple[bool, list[str], str]:
        """Projedeki olası issue durumlarını döner."""
        ok, data, err = await self._request("GET", f"project/{project_key}/statuses")
        if not ok:
            return False, [], err
        statuses: list[str] = []
        for issue_type in data or []:
            for s in issue_type.get("statuses", []):
                name = s.get("name", "")
                if name and name not in statuses:
                    statuses.append(name)
        return True, statuses, ""
