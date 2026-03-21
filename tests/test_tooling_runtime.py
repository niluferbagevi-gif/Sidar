import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_tooling_module():
    stub = types.ModuleType("pydantic")

    class _BaseModel:
        def __init__(self, **kwargs):
            annotations = getattr(self.__class__, "__annotations__", {})
            for k in annotations:
                if k in kwargs:
                    setattr(self, k, kwargs[k])
                elif hasattr(self.__class__, k):
                    setattr(self, k, getattr(self.__class__, k))
                else:
                    raise ValueError(f"missing required: {k}")

        @classmethod
        def model_validate(cls, data):
            return cls(**data)

        @classmethod
        def model_rebuild(cls):
            return None

    def _field(default=None, **_kwargs):
        return default

    stub.BaseModel = _BaseModel
    stub.Field = _field

    old = sys.modules.get("pydantic")
    try:
        sys.modules["pydantic"] = stub
        spec = importlib.util.spec_from_file_location("tooling_runtime", Path("agent/tooling.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        if old is None:
            sys.modules.pop("pydantic", None)
        else:
            sys.modules["pydantic"] = old


def test_tooling_parse_branches_runtime_json_only():
    tooling = _load_tooling_module()

    parsed_empty = tooling.parse_tool_argument("github_list_files", "")
    assert parsed_empty.path == ""
    assert parsed_empty.branch is None

    with pytest.raises(ValueError):
        tooling.parse_tool_argument("write_file", "path_only")

    parsed_list = tooling.parse_tool_argument("github_list_files", '{"path":"src","branch":"dev"}')
    assert parsed_list.path == "src"
    assert parsed_list.branch == "dev"

    parsed_write = tooling.parse_tool_argument("github_write", '{"path":"a.py","content":"x","commit_message":"msg","branch":"dev"}')
    assert parsed_write.path == "a.py"
    assert parsed_write.commit_message == "msg"

    parsed_patch = tooling.parse_tool_argument("patch_file", '{"path":"a.py","old_text":"old","new_text":"new"}')
    assert parsed_patch.old_text == "old"
    assert parsed_patch.new_text == "new"

    parsed_branch = tooling.parse_tool_argument("github_create_branch", '{"branch_name":"feature-x","from_branch":"main"}')
    assert parsed_branch.branch_name == "feature-x"
    assert parsed_branch.from_branch == "main"

    parsed_close_issue = tooling.parse_tool_argument("github_close_issue", '{"number":42}')
    assert parsed_close_issue.number == 42

    parsed_pr_diff = tooling.parse_tool_argument("github_pr_diff", '{"number":42}')
    assert parsed_pr_diff.number == 42

    with pytest.raises(ValueError):
        tooling.parse_tool_argument("github_create_branch", "")

    for tool, arg in (
        ("github_comment_issue", '{"number":1}'),
        ("github_close_issue", ""),
        ("github_pr_diff", "|||"),
    ):
        with pytest.raises(Exception):
            tooling.parse_tool_argument(tool, arg)

    class _Dummy(tooling.BaseModel):
        value: str = ""

    tooling.TOOL_ARG_SCHEMAS["dummy"] = _Dummy
    with pytest.raises(ValueError):
        tooling.parse_tool_argument("dummy", "raw")


def test_load_tooling_module_restores_when_pydantic_missing(monkeypatch):
    old = sys.modules.pop("pydantic", None)
    try:
        mod = _load_tooling_module()
        assert hasattr(mod, "parse_tool_argument")
        assert "pydantic" not in sys.modules
    finally:
        if old is not None:
            sys.modules["pydantic"] = old


def test_tooling_json_parsing_for_list_and_todo_tools():
    tooling = _load_tooling_module()

    result_pr = tooling.parse_tool_argument("github_list_prs", '{"state":"open","limit":25}')
    assert result_pr.limit == 25

    result_issue = tooling.parse_tool_argument("github_list_issues", '{"state":"closed","limit":12}')
    assert result_issue.limit == 12

    result_scan = tooling.parse_tool_argument("scan_project_todos", '{"directory":"src","extensions":[".py",".js"]}')
    assert result_scan.directory == "src"
    assert result_scan.extensions == [".py", ".js"]


def test_tooling_rejects_legacy_delimited_payloads():
    tooling = _load_tooling_module()

    with pytest.raises(ValueError, match=r"legacy '\|\|\|' formatı kaldırıldı"):
        tooling.parse_tool_argument("github_create_branch", "   |||main")

    with pytest.raises(ValueError, match=r"legacy '\|\|\|' formatı kaldırıldı"):
        tooling.parse_tool_argument("github_close_issue", "|||   ")


def test_tooling_github_close_issue_empty_argument():
    tooling = _load_tooling_module()

    with pytest.raises(Exception):
        tooling.parse_tool_argument("github_close_issue", "")

def test_tooling_rejects_non_object_json_payload():
    tooling = _load_tooling_module()

    with pytest.raises(ValueError, match="JSON object olmalıdır"):
        tooling.parse_tool_argument("github_list_files", "[]")


def test_tooling_marketing_schemas_runtime():
    tooling = _load_tooling_module()

    social = tooling.parse_tool_argument(
        "publish_social",
        '{"platform":"facebook","text":"Duyuru","link_url":"https://example.test"}',
    )
    assert social.platform == "facebook"
    assert social.link_url == "https://example.test"

    landing = tooling.parse_tool_argument(
        "build_landing_page",
        '{"brand_name":"Sidar","offer":"Operasyon Merkezi","audience":"Kurumsal","call_to_action":"Demo iste"}',
    )
    assert landing.brand_name == "Sidar"
    assert landing.call_to_action == "Demo iste"

    campaign = tooling.parse_tool_argument(
        "generate_campaign_copy",
        '{"campaign_name":"Launch","objective":"Awareness","audience":"Developers","channels":["instagram"]}',
    )
    assert campaign.campaign_name == "Launch"
    assert campaign.channels == ["instagram"]
