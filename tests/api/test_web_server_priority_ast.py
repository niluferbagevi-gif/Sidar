from __future__ import annotations

from pathlib import Path


WEB_SERVER_PATH = Path(__file__).resolve().parents[2] / "web_server.py"


def _source() -> str:
    return WEB_SERVER_PATH.read_text(encoding="utf-8")


def test_voice_websocket_route_contains_auth_and_payload_guards() -> None:
    source = _source()

    assert "@app.websocket(\"/ws/voice\")" in source
    assert "Authentication required" in source
    assert "Authentication token missing" in source
    assert "Voice payload too large" in source
    assert "Geçersiz base64 ses parçası" in source


def test_chat_websocket_route_contains_collaboration_and_cancel_paths() -> None:
    source = _source()

    assert "@app.websocket(\"/ws/chat\")" in source
    assert 'if action == "join_room"' in source
    assert 'if action == "cancel" and active_task and not active_task.done()' in source
    assert 'if action == "cancel" and joined_room_id' in source
    assert "@Sidar etiketi sonrası komut bulunamadı." in source
