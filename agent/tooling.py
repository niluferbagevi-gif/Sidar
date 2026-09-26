"""Sidar araç kayıt/argüman şema yardımcıları."""

import json
from typing import Any

from pydantic import BaseModel, Field


class WriteFileSchema(BaseModel):
    """Arguments of ``write_file``: target path and full content."""

    path: str
    content: str


class PatchFileSchema(BaseModel):
    """Arguments of ``patch_file``: replace ``old_text`` with ``new_text`` in a file."""

    path: str
    old_text: str
    new_text: str


class GithubListFilesSchema(BaseModel):
    """Arguments of ``github_list_files``: directory path and optional branch."""

    path: str = ""
    branch: str | None = None


class GithubWriteSchema(BaseModel):
    """Arguments of ``github_write``: file path, content, commit message and branch."""

    path: str
    content: str
    commit_message: str
    branch: str | None = None


class GithubCreateBranchSchema(BaseModel):
    """Arguments of ``github_create_branch``: new branch name and optional base."""

    branch_name: str
    from_branch: str | None = None


class GithubCreatePRSchema(BaseModel):
    """Arguments of ``github_create_pr``: title, body, head and optional base branch."""

    title: str
    body: str
    head: str
    base: str | None = None


class GithubListPRsSchema(BaseModel):
    """Arguments of ``github_list_prs``: state filter and result limit."""

    state: str = "open"
    limit: int = 10


class GithubListIssuesSchema(BaseModel):
    """Arguments of ``github_list_issues``: state filter and result limit."""

    state: str = "open"
    limit: int = 10


class GithubCreateIssueSchema(BaseModel):
    """Arguments of ``github_create_issue``: title and body."""

    title: str
    body: str


class GithubCommentIssueSchema(BaseModel):
    """Arguments of ``github_comment_issue``: issue number and comment body."""

    number: int
    body: str


class GithubCloseIssueSchema(BaseModel):
    """Arguments of ``github_close_issue``: issue number."""

    number: int


class GithubPRDiffSchema(BaseModel):
    """Arguments of ``github_pr_diff``: pull request number."""

    number: int = Field(description="Diff (fark) kodu alınacak PR numarası")


class ScanProjectTodosSchema(BaseModel):
    """Arguments of ``scan_project_todos``: directory and file extensions to scan."""

    directory: str | None = Field(
        default=None, description="Taranacak alt dizin (boş bırakılırsa tüm proje taranır)"
    )
    extensions: list[str] | None = Field(
        default=None, description="Taranacak dosya uzantıları listesi (Örn: ['.py', '.js'])"
    )


class LspDiagnosticsSchema(BaseModel):
    """Arguments of ``lsp_diagnostics``: files to diagnose."""

    paths: list[str] | None = Field(
        default=None, description="LSP diagnostics çalıştırılacak dosya yolları"
    )


class LspRenameSchema(BaseModel):
    """Arguments of ``lsp_rename``: symbol position, new name and whether to apply."""

    path: str
    line: int
    character: int
    new_name: str
    apply: bool = False


class SocialPublishSchema(BaseModel):
    """Arguments of ``publish_social``: platform, text and optional destination/media/link."""

    platform: str
    text: str
    destination: str = ""
    media_url: str = ""
    link_url: str = ""


class InstagramPublishSchema(BaseModel):
    """Arguments of ``publish_instagram_post``: caption and image URL."""

    caption: str
    image_url: str


class FacebookPublishSchema(BaseModel):
    """Arguments of ``publish_facebook_post``: message and optional link."""

    message: str
    link_url: str = ""


class WhatsAppMessageSchema(BaseModel):
    """Arguments of ``send_whatsapp_message``: recipient, text and link preview flag."""

    to: str
    text: str
    preview_url: bool = False


class LandingPageDraftSchema(BaseModel):
    """Arguments of ``build_landing_page``: brand, offer, audience, CTA and sections."""

    brand_name: str
    offer: str
    audience: str
    call_to_action: str
    tone: str = "professional"
    sections: list[str] | None = None
    campaign_id: int | None = None
    tenant_id: str = "default"
    store_asset: bool = False
    asset_title: str = "Landing Page Taslağı"
    channel: str = "web"


