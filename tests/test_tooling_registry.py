import pytest


pytest.importorskip("pydantic")
import agent.tooling as tooling


class _DummySchema(tooling.BaseModel):
    value: str | None = None


def test_parse_tool_argument_supports_json_schema_payloads():
    parsed = tooling.parse_tool_argument(
        "write_file",
        '{"path": "core/example.py", "content": "print(1)"}',
    )
    assert isinstance(parsed, tooling.WriteFileSchema)
    assert parsed.path == "core/example.py"
    assert parsed.content == "print(1)"


def test_parse_tool_argument_requires_json_for_schema_tools():
    with pytest.raises(ValueError, match=r"legacy '\|\|\|' formatı kaldırıldı"):
        tooling.parse_tool_argument(
            "github_create_pr",
            "feat: başlık|||gövde|||feature/branch|||main",
        )


def test_schema_registry_contains_core_migrated_tools():
    assert tooling.TOOL_ARG_SCHEMAS["write_file"] is tooling.WriteFileSchema
    assert "github_create_pr" in tooling.TOOL_ARG_SCHEMAS


def test_issue_tool_schemas_are_registered_and_parse_json_payloads():
    assert "github_list_issues" in tooling.TOOL_ARG_SCHEMAS
    assert "github_create_issue" in tooling.TOOL_ARG_SCHEMAS
    assert "github_comment_issue" in tooling.TOOL_ARG_SCHEMAS
    assert "github_close_issue" in tooling.TOOL_ARG_SCHEMAS

    parsed_list = tooling.parse_tool_argument("github_list_issues", '{"state":"open","limit":5}')
    assert isinstance(parsed_list, tooling.GithubListIssuesSchema)
    assert parsed_list.limit == 5

    parsed_create = tooling.parse_tool_argument("github_create_issue", '{"title":"Başlık","body":"Açıklama"}')
    assert isinstance(parsed_create, tooling.GithubCreateIssueSchema)
    assert parsed_create.title == "Başlık"

    parsed_comment = tooling.parse_tool_argument("github_comment_issue", '{"number":42,"body":"Not"}')
    assert isinstance(parsed_comment, tooling.GithubCommentIssueSchema)
    assert parsed_comment.number == 42

    parsed_close = tooling.parse_tool_argument("github_close_issue", '{"number":42}')
    assert isinstance(parsed_close, tooling.GithubCloseIssueSchema)
    assert parsed_close.number == 42


def test_pr_diff_tool_schema_and_json_parse_are_registered():
    assert "github_pr_diff" in tooling.TOOL_ARG_SCHEMAS

    parsed = tooling.parse_tool_argument("github_pr_diff", '{"number":42}')
    assert isinstance(parsed, tooling.GithubPRDiffSchema)
    assert parsed.number == 42


def test_scan_project_todos_schema_and_parse_registered():
    assert "scan_project_todos" in tooling.TOOL_ARG_SCHEMAS

    parsed = tooling.parse_tool_argument("scan_project_todos", '{"directory":"core","extensions":[".py",".md"]}')
    assert isinstance(parsed, tooling.ScanProjectTodosSchema)
    assert parsed.directory == "core"
    assert parsed.extensions == [".py", ".md"]


def test_parse_tool_argument_error_and_default_fallbacks():
    with pytest.raises(ValueError):
        tooling.parse_tool_argument("patch_file", "path|||old")

    with pytest.raises(ValueError):
        tooling.parse_tool_argument("github_write", "path|||content")

    with pytest.raises(ValueError):
        tooling.parse_tool_argument("github_create_pr", "title|||body")

    with pytest.raises(ValueError):
        tooling.parse_tool_argument("github_create_issue", "title")

    prs = tooling.parse_tool_argument("github_list_prs", '{"state":"closed"}')
    assert isinstance(prs, tooling.GithubListPRsSchema)
    assert prs.state == "closed"
    assert prs.limit == 10

    issues = tooling.parse_tool_argument("github_list_issues", '{"limit":10}')
    assert isinstance(issues, tooling.GithubListIssuesSchema)
    assert issues.state == "open"
    assert issues.limit == 10

    branch = tooling.parse_tool_argument("github_create_branch", '{"branch_name":"feature"}')
    assert isinstance(branch, tooling.GithubCreateBranchSchema)
    assert branch.branch_name == "feature"
    assert branch.from_branch is None

    todos = tooling.parse_tool_argument("scan_project_todos", '{"directory":"src","extensions":[".py",".md"]}')
    assert isinstance(todos, tooling.ScanProjectTodosSchema)
    assert todos.directory == "src"
    assert todos.extensions == [".py", ".md"]


