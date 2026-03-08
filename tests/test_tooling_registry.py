import pytest
import importlib.util
from pathlib import Path


pytest.importorskip("pydantic")
spec = importlib.util.spec_from_file_location("sidar_tooling", Path("agent/tooling.py"))
tooling = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(tooling)


def test_parse_tool_argument_supports_json_schema_payloads():
    parsed = tooling.parse_tool_argument(
        "write_file",
        '{"path": "core/example.py", "content": "print(1)"}',
    )
    assert isinstance(parsed, tooling.WriteFileSchema)
    assert parsed.path == "core/example.py"
    assert parsed.content == "print(1)"


def test_parse_tool_argument_supports_legacy_delimiter_payloads():
    parsed = tooling.parse_tool_argument(
        "github_create_pr",
        "feat: başlık|||gövde|||feature/branch|||main",
    )
    assert isinstance(parsed, tooling.GithubCreatePRSchema)
    assert parsed.head == "feature/branch"
    assert parsed.base == "main"


def test_schema_registry_contains_core_migrated_tools():
    assert tooling.TOOL_ARG_SCHEMAS["write_file"] is tooling.WriteFileSchema
    assert "github_create_pr" in tooling.TOOL_ARG_SCHEMAS


def test_issue_tool_schemas_and_dispatch_are_registered():
    assert "github_list_issues" in tooling.TOOL_ARG_SCHEMAS
    assert "github_create_issue" in tooling.TOOL_ARG_SCHEMAS
    assert "github_comment_issue" in tooling.TOOL_ARG_SCHEMAS
    assert "github_close_issue" in tooling.TOOL_ARG_SCHEMAS

    parsed_list = tooling.parse_tool_argument("github_list_issues", "open|||5")
    assert isinstance(parsed_list, tooling.GithubListIssuesSchema)
    assert parsed_list.limit == 5

    parsed_create = tooling.parse_tool_argument("github_create_issue", "Başlık|||Açıklama")
    assert isinstance(parsed_create, tooling.GithubCreateIssueSchema)
    assert parsed_create.title == "Başlık"

    parsed_comment = tooling.parse_tool_argument("github_comment_issue", "42|||Not")
    assert isinstance(parsed_comment, tooling.GithubCommentIssueSchema)
    assert parsed_comment.number == 42

    parsed_close = tooling.parse_tool_argument("github_close_issue", "42")
    assert isinstance(parsed_close, tooling.GithubCloseIssueSchema)
    assert parsed_close.number == 42



def test_pr_diff_tool_schema_and_legacy_parse_are_registered():
    assert "github_pr_diff" in tooling.TOOL_ARG_SCHEMAS

    parsed = tooling.parse_tool_argument("github_pr_diff", "42")
    assert isinstance(parsed, tooling.GithubPRDiffSchema)
    assert parsed.number == 42


def test_scan_project_todos_schema_and_parse_registered():
    assert "scan_project_todos" in tooling.TOOL_ARG_SCHEMAS

    parsed = tooling.parse_tool_argument("scan_project_todos", "core|||.py,.md")
    assert isinstance(parsed, tooling.ScanProjectTodosSchema)
    assert parsed.directory == "core"
    assert parsed.extensions == [".py", ".md"]
