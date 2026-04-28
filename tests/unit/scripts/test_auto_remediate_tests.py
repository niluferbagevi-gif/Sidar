from scripts.auto_remediate_tests import _strip_markdown_fences, parse_mypy_errors


def test_parse_mypy_errors_groups_by_file() -> None:
    output = (
        "agent/roles/qa_agent.py:42: error: Incompatible return value type\n"
        "core/ci_remediation.py:15:3: error: Name 'x' is not defined\n"
        "core/ci_remediation.py:17: error: Argument 1 has incompatible type\n"
    )
    grouped = parse_mypy_errors(output)
    assert set(grouped) == {"agent/roles/qa_agent.py", "core/ci_remediation.py"}
    assert len(grouped["core/ci_remediation.py"]) == 2
    assert grouped["core/ci_remediation.py"][0].line == 15


def test_strip_markdown_fences() -> None:
    raw = "```python\nprint('ok')\n```"
    assert _strip_markdown_fences(raw) == "print('ok')"
