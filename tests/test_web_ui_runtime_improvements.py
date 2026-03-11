from pathlib import Path


def test_web_ui_uses_websocket_chat_stream_and_cancel_handling():
    html = Path("web_ui/index.html").read_text(encoding="utf-8")
    js = Path("web_ui/chat.js").read_text(encoding="utf-8")
    assert "/ws/chat" in js
    assert "new WebSocket" in js
    assert "action: 'cancel'" in js
    assert "showUiNotice('Sunucu bağlantısı hazırlanıyor, lütfen tekrar deneyin.'" in js
    assert '/static/chat.js' in html


def test_web_ui_exposes_live_health_strip_for_gpu_and_ollama():
    html = Path("web_ui/index.html").read_text(encoding="utf-8")
    js = Path("web_ui/app.js").read_text(encoding="utf-8")
    assert "id=\"pill-ollama\"" in html
    assert "id=\"pill-gpu\"" in html
    assert "id=\"pill-vram\"" in html
    assert "async function refreshHealthStrip()" in js


def test_web_ui_supports_drag_drop_rag_and_markdown_download():
    html = Path("web_ui/index.html").read_text(encoding="utf-8")
    js = Path("web_ui/app.js").read_text(encoding="utf-8")

    assert 'onclick="downloadChat()"' in html
    assert 'id="drag-overlay"' in html
    assert '.drag-overlay.active' in html

    assert "document.addEventListener('drop', async (e) =>" in js
    assert "fetch(apiUrl('/api/rag/upload')" in js
    assert "function downloadChat()" in js
    assert "sidar_sohbet_" in js

def test_web_ui_budget_strip_uses_budget_endpoint_and_cost_text():
    js = Path("web_ui/app.js").read_text(encoding="utf-8")
    assert "apiUrl('/api/budget')" in js
    assert "OpenAI" in js
    assert "Anthropic" in js
