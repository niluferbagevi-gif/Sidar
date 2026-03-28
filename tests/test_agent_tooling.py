"""
agent/tooling.py için birim testleri.
Pydantic şema sınıfları, TOOL_ARG_SCHEMAS tablosu ve parse_tool_argument fonksiyonu kapsar.
"""
from __future__ import annotations

import json
import sys
import types

import pytest


def _get_tooling():
    for mod in list(sys.modules.keys()):
        if mod == "agent.tooling":
            del sys.modules[mod]
    import agent.tooling as t
    return t


class TestWriteFileSchema:
    def test_valid_schema(self):
        t = _get_tooling()
        obj = t.WriteFileSchema(path="foo.py", content="hello")
        assert obj.path == "foo.py"
        assert obj.content == "hello"

    def test_missing_field_raises(self):
        t = _get_tooling()
        with pytest.raises(Exception):
            t.WriteFileSchema(path="foo.py")


class TestPatchFileSchema:
    def test_valid_schema(self):
        t = _get_tooling()
        obj = t.PatchFileSchema(path="a.py", old_text="old", new_text="new")
        assert obj.old_text == "old"
        assert obj.new_text == "new"


class TestGithubSchemas:
    def test_github_list_files_default_path(self):
        t = _get_tooling()
        obj = t.GithubListFilesSchema()
        assert obj.path == ""
        assert obj.branch is None

    def test_github_write_schema(self):
        t = _get_tooling()
        obj = t.GithubWriteSchema(
            path="main.py", content="# code", commit_message="feat: add"
        )
        assert obj.commit_message == "feat: add"
        assert obj.branch is None

    def test_github_create_branch_schema(self):
        t = _get_tooling()
        obj = t.GithubCreateBranchSchema(branch_name="feature/x")
        assert obj.branch_name == "feature/x"
        assert obj.from_branch is None

    def test_github_create_pr_schema(self):
        t = _get_tooling()
        obj = t.GithubCreatePRSchema(title="PR başlığı", body="açıklama", head="feature/x")
        assert obj.base is None

    def test_github_list_prs_defaults(self):
        t = _get_tooling()
        obj = t.GithubListPRsSchema()
        assert obj.state == "open"
        assert obj.limit == 10

    def test_github_list_issues_defaults(self):
        t = _get_tooling()
        obj = t.GithubListIssuesSchema()
        assert obj.state == "open"

    def test_github_comment_issue_schema(self):
        t = _get_tooling()
        obj = t.GithubCommentIssueSchema(number=5, body="yorum metni")
        assert obj.number == 5

    def test_github_close_issue_schema(self):
        t = _get_tooling()
        obj = t.GithubCloseIssueSchema(number=3)
        assert obj.number == 3

    def test_github_pr_diff_schema(self):
        t = _get_tooling()
        obj = t.GithubPRDiffSchema(number=7)
        assert obj.number == 7


class TestMarketingSchemas:
    def test_social_publish_schema(self):
        t = _get_tooling()
        obj = t.SocialPublishSchema(platform="twitter", text="merhaba")
        assert obj.platform == "twitter"
        assert obj.destination == ""

    def test_campaign_copy_schema_defaults(self):
        t = _get_tooling()
        obj = t.CampaignCopySchema(
            campaign_name="Yaz Kampanyası",
            objective="satış",
            audience="gençler",
        )
        assert obj.tone == "professional"
        assert obj.store_asset is False
        assert obj.tenant_id == "default"

    def test_landing_page_draft_schema(self):
        t = _get_tooling()
        obj = t.LandingPageDraftSchema(
            brand_name="Sidar",
            offer="ücretsiz deneme",
            audience="geliştiriciler",
            call_to_action="hemen dene",
        )
        assert obj.tone == "professional"
        assert obj.channel == "web"

    def test_marketing_campaign_create_schema_defaults(self):
        t = _get_tooling()
        obj = t.MarketingCampaignCreateSchema(name="Kış Kampanyası")
        assert obj.tenant_id == "default"
        assert obj.budget == 0.0
        assert obj.status == "draft"


class TestToolArgSchemas:
    def test_tool_arg_schemas_is_dict(self):
        t = _get_tooling()
        assert isinstance(t.TOOL_ARG_SCHEMAS, dict)

    def test_known_tools_in_schema(self):
        t = _get_tooling()
        expected = [
            "write_file", "patch_file", "github_write",
            "github_create_pr", "publish_social",
        ]
        for tool in expected:
            assert tool in t.TOOL_ARG_SCHEMAS, f"{tool} TOOL_ARG_SCHEMAS içinde yok"

    def test_schema_values_are_pydantic_models(self):
        t = _get_tooling()
        from pydantic import BaseModel
        for name, schema in t.TOOL_ARG_SCHEMAS.items():
            assert issubclass(schema, BaseModel), f"{name} bir Pydantic modeli değil"


class TestParseToolArgument:
    def test_unknown_tool_returns_raw(self):
        t = _get_tooling()
        result = t.parse_tool_argument("unknown_tool", "ham argüman")
        assert result == "ham argüman"

    def test_known_tool_parses_json(self):
        t = _get_tooling()
        payload = json.dumps({"path": "foo.py", "content": "# code"})
        result = t.parse_tool_argument("write_file", payload)
        assert isinstance(result, t.WriteFileSchema)
        assert result.path == "foo.py"

    def test_known_tool_empty_arg_returns_default_model(self):
        t = _get_tooling()
        result = t.parse_tool_argument("github_list_files", "")
        assert isinstance(result, t.GithubListFilesSchema)

    def test_legacy_pipe_format_raises_value_error(self):
        t = _get_tooling()
        with pytest.raises(ValueError, match="JSON"):
            t.parse_tool_argument("write_file", "foo.py|||# code")

    def test_json_array_raises_value_error(self):
        t = _get_tooling()
        with pytest.raises(ValueError):
            t.parse_tool_argument("write_file", '["foo", "bar"]')

    def test_parse_patch_file(self):
        t = _get_tooling()
        payload = json.dumps({"path": "a.py", "old_text": "old", "new_text": "new"})
        result = t.parse_tool_argument("patch_file", payload)
        assert isinstance(result, t.PatchFileSchema)
        assert result.new_text == "new"

    def test_parse_github_list_prs(self):
        t = _get_tooling()
        payload = json.dumps({"state": "closed", "limit": 5})
        result = t.parse_tool_argument("github_list_prs", payload)
        assert isinstance(result, t.GithubListPRsSchema)
        assert result.state == "closed"
        assert result.limit == 5
