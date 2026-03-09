import importlib.util
import sys
import types
from pathlib import Path


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

    try:
        tooling.parse_tool_argument("write_file", "path_only")
        assert False, "expected ValueError"
    except ValueError:
        pass

    parsed_list = tooling.parse_tool_argument("github_list_files", "src|||dev")
    assert parsed_list.path == "src"
    assert parsed_list.branch == "dev"

    parsed_write = tooling.parse_tool_argument("github_write", "a.py|||x|||msg|||dev")
    assert parsed_write.path == "a.py"
    assert parsed_write.commit_message == "msg"

    try:
        tooling.parse_tool_argument("github_create_branch", "")
        assert False, "expected ValueError"
    except ValueError:
        pass

    for tool, arg in (
        ("github_comment_issue", "1"),
        ("github_close_issue", ""),
        ("github_pr_diff", "|||"),
    ):
        try:
            tooling.parse_tool_argument(tool, arg)
            assert False, f"expected ValueError for {tool}"
        except ValueError:
            pass

    class _Dummy(tooling.BaseModel):
        value: str = ""

    tooling.TOOL_ARG_SCHEMAS["dummy"] = _Dummy
    assert tooling.parse_tool_argument("dummy", "raw") == "raw"