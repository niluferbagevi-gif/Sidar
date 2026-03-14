# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

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
    assert "fetchAPI(apiUrl('/api/rag/upload')" in js
    assert "function downloadChat()" in js
    assert "sidar_sohbet_" in js

def test_web_ui_budget_strip_uses_budget_endpoint_and_cost_text():
    js = Path("web_ui/app.js").read_text(encoding="utf-8")
    assert "apiUrl('/api/budget')" in js
    assert "OpenAI" in js
    assert "Anthropic" in js


def test_web_ui_handles_backend_status_stream_messages():
    js = Path("web_ui/chat.js").read_text(encoding="utf-8")
    assert "if (data.status)" in js
    assert "apSetThought(data.status)" in js

def test_web_ui_has_auth_overlay_and_token_wrapper():
    html = Path("web_ui/index.html").read_text(encoding="utf-8")
    js = Path("web_ui/app.js").read_text(encoding="utf-8")

    assert 'id="auth-overlay"' in html
    assert 'id="login-form"' in html
    assert 'id="register-form"' in html
    assert "async function fetchAPI(url, options = {})" in js
    assert "Authorization = `Bearer ${token}`" in js
    assert "function logoutUser()" in js


def test_web_ui_has_admin_panel_markup_and_loader_logic():
    html = Path("web_ui/index.html").read_text(encoding="utf-8")
    js = Path("web_ui/app.js").read_text(encoding="utf-8")

    assert 'id="admin-panel-container"' in html
    assert 'id="admin-users-tbody"' in html
    assert 'id="admin-nav-tab"' in html
    assert "window.showAdminPanel = async function showAdminPanel()" in js
    assert "fetchAPI('/admin/stats')" in js

def test_web_ui_handles_auth_expiry_websocket_disconnect_gracefully():
    js = Path("web_ui/chat.js").read_text(encoding="utf-8")
    assert "function handleExpiredSession" in js
    assert "Oturumunuz sonlandı, lütfen tekrar giriş yapın." in js
    assert "wsCode === 1008" in js
    assert "if (!authClosed)" in js