# 🚀 Sidar 3.0.0 - Otomatik Dağıtım


from pathlib import Path


def test_cli_supports_clear_aliases():
    src = Path("cli.py").read_text(encoding="utf-8")
    assert '.clear", "/clear", "/reset"' in src
    assert "agent.clear_memory()" in src


def test_cli_parser_defaults_are_loaded_from_config():
    src = Path("cli.py").read_text(encoding="utf-8")
    assert "cfg_defaults = Config()" in src
    assert 'default=getattr(cfg_defaults, "ACCESS_LEVEL", "full")' in src
    assert 'default=getattr(cfg_defaults, "AI_PROVIDER", "ollama")' in src
    assert 'default=getattr(cfg_defaults, "CODING_MODEL", "qwen2.5-coder:7b")' in src
    assert 'default=getattr(cfg_defaults, "LOG_LEVEL", "INFO")' in src