class CampaignCopySchema(BaseModel):
    """Arguments of ``generate_campaign_copy``: campaign, objective, audience and channels."""

    campaign_name: str
    objective: str
    audience: str
    channels: list[str] | None = None
    offer: str = ""
    tone: str = "professional"
    call_to_action: str = ""
    campaign_id: int | None = None
    tenant_id: str = "default"
    store_asset: bool = False
    asset_title: str = "Kampanya Kopyası"


class VideoInsightIngestSchema(BaseModel):
    """Arguments of ``ingest_video_insights``: source URL and frame sampling options."""

    source_url: str
    prompt: str = ""
    language: str = ""
    session_id: str = "marketing"
    max_frames: int = 6
    frame_interval_seconds: float = 5.0


class MarketingCampaignCreateSchema(BaseModel):
    """Arguments of ``create_marketing_campaign``: campaign fields and metadata."""

    tenant_id: str = "default"
    name: str
    channel: str = ""
    objective: str = ""
    status: str = "draft"
    owner_user_id: str = ""
    budget: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    campaign_id: int | None = None


class ContentAssetCreateSchema(BaseModel):
    """Arguments of ``store_content_asset``: campaign id, asset type, title and content."""

    campaign_id: int
    tenant_id: str = "default"
    asset_type: str
    title: str
    content: str
    channel: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class OperationChecklistSchema(BaseModel):
    """Arguments of ``create_operation_checklist``: title, items, status and owner."""

    tenant_id: str = "default"
    title: str
    items: list[Any] = Field(default_factory=list)
    status: str = "pending"
    owner_user_id: str = ""
    campaign_id: int | None = None


class ServiceOperationsPlanSchema(BaseModel):
    """Arguments of ``plan_service_operations``: service, menu, vendors and timeline."""

    tenant_id: str = "default"
    campaign_id: int | None = None
    campaign_name: str = ""
    service_name: str = ""
    audience: str = ""
    menu_plan: dict[str, list[str]] = Field(default_factory=dict)
    vendor_assignments: dict[str, str] = Field(default_factory=dict)
    timeline: list[str] = Field(default_factory=list)
    notes: str = ""
    owner_user_id: str = ""
    persist_checklist: bool = True
    checklist_title: str = "Operasyon Planı"


TOOL_ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "write_file": WriteFileSchema,
    "patch_file": PatchFileSchema,
    "github_list_files": GithubListFilesSchema,
    "github_write": GithubWriteSchema,
    "github_create_branch": GithubCreateBranchSchema,
    "github_create_pr": GithubCreatePRSchema,
    "github_list_prs": GithubListPRsSchema,
    "github_list_issues": GithubListIssuesSchema,
    "github_create_issue": GithubCreateIssueSchema,
    "github_comment_issue": GithubCommentIssueSchema,
    "github_close_issue": GithubCloseIssueSchema,
    "github_pr_diff": GithubPRDiffSchema,
    "scan_project_todos": ScanProjectTodosSchema,
    "lsp_diagnostics": LspDiagnosticsSchema,
    "lsp_rename": LspRenameSchema,
    "publish_social": SocialPublishSchema,
    "publish_instagram_post": InstagramPublishSchema,
    "publish_facebook_post": FacebookPublishSchema,
    "send_whatsapp_message": WhatsAppMessageSchema,
    "build_landing_page": LandingPageDraftSchema,
    "generate_campaign_copy": CampaignCopySchema,
    "ingest_video_insights": VideoInsightIngestSchema,
    "create_marketing_campaign": MarketingCampaignCreateSchema,
    "store_content_asset": ContentAssetCreateSchema,
    "create_operation_checklist": OperationChecklistSchema,
    "plan_service_operations": ServiceOperationsPlanSchema,
}


def parse_tool_argument(tool_name: str, raw_arg: str) -> Any:
    """Şema tanımlı araçlar için yalnızca JSON object argümanı typed modele dönüştür."""
    schema = TOOL_ARG_SCHEMAS.get(tool_name)
    if schema is None:
        return raw_arg

    text = (raw_arg or "").strip()
    if not text:
        return schema.model_validate({})

    # Yalnızca JSON object formatı desteklenir.
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return schema.model_validate(payload)
        raise ValueError("Argüman JSON object olmalıdır")
    except json.JSONDecodeError as err:
        raise ValueError(
            f"'{tool_name}' için legacy '|||' formatı kaldırıldı. JSON object argümanı gönderin."
        ) from err
