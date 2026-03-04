from pathlib import Path


def test_definitions_prompt_mentions_gemini_requires_internet_conditionally():
    src = Path("agent/definitions.py").read_text(encoding="utf-8")
    assert "sağlayıcı Gemini ise internet bağlantısı gerekir" in src


def test_definitions_prompt_declares_dispatch_as_source_of_truth():
    src = Path("agent/definitions.py").read_text(encoding="utf-8")
    assert "source-of-truth `agent/sidar_agent.py`" in src
    assert "dispatch tablosunu esas al" in src