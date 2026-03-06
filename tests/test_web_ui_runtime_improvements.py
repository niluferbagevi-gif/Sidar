from pathlib import Path


def test_web_ui_uses_dynamic_api_origin_and_chat_stream_handling():
    src = Path("web_ui/index.html").read_text(encoding="utf-8")
    assert "const API_URL = window.location.origin" in src
    assert "fetch(apiUrl('/chat')" in src
    assert "response.status === 429" in src
    assert "showUiNotice(msg, 'warn')" in src


def test_web_ui_exposes_live_health_strip_for_gpu_and_ollama():
    src = Path("web_ui/index.html").read_text(encoding="utf-8")
    assert "id=\"pill-ollama\"" in src
    assert "id=\"pill-gpu\"" in src
    assert "id=\"pill-vram\"" in src
    assert "async function refreshHealthStrip()" in src