import pytest

from agent.tooling import GithubListPRsSchema, parse_tool_argument


def test_parse_tool_argument_returns_raw_arg_for_unknown_tool():
    raw = "legacy|||value"

    assert parse_tool_argument("unknown_tool", raw) == raw


def test_parse_tool_argument_empty_payload_uses_schema_defaults():
    payload = parse_tool_argument("github_list_prs", "   ")

    assert isinstance(payload, GithubListPRsSchema)
    assert payload.state == "open"
    assert payload.limit == 10


def test_parse_tool_argument_rejects_non_object_json_payload():
    with pytest.raises(ValueError, match="Argüman JSON object olmalıdır"):
        parse_tool_argument("github_list_prs", "[]")


def test_parse_tool_argument_rejects_legacy_or_invalid_json_payload():
    with pytest.raises(ValueError, match=r"legacy '\|\|\|' formatı kaldırıldı"):
        parse_tool_argument("github_list_prs", "not-json")
