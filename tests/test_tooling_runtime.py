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


def test_tooling_uncovered_parse_branches_runtime():
    tooling = _load_tooling_module()

    parsed_empty = tooling.parse_tool_argument("github_list_files", "")
    assert parsed_empty.path == ""
    assert parsed_empty.branch is None

    with pytest.raises(ValueError):
        tooling.parse_tool_argument("write_file", "path_only")

    parsed_list = tooling.parse_tool_argument("github_list_files", "src|||dev")
    assert parsed_list.path == "src"
    assert parsed_list.branch == "dev"

    parsed_write = tooling.parse_tool_argument("github_write", "a.py|||x|||msg|||dev")
    assert parsed_write.path == "a.py"
    assert parsed_write.commit_message == "msg"

    parsed_legacy_write = tooling.parse_tool_argument("write_file", "a.py|||print('x')")
    assert parsed_legacy_write.path == "a.py"
    assert "print" in parsed_legacy_write.content

    parsed_patch = tooling.parse_tool_argument("patch_file", "a.py|||old|||new")
    assert parsed_patch.old_text == "old"
    assert parsed_patch.new_text == "new"

    parsed_branch = tooling.parse_tool_argument("github_create_branch", "feature-x|||main")
    assert parsed_branch.branch_name == "feature-x"
    assert parsed_branch.from_branch == "main"

    parsed_close_issue = tooling.parse_tool_argument("github_close_issue", "42")
    assert parsed_close_issue.number == 42

    with pytest.raises(ValueError):
        tooling.parse_tool_argument("github_create_branch", "")

    for tool, arg in (
        ("github_comment_issue", "1"),
        ("github_close_issue", ""),
        ("github_pr_diff", "|||"),
    ):
        with pytest.raises(ValueError):
            tooling.parse_tool_argument(tool, arg)

    class _Dummy(tooling.BaseModel):
        value: str = ""

    tooling.TOOL_ARG_SCHEMAS["dummy"] = _Dummy
    assert tooling.parse_tool_argument("dummy", "raw") == "raw"


def test_load_tooling_module_restores_when_pydantic_missing(monkeypatch):
    old = sys.modules.pop("pydantic", None)
    try:
        mod = _load_tooling_module()
        assert hasattr(mod, "parse_tool_argument")
        assert "pydantic" not in sys.modules
    finally:
        if old is not None:
            sys.modules["pydantic"] = old


def test_tooling_legacy_parse_value_errors_and_extensions():
    tooling = _load_tooling_module()

    result_pr = tooling.parse_tool_argument("github_list_prs", "open|||not-a-number")
    assert result_pr.limit == 10

    result_issue = tooling.parse_tool_argument("github_list_issues", "closed|||invalid")
    assert result_issue.limit == 10

    result_scan = tooling.parse_tool_argument("scan_project_todos", "src|||.py, .js")
    assert result_scan.directory == "src"
    assert result_scan.extensions == [".py", ".js"]