def test_parse_tool_argument_empty_and_json_edge_branches(monkeypatch):
    list_files_empty = tooling.parse_tool_argument("github_list_files", "")
    assert isinstance(list_files_empty, tooling.GithubListFilesSchema)
    assert list_files_empty.path == ""
    assert list_files_empty.branch is None

    with pytest.raises(ValueError):
        tooling.parse_tool_argument("write_file", "only_path")

    list_files = tooling.parse_tool_argument("github_list_files", '{"path":"src","branch":"dev"}')
    assert isinstance(list_files, tooling.GithubListFilesSchema)
    assert list_files.path == "src"
    assert list_files.branch == "dev"

    gw = tooling.parse_tool_argument("github_write", '{"path":"a.py","content":"print(1)","commit_message":"msg","branch":"dev"}')
    assert isinstance(gw, tooling.GithubWriteSchema)
    assert gw.commit_message == "msg"
    assert gw.branch == "dev"

    blank_branch = tooling.parse_tool_argument("github_create_branch", '{"branch_name":"   "}')
    assert isinstance(blank_branch, tooling.GithubCreateBranchSchema)

    with pytest.raises(Exception):
        tooling.parse_tool_argument("github_comment_issue", '{"number":"x"}')

    with pytest.raises(Exception):
        tooling.parse_tool_argument("github_close_issue", "")

    with pytest.raises(Exception):
        tooling.parse_tool_argument("github_pr_diff", "")

    monkeypatch.setitem(tooling.TOOL_ARG_SCHEMAS, "dummy_tool", _DummySchema)
    with pytest.raises(ValueError):
        tooling.parse_tool_argument("dummy_tool", "raw-payload")


def test_parse_tool_argument_for_unknown_tool_returns_raw_payload():
    assert tooling.parse_tool_argument("dummy_tool", "raw-payload") == "raw-payload"


def test_parse_tool_argument_supports_marketing_operation_schemas():
    assert "publish_social" in tooling.TOOL_ARG_SCHEMAS
    assert "build_landing_page" in tooling.TOOL_ARG_SCHEMAS
    assert "generate_campaign_copy" in tooling.TOOL_ARG_SCHEMAS
    assert "ingest_video_insights" in tooling.TOOL_ARG_SCHEMAS

    social = tooling.parse_tool_argument(
        "publish_social",
        '{"platform":"instagram","text":"Yeni kampanya","media_url":"https://cdn.test/post.jpg"}',
    )
    assert isinstance(social, tooling.SocialPublishSchema)
    assert social.platform == "instagram"

    landing = tooling.parse_tool_argument(
        "build_landing_page",
        '{"brand_name":"Poyraz","offer":"Demo","audience":"KOBI","call_to_action":"Kaydol","sections":["hero","faq"]}',
    )
    assert isinstance(landing, tooling.LandingPageDraftSchema)
    assert landing.sections == ["hero", "faq"]

    campaign = tooling.parse_tool_argument(
        "generate_campaign_copy",
        '{"campaign_name":"Bahar","objective":"Lead","audience":"SMB","channels":["instagram","whatsapp"]}',
    )
    assert isinstance(campaign, tooling.CampaignCopySchema)
    assert campaign.channels == ["instagram", "whatsapp"]

    video = tooling.parse_tool_argument(
        "ingest_video_insights",
        '{"source_url":"https://youtu.be/dQw4w9WgXcQ","prompt":"Özet çıkar","session_id":"marketing"}',
    )
    assert isinstance(video, tooling.VideoInsightIngestSchema)
    assert video.source_url.endswith("dQw4w9WgXcQ")