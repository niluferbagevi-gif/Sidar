"""Unit tests for ``agent.tooling``."""

import pytest

from agent.tooling import (
    GithubListIssuesSchema,
    LspRenameSchema,
    parse_tool_argument,
)


def test_parse_tool_argument_returns_raw_for_unknown_tool() -> None:
    """Parse tool argument returns raw for unknown tool."""
    raw = "plain-text-value"
    assert parse_tool_argument("unknown_tool", raw) == raw


def test_parse_tool_argument_uses_schema_defaults_for_empty_payload() -> None:
    """Parse tool argument uses schema defaults for empty payload."""
    result = parse_tool_argument("github_list_issues", "   ")

    assert isinstance(result, GithubListIssuesSchema)
    assert result.state == "open"
    assert result.limit == 10


def test_parse_tool_argument_validates_json_object_payload() -> None:
    """Parse tool argument validates json object payload."""
    result = parse_tool_argument(
        "lsp_rename",
        '{"path":"agent/tooling.py","line":7,"character":3,"new_name":"renamed","apply":true}',
    )

    assert isinstance(result, LspRenameSchema)
    assert result.path == "agent/tooling.py"
    assert result.line == 7
    assert result.character == 3
    assert result.new_name == "renamed"
    assert result.apply is True


@pytest.mark.parametrize("payload", ["[]", '"text"', "123", "true", "null"])
def test_parse_tool_argument_rejects_non_object_json(payload: str) -> None:
    """Parse tool argument rejects non object json."""
    with pytest.raises(ValueError, match="Argüman JSON object olmalıdır"):
        parse_tool_argument("github_list_issues", payload)


def test_parse_tool_argument_rejects_legacy_delimited_format() -> None:
    """Parse tool argument rejects legacy delimited format."""
    with pytest.raises(ValueError, match=r"legacy '\|\|\|' formatı kaldırıldı"):
        parse_tool_argument("lsp_rename", "path|||12|||3|||new_name")


def test_parse_tool_argument_allows_none_raw_arg_and_applies_defaults() -> None:
    """Parse tool argument allows none raw arg and applies defaults."""
    result = parse_tool_argument("github_list_issues", None)

    assert isinstance(result, GithubListIssuesSchema)
    assert result.model_dump() == {"state": "open", "limit": 10}
