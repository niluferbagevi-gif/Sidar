from agent.roles.qa_agent import QAAgent


def test_suggest_test_path_preserves_module_hierarchy() -> None:
    assert QAAgent._suggest_test_path("core/utils.py") == "tests/core/test_utils.py"
    assert QAAgent._suggest_test_path("api/utils.py") == "tests/api/test_utils.py"
    assert QAAgent._suggest_test_path("utils.py") == "tests/test_utils.py"


def test_sanitize_llm_code_removes_markdown_fences() -> None:
    raw = """```python\nimport pytest\n\n\ndef test_x():\n    assert True\n```"""
    clean = QAAgent._sanitize_llm_code(raw)
    assert clean.startswith("import pytest")
    assert "```" not in clean
