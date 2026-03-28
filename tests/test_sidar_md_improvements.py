from pathlib import Path


def test_sidar_md_contains_runtime_port_and_model_defaults():
    src = Path("docs/SIDAR.md").read_text(encoding="utf-8")
    assert "API/Web Portu:" in src
    assert "7860" in src
    assert "qwen2.5-coder:7b" in src
    assert "gemini-2.5-flash" in src


def test_sidar_md_documents_utf8_and_fail_closed_security():
    src = Path("docs/SIDAR.md").read_text(encoding="utf-8")
    assert "encoding=\"utf-8\"" in src
    assert "Fail-Closed" in src
    assert "restricted / sandbox / full" in src


def test_sidar_md_mentions_dot_prefixed_system_commands():
    src = Path("docs/SIDAR.md").read_text(encoding="utf-8")
    assert ".status" in src
    assert ".health" in src
    assert ".clear" in src