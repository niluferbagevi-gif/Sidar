import asyncio
import json
import types
from pathlib import Path

from tests.test_web_server_runtime import _load_web_server


class _PassiveSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def test_join_room_helper_tracks_presence_snapshot():
    mod = _load_web_server()
    ws = _PassiveSocket()

    room = asyncio.run(
        mod._join_collaboration_room(
            ws,
            room_id="workspace:demo",
            user_id="u1",
            username="alice",
            display_name="Alice",
        )
    )

    assert room.room_id == "workspace:demo"
    assert any(item.get("type") == "room_state" for item in ws.sent)
    assert any(item.get("type") == "presence" for item in ws.sent)

    asyncio.run(mod._leave_collaboration_room(ws))


def test_join_room_helper_exposes_role_and_write_scopes():
    mod = _load_web_server()
    ws = _PassiveSocket()

    room = asyncio.run(
        mod._join_collaboration_room(
            ws,
            room_id="workspace:secure",
            user_id="u-admin",
            username="admin",
            display_name="Admin",
            user_role="admin",
        )
    )

    room_state = next(item for item in ws.sent if item.get("type") == "room_state")
    participant = room_state["participants"][0]

    assert room.room_id == "workspace:secure"
    assert participant["role"] == "admin"
    assert participant["can_write"] == "true"
    assert participant["write_scopes"]

    asyncio.run(mod._leave_collaboration_room(ws))


def test_websocket_chat_broadcasts_collaboration_room_messages_and_sidar_commands():
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, token):
            if token == "tok-alice":
                return types.SimpleNamespace(id="u1", username="alice", role="editor")
            return types.SimpleNamespace(id="u2", username="bob", role="viewer")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def _try_multi_agent(self, prompt):
            delimiter = 'Current command:\n'
            return f"room-ok:{prompt.split(delimiter, 1)[-1].strip()}"

    class _ScriptedSocket:
        def __init__(self, payloads):
            self._payloads = list(payloads)
            self.sent = []
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}
            self.accepted = False

        async def accept(self, subprotocol=None):
            self.accepted = True
            self.subprotocol = subprotocol

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    agent = _Agent()

    async def _get_agent():
        return agent

    async def _not_limited(*_args, **_kwargs):
        return False

    mod.get_agent = _get_agent
    mod._redis_is_rate_limited = _not_limited

    spectator = _PassiveSocket()
    asyncio.run(
        mod._join_collaboration_room(
            spectator,
            room_id="workspace:demo",
            user_id="u2",
            username="bob",
            display_name="Bob",
        )
    )

    ws = _ScriptedSocket([
        json.dumps({"action": "auth", "token": "tok-alice"}),
        json.dumps({"action": "join_room", "room_id": "workspace:demo", "display_name": "Alice"}),
        json.dumps({"action": "message", "message": "@Sidar sprint planı çıkar", "display_name": "Alice"}),
    ])

    asyncio.run(mod.websocket_chat(ws))

    assert any(item.get("type") == "room_state" for item in ws.sent)
    assert any(item.get("type") == "room_message" for item in spectator.sent)
    assert any(item.get("type") == "assistant_done" for item in spectator.sent)
    assistant_done = next(item for item in spectator.sent if item.get("type") == "assistant_done")
    assert "sprint planı çıkar" in assistant_done["message"]["content"]

    asyncio.run(mod._leave_collaboration_room(spectator))


def test_websocket_chat_masks_collaboration_secrets_and_blocks_read_only_write_requests():
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, token):
            if token == "tok-writer":
                return types.SimpleNamespace(id="u1", username="alice", role="editor")
            return types.SimpleNamespace(id="u2", username="bob", role="viewer")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def _try_multi_agent(self, prompt):
            return "ok"

    class _ScriptedSocket:
        def __init__(self, payloads):
            self._payloads = list(payloads)
            self.sent = []
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}

        async def accept(self, subprotocol=None):
            self.subprotocol = subprotocol

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    agent = _Agent()

    async def _get_agent():
        return agent

    async def _not_limited(*_args, **_kwargs):
        return False

    mod.get_agent = _get_agent
    mod._redis_is_rate_limited = _not_limited

    spectator = _PassiveSocket()
    asyncio.run(
        mod._join_collaboration_room(
            spectator,
            room_id="workspace:secure",
            user_id="u1",
            username="alice",
            display_name="Alice",
            user_role="editor",
        )
    )

    ws = _ScriptedSocket([
        json.dumps({"action": "auth", "token": "tok-viewer"}),
        json.dumps({"action": "join_room", "room_id": "workspace:secure", "display_name": "Bob"}),
        json.dumps({"action": "message", "message": "api_key=abcdef1234567890xyz", "display_name": "Bob"}),
        json.dumps({"action": "message", "message": "@Sidar main.py dosyasını değiştir", "display_name": "Bob"}),
    ])

    asyncio.run(mod.websocket_chat(ws))

    room_message = next(item for item in spectator.sent if item.get("type") == "room_message")
    assert "abcdef1234567890xyz" not in room_message["message"]["content"]
    assert "[MASK" in room_message["message"]["content"]

    error_payload = next(item for item in ws.sent if item.get("type") == "room_error")
    assert "yazma yetkisine sahip değil" in error_payload["error"]

    asyncio.run(mod._leave_collaboration_room(spectator))


def test_react_collaboration_workspace_sources_exist():
    chat_panel = Path("web_ui_react/src/components/ChatPanel.jsx").read_text(encoding="utf-8")
    websocket_hook = Path("web_ui_react/src/hooks/useWebSocket.js").read_text(encoding="utf-8")
    chat_store = Path("web_ui_react/src/hooks/useChatStore.js").read_text(encoding="utf-8")

    assert "join_room" in websocket_hook
    assert "workspace:sidar" in chat_store
    assert "@Sidar" in chat_panel