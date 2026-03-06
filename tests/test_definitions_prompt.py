from pathlib import Path


def test_definitions_prompt_mentions_gemini_requires_internet_conditionally():
    src = Path("agent/definitions.py").read_text(encoding="utf-8")
    assert "sağlayıcı Gemini ise internet bağlantısı gerekir" in src


def test_definitions_prompt_declares_dispatch_as_source_of_truth():
    src = Path("agent/definitions.py").read_text(encoding="utf-8")
    assert "source-of-truth `agent/sidar_agent.py`" in src
    assert "dispatch tablosunu esas al" in src


def test_definitions_prompt_has_updated_runtime_identity_and_models():
    src = Path("agent/definitions.py").read_text(encoding="utf-8")
    assert "Web arayüzü varsayılan portu: `7860`" in src
    assert "Ollama varsayılan kod modeli: `qwen2.5-coder:7b`" in src
    assert "Gemini varsayılan model: `gemini-2.5-flash`" in src


def test_definitions_prompt_documents_limits_and_safety_awareness():
    src = Path("agent/definitions.py").read_text(encoding="utf-8")
    assert "en fazla son 30 commit döner" in src
    assert "İçerik 12.000 karakterden uzunsa otomatik kırpılır" in src
    assert "UTF-8 kullan; Türkçe karakterleri güvenle koru" in src
    assert "Sandbox fail-closed" in src
