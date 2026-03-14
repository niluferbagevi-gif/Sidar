# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

from pathlib import Path


def test_claude_md_contains_run_commands_and_port_7860():
    src = Path("CLAUDE.md").read_text(encoding="utf-8")
    assert "python main.py" in src
    assert "python main.py --quick web --host 0.0.0.0 --port 7860" in src
    assert "docker compose up --build" in src
    assert "Varsayılan API/Web portu **7860**" in src


def test_claude_md_documents_async_utf8_and_sandbox_fail_closed():
    src = Path("CLAUDE.md").read_text(encoding="utf-8")
    assert "Asenkron Mimari" in src
    assert "async/await" in src
    assert "UTF-8" in src
    assert "Sandbox fail-closed" in src


def test_claude_md_mentions_dot_commands():
    src = Path("CLAUDE.md").read_text(encoding="utf-8")
    assert ".status" in src
    assert ".health" in src
    assert ".clear" in src