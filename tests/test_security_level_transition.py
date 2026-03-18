from pathlib import Path


def test_security_manager_has_runtime_level_setter():
    src = Path("managers/security.py").read_text(encoding="utf-8")
    assert "def set_level(self, new_level: str) -> bool:" in src
    assert "self.level = LEVEL_NAMES[normalized]" in src
    assert "self.level_name = normalized" in src


def test_sidar_agent_logs_security_level_transition_into_memory():
    src = Path("agent/sidar_agent.py").read_text(encoding="utf-8")
    assert "def set_access_level(self, new_level: str) -> str:" in src
    assert "[GÜVENLİK BİLDİRİMİ]" in src
    assert "self.memory.add(\"user\", msg)" in src
    assert "self.memory.add(" in src and "assistant" in src


def test_cli_supports_level_command_with_argument():
    src = Path("cli.py").read_text(encoding="utf-8")
    assert "elif user_input.lower().startswith(\".level\")" in src
    assert "agent.set_access_level(parts[1])" in src


def test_web_server_exposes_set_level_endpoint():
    src = Path("web_server.py").read_text(encoding="utf-8")
    assert '"/set-level"' in src
    assert "async def set_level_endpoint(" in src
    assert "await asyncio.to_thread(agent.set_access_level, new_level)" in src