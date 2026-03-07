import importlib.util
from pathlib import Path


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
