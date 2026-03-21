"""Sidar araç kayıt/argüman şema yardımcıları."""

import json
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field


class WriteFileSchema(BaseModel):
    path: str
    content: str


class PatchFileSchema(BaseModel):
    path: str
    old_text: str
    new_text: str


class GithubListFilesSchema(BaseModel):
    path: str = ""
    branch: Optional[str] = None


class GithubWriteSchema(BaseModel):
    path: str
    content: str
    commit_message: str
    branch: Optional[str] = None


class GithubCreateBranchSchema(BaseModel):
    branch_name: str
    from_branch: Optional[str] = None


class GithubCreatePRSchema(BaseModel):
    title: str
    body: str
    head: str
    base: Optional[str] = None


class GithubListPRsSchema(BaseModel):
    state: str = "open"
    limit: int = 10


class GithubListIssuesSchema(BaseModel):
    state: str = "open"
    limit: int = 10


class GithubCreateIssueSchema(BaseModel):
    title: str
    body: str


class GithubCommentIssueSchema(BaseModel):
    number: int
    body: str


class GithubCloseIssueSchema(BaseModel):
    number: int


class GithubPRDiffSchema(BaseModel):
    number: int = Field(description="Diff (fark) kodu alınacak PR numarası")


class ScanProjectTodosSchema(BaseModel):
    directory: Optional[str] = Field(default=None, description="Taranacak alt dizin (boş bırakılırsa tüm proje taranır)")
    extensions: Optional[List[str]] = Field(default=None, description="Taranacak dosya uzantıları listesi (Örn: ['.py', '.js'])")


class LspDiagnosticsSchema(BaseModel):
    paths: Optional[List[str]] = Field(default=None, description="LSP diagnostics çalıştırılacak dosya yolları")


class LspRenameSchema(BaseModel):
    path: str
    line: int
    character: int
    new_name: str
    apply: bool = False


class SocialPublishSchema(BaseModel):
    platform: str
    text: str
    destination: str = ""
    media_url: str = ""
    link_url: str = ""


class LandingPageDraftSchema(BaseModel):
    brand_name: str
    offer: str
    audience: str
    call_to_action: str
    tone: str = "professional"
    sections: Optional[List[str]] = None


class CampaignCopySchema(BaseModel):
    campaign_name: str
    objective: str
    audience: str
    channels: Optional[List[str]] = None
    offer: str = ""
    tone: str = "professional"
    call_to_action: str = ""


TOOL_ARG_SCHEMAS: Dict[str, Type[BaseModel]] = {
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
    "build_landing_page": LandingPageDraftSchema,
    "generate_campaign_copy": CampaignCopySchema,
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
    except json.JSONDecodeError:
        raise ValueError(
            f"'{tool_name}' için legacy '|||' formatı kaldırıldı. "
            "JSON object argümanı gönderin."
        )
