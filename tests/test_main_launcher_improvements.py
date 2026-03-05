from pathlib import Path


def test_main_dummy_config_defaults_are_aligned():
    src = Path("main.py").read_text(encoding="utf-8")
    assert 'WEB_HOST = "0.0.0.0"' in src
    assert 'WEB_PORT = 7860' in src
    assert 'CODING_MODEL = "qwen2.5-coder:7b"' in src
    assert 'OLLAMA_URL = "http://localhost:11434/api"' in src


def test_main_uses_lowercase_log_levels_for_web_compatibility():
    src = Path("main.py").read_text(encoding="utf-8")
    assert '("INFO (Standart)", "info")' in src
    assert '("DEBUG (Detaylı Geliştirici Logları)", "debug")' in src
    assert '("WARNING (Sadece Uyarılar ve Hatalar)", "warning")' in src
    assert 'args.log.lower()' in src
    assert 'parser.add_argument("--log", default="info"' in src


def test_main_quick_mode_fallbacks_match_config_defaults():
    src = Path("main.py").read_text(encoding="utf-8")
    assert 'getattr(cfg, "CODING_MODEL", "qwen2.5-coder:7b")' in src
    assert 'getattr(cfg, "WEB_HOST", "0.0.0.0")' in src
    assert 'getattr(cfg, "WEB_PORT", 7860)' in src



def test_main_wizard_fallbacks_match_config_defaults():
    src = Path("main.py").read_text(encoding="utf-8")
    assert "Kullanılacak Ollama modeli" in src
    assert "getattr(cfg, \"CODING_MODEL\", \"qwen2.5-coder:7b\")" in src
    assert "Web Sunucu Host IP'si" in src
    assert "getattr(cfg, \"WEB_HOST\", \"0.0.0.0\")" in src
    assert "ask_text(\"Web Sunucu Portu\", str(getattr(cfg, \"WEB_PORT\", 7860)))" in src