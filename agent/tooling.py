"""Sidar araç kayıt/argüman şema yardımcıları."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Type

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
}


def parse_tool_argument(tool_name: str, raw_arg: str) -> Any:
    """Şema tanımlı araçlar için JSON/legacy argümanı typed modele dönüştür."""
    schema = TOOL_ARG_SCHEMAS.get(tool_name)
    if schema is None:
        return raw_arg

    text = (raw_arg or "").strip()
    if not text:
        return schema.model_validate({})

    # 1) Öncelik: doğrudan JSON object
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return schema.model_validate(payload)
    except json.JSONDecodeError:
        pass

    # 2) Legacy delimiter formatları
    parts = text.split("|||")
    if schema is WriteFileSchema:
        if len(parts) < 2:
            raise ValueError("Argüman formatı geçersiz")
        return WriteFileSchema(path=parts[0].strip(), content=parts[1])

    if schema is PatchFileSchema:
        if len(parts) < 3:
            raise ValueError("Argüman formatı geçersiz")
        return PatchFileSchema(path=parts[0].strip(), old_text=parts[1], new_text=parts[2])

    if schema is GithubListFilesSchema:
        return GithubListFilesSchema(
            path=parts[0].strip() if parts else "",
            branch=parts[1].strip() if len(parts) > 1 and parts[1].strip() else None,
        )

    if schema is GithubWriteSchema:
        if len(parts) < 3:
            raise ValueError("Argüman formatı geçersiz")
        return GithubWriteSchema(
            path=parts[0].strip(),
            content=parts[1],
            commit_message=parts[2].strip(),
            branch=parts[3].strip() if len(parts) > 3 and parts[3].strip() else None,
        )

    if schema is GithubCreateBranchSchema:
        if not parts or not parts[0].strip():
            raise ValueError("Argüman formatı geçersiz")
        return GithubCreateBranchSchema(
            branch_name=parts[0].strip(),
            from_branch=parts[1].strip() if len(parts) > 1 and parts[1].strip() else None,
        )

    if schema is GithubCreatePRSchema:
        if len(parts) < 3:
            raise ValueError("Argüman formatı geçersiz")
        return GithubCreatePRSchema(
            title=parts[0].strip(),
            body=parts[1],
            head=parts[2].strip(),
            base=parts[3].strip() if len(parts) > 3 and parts[3].strip() else None,
        )

    if schema is GithubListPRsSchema:
        state = parts[0].strip() if parts and parts[0].strip() else "open"
        try:
            limit = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else 10
        except ValueError:
            limit = 10
        return GithubListPRsSchema(state=state, limit=limit)

    if schema is GithubListIssuesSchema:
        state = parts[0].strip() if parts and parts[0].strip() else "open"
        try:
            limit = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else 10
        except ValueError:
            limit = 10
        return GithubListIssuesSchema(state=state, limit=limit)

    if schema is GithubCreateIssueSchema:
        if len(parts) < 2:
            raise ValueError("Argüman formatı geçersiz")
        return GithubCreateIssueSchema(title=parts[0].strip(), body=parts[1])

    if schema is GithubCommentIssueSchema:
        if len(parts) < 2:
            raise ValueError("Argüman formatı geçersiz")
        return GithubCommentIssueSchema(number=int(parts[0].strip()), body=parts[1])

    if schema is GithubCloseIssueSchema:
        if not parts or not parts[0].strip():
            raise ValueError("Argüman formatı geçersiz")
        return GithubCloseIssueSchema(number=int(parts[0].strip()))

    if schema is GithubPRDiffSchema:
        if not parts or not parts[0].strip():
            raise ValueError("Argüman formatı geçersiz")
        return GithubPRDiffSchema(number=int(parts[0].strip()))

    if schema is ScanProjectTodosSchema:
        directory = parts[0].strip() if parts and parts[0].strip() else None
        ext_list = None
        if len(parts) > 1 and parts[1].strip():
            ext_list = [e.strip() for e in parts[1].split(",") if e.strip()]
        return ScanProjectTodosSchema(directory=directory, extensions=ext_list)

    return raw_arg


def build_tool_dispatch(agent: Any) -> Dict[str, Callable[[Any], Any]]:
    """Araç tablosunu dış modülde üretir (tek source-of-truth)."""
    return {
        "list_dir":               agent._tool_list_dir,
        "read_file":              agent._tool_read_file,
        "write_file":             agent._tool_write_file,
        "patch_file":             agent._tool_patch_file,
        "execute_code":           agent._tool_execute_code,
        "audit":                  agent._tool_audit,
        "health":                 agent._tool_health,
        "gpu_optimize":           agent._tool_gpu_optimize,
        "github_commits":         agent._tool_github_commits,
        "github_info":            agent._tool_github_info,
        "github_read":            agent._tool_github_read,
        "github_list_files":      agent._tool_github_list_files,
        "github_write":           agent._tool_github_write,
        "github_create_branch":   agent._tool_github_create_branch,
        "github_create_pr":       agent._tool_github_create_pr,
        "github_search_code":     agent._tool_github_search_code,
        "github_list_prs":        agent._tool_github_list_prs,
        "github_get_pr":          agent._tool_github_get_pr,
        "github_comment_pr":      agent._tool_github_comment_pr,
        "github_close_pr":        agent._tool_github_close_pr,
        "github_pr_files":        agent._tool_github_pr_files,
        "github_smart_pr":        agent._tool_github_smart_pr,
        "github_list_issues":    agent._tool_github_list_issues,
        "github_create_issue":   agent._tool_github_create_issue,
        "github_comment_issue":  agent._tool_github_comment_issue,
        "github_close_issue":    agent._tool_github_close_issue,
        "github_pr_diff":       agent._tool_github_pr_diff,
        "web_search":             agent._tool_web_search,
        "fetch_url":              agent._tool_fetch_url,
        "search_docs":            agent._tool_search_docs,
        "search_stackoverflow":   agent._tool_search_stackoverflow,
        "pypi":                   agent._tool_pypi,
        "pypi_compare":           agent._tool_pypi_compare,
        "npm":                    agent._tool_npm,
        "gh_releases":            agent._tool_gh_releases,
        "gh_latest":              agent._tool_gh_latest,
        "docs_search":            agent._tool_docs_search,
        "docs_add":               agent._tool_docs_add,
        "docs_add_file":          agent._tool_docs_add_file,
        "docs_list":              agent._tool_docs_list,
        "docs_delete":            agent._tool_docs_delete,
        "run_shell":              agent._tool_run_shell,
        "bash":                   agent._tool_run_shell,
        "shell":                  agent._tool_run_shell,
        "glob_search":            agent._tool_glob_search,
        "grep_files":             agent._tool_grep_files,
        "grep":                   agent._tool_grep_files,
        "ls":                     agent._tool_list_dir,
        "todo_write":             agent._tool_todo_write,
        "todo_read":              agent._tool_todo_read,
        "todo_update":            agent._tool_todo_update,
        "scan_project_todos":    agent._tool_scan_project_todos,
        "get_config":             agent._tool_get_config,
        "print_config_summary":   agent._tool_get_config,
        "subtask":                agent._tool_subtask,
        "agent":                  agent._tool_subtask,
    }