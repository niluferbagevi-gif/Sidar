import asyncio
import json
import sys
import types

from tests.test_web_server_runtime import _load_web_server


class _ModulePatch:
    def __init__(self, name: str, module: types.ModuleType):
        self.name = name
        self.module = module
        self.previous = sys.modules.get(name)

    def __enter__(self):
        sys.modules[self.name] = self.module
        return self.module

    def __exit__(self, exc_type, exc, tb):
        if self.previous is None:
            sys.modules.pop(self.name, None)
        else:
            sys.modules[self.name] = self.previous
        return False


def test_websocket_voice_transcribes_audio_and_streams_agent_reply():
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, token):
            if token == "valid-token":
                return types.SimpleNamespace(id="u1", username="alice")
            return None

    class _Memory:
        def __len__(self):
            return 1

        async def set_active_user(self, *_args, **_kwargs):
            return None

        db = _DB()

    async def _respond(prompt):
        yield f"yanit:{prompt}"

    agent = types.SimpleNamespace(memory=_Memory(), llm=object(), respond=_respond)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    multimodal_mod = types.ModuleType("core.multimodal")
    voice_mod = types.ModuleType("core.voice")

    class _Pipeline:
        def __init__(self, *_args, **_kwargs):
            return None

        async def transcribe_bytes(self, audio_bytes, **kwargs):
            assert audio_bytes == b"\x01\x02voice"
            assert kwargs["mime_type"] == "audio/webm"
            return {
                "success": True,
                "text": "Sunucuyu yeniden başlat.",
                "language": "tr",
                "provider": "whisper",
            }

    multimodal_mod.MultimodalPipeline = _Pipeline

    class _VoicePipeline:
        def __init__(self, *_args, **_kwargs):
            self.enabled = True

        def extract_ready_segments(self, text, flush=False):
            text = str(text or "").strip()
            if not text:
                return [], ""
            return ([text], "") if flush else ([], text)

        async def synthesize_text(self, text):
            return {
                "success": True,
                "audio_bytes": b"tts:" + text.encode("utf-8"),
                "mime_type": "audio/mock",
                "provider": "mock",
                "voice": "",
            }

    voice_mod.VoicePipeline = _VoicePipeline

    class _WebSocket:
        def __init__(self):
            self.headers = {"sec-websocket-protocol": "valid-token"}
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.sent = []
            self.closed = None
            self._events = [
                {"type": "websocket.receive", "bytes": b"\x01\x02voice"},
                {"type": "websocket.receive", "text": json.dumps({"action": "commit", "mime_type": "audio/webm"})},
                {"type": "websocket.disconnect"},
            ]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive(self):
            return self._events.pop(0)

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code, reason):
            self.closed = (code, reason)

    ws = _WebSocket()
    with _ModulePatch("core.multimodal", multimodal_mod), _ModulePatch("core.voice", voice_mod):
        asyncio.run(mod.websocket_voice(ws))

    assert ws.accepted == "valid-token"
    assert ws.closed is None
    assert {"auth_ok": True} in ws.sent
    assert {"buffered_bytes": 7} in ws.sent
    assert {"transcript": "Sunucuyu yeniden başlat.", "language": "tr", "provider": "whisper"} in ws.sent
    assert {"chunk": "yanit:Sunucuyu yeniden başlat."} in ws.sent
    assert {
        "audio_chunk": "dHRzOnlhbml0OlN1bnVjdXl1IHllbmlkZW4gYmHFn2xhdC4=",
        "audio_text": "yanit:Sunucuyu yeniden başlat.",
        "audio_mime_type": "audio/mock",
        "audio_provider": "mock",
        "audio_voice": "",
    } in ws.sent
    assert ws.sent[-1] == {"done": True}


def test_websocket_voice_requires_auth_before_binary_audio():
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, *_args, **_kwargs):
            return None

    async def _get_agent():
        memory = types.SimpleNamespace(db=_DB())
        return types.SimpleNamespace(memory=memory, llm=object(), respond=None)

    mod.get_agent = _get_agent

    multimodal_mod = types.ModuleType("core.multimodal")
    multimodal_mod.MultimodalPipeline = lambda *_a, **_k: object()

    class _WebSocket:
        def __init__(self):
            self.headers = {}
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.closed = None
            self._events = [{"type": "websocket.receive", "bytes": b"voice"}]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive(self):
            return self._events.pop(0)

        async def send_json(self, payload):
            self.payload = payload

        async def close(self, code, reason):
            self.closed = (code, reason)

    ws = _WebSocket()
    with _ModulePatch("core.multimodal", multimodal_mod):
        asyncio.run(mod.websocket_voice(ws))

    assert ws.closed == (1008, "Authentication required")


def test_websocket_voice_vad_event_auto_commits_buffered_audio():
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, token):
            if token == "valid-token":
                return types.SimpleNamespace(id="u1", username="alice")
            return None

    class _Memory:
        def __len__(self):
            return 1

        async def set_active_user(self, *_args, **_kwargs):
            return None

        db = _DB()

    async def _respond(prompt):
        yield f"yanit:{prompt}"

    agent = types.SimpleNamespace(memory=_Memory(), llm=object(), respond=_respond)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    multimodal_mod = types.ModuleType("core.multimodal")
    voice_mod = types.ModuleType("core.voice")

    class _Pipeline:
        def __init__(self, *_args, **_kwargs):
            return None

        async def transcribe_bytes(self, audio_bytes, **kwargs):
            assert audio_bytes == b"x" * 1200
            return {
                "success": True,
                "text": "Otomatik commit denemesi.",
                "language": "tr",
                "provider": "whisper",
            }

    multimodal_mod.MultimodalPipeline = _Pipeline

    class _VoicePipeline:
        def __init__(self, *_args, **_kwargs):
            self.enabled = True
            self.vad_enabled = True

        def extract_ready_segments(self, text, flush=False):
            text = str(text or "").strip()
            if not text:
                return [], ""
            return ([text], "") if flush else ([], text)

        async def synthesize_text(self, text):
            return {
                "success": True,
                "audio_bytes": b"tts:" + text.encode("utf-8"),
                "mime_type": "audio/mock",
                "provider": "mock",
                "voice": "",
            }

        def should_commit_audio(self, buffered_bytes, *, event=""):
            return event == "speech_end" and buffered_bytes >= 1024

        def build_voice_state_payload(self, *, event, buffered_bytes, sequence):
            return {
                "voice_state": event,
                "buffered_bytes": buffered_bytes,
                "sequence": sequence,
                "vad_enabled": True,
                "auto_commit_ready": self.should_commit_audio(buffered_bytes, event=event),
                "tts_enabled": True,
            }

    voice_mod.VoicePipeline = _VoicePipeline

    class _WebSocket:
        def __init__(self):
            self.headers = {"sec-websocket-protocol": "valid-token"}
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.sent = []
            self._events = [
                {"type": "websocket.receive", "bytes": b"x" * 1200},
                {"type": "websocket.receive", "text": json.dumps({"action": "vad_event", "state": "speech_end"})},
                {"type": "websocket.disconnect"},
            ]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive(self):
            return self._events.pop(0)

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code, reason):
            self.closed = (code, reason)

    ws = _WebSocket()
    with _ModulePatch("core.multimodal", multimodal_mod), _ModulePatch("core.voice", voice_mod):
        asyncio.run(mod.websocket_voice(ws))

    voice_states = [item for item in ws.sent if "voice_state" in item]
    assert any(item["voice_state"] == "chunk" for item in voice_states)
    assert any(item["voice_state"] == "speech_end" and item["auto_commit_ready"] is True for item in voice_states)
    assert any(item["voice_state"] == "processed" for item in voice_states)
    assert {"transcript": "Otomatik commit denemesi.", "language": "tr", "provider": "whisper"} in ws.sent


def test_websocket_voice_barge_in_cancels_active_duplex_response():
    mod = _load_web_server()

    class _DB:
        async def get_user_by_token(self, token):
            if token == "valid-token":
                return types.SimpleNamespace(id="u1", username="alice")
            return None

    class _Memory:
        def __len__(self):
            return 1

        async def set_active_user(self, *_args, **_kwargs):
            return None

        db = _DB()

    async def _respond(prompt):
        yield f"yanit:{prompt}"
        await asyncio.sleep(0.05)
        yield "uzun-devam"

    agent = types.SimpleNamespace(memory=_Memory(), llm=object(), respond=_respond)

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent

    multimodal_mod = types.ModuleType("core.multimodal")
    voice_mod = types.ModuleType("core.voice")

    class _Pipeline:
        def __init__(self, *_args, **_kwargs):
            return None

        async def transcribe_bytes(self, audio_bytes, **kwargs):
            if audio_bytes == b"a" * 900:
                return {
                    "success": True,
                    "text": "İlk konuşma",
                    "language": "tr",
                    "provider": "whisper",
                }
            return {
                "success": True,
                "text": "İkinci konuşma",
                "language": "tr",
                "provider": "whisper",
            }

    multimodal_mod.MultimodalPipeline = _Pipeline

    class _VoicePipeline:
        def __init__(self, *_args, **_kwargs):
            self.enabled = True
            self.vad_enabled = True
            self.duplex_enabled = True

        def extract_ready_segments(self, text, flush=False):
            text = str(text or "").strip()
            if not text:
                return [], ""
            return ([text], "") if flush else ([], text)

        async def synthesize_text(self, text):
            return {
                "success": True,
                "audio_bytes": b"tts:" + text.encode("utf-8"),
                "mime_type": "audio/mock",
                "provider": "mock",
                "voice": "",
            }

        def should_commit_audio(self, buffered_bytes, *, event=""):
            return event == "speech_end" and buffered_bytes >= 700

        def should_interrupt_response(self, buffered_bytes, *, event=""):
            return event == "speech_start" and buffered_bytes >= 300

        def build_voice_state_payload(self, *, event, buffered_bytes, sequence):
            return {
                "voice_state": event,
                "buffered_bytes": buffered_bytes,
                "sequence": sequence,
                "vad_enabled": True,
                "auto_commit_ready": self.should_commit_audio(buffered_bytes, event=event),
                "duplex_enabled": True,
                "interrupt_ready": self.should_interrupt_response(buffered_bytes, event=event),
                "tts_enabled": True,
            }

    voice_mod.VoicePipeline = _VoicePipeline

    class _WebSocket:
        def __init__(self):
            self.headers = {"sec-websocket-protocol": "valid-token"}
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.sent = []
            self._events = [
                {"type": "websocket.receive", "bytes": b"a" * 900},
                {"type": "websocket.receive", "text": json.dumps({"action": "commit", "mime_type": "audio/webm"})},
                {"type": "websocket.receive", "bytes": b"b" * 400},
                {"type": "websocket.receive", "text": json.dumps({"action": "vad_event", "state": "speech_start"})},
                {"type": "websocket.disconnect"},
            ]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive(self):
            await asyncio.sleep(0)
            return self._events.pop(0)

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code, reason):
            self.closed = (code, reason)

    ws = _WebSocket()
    with _ModulePatch("core.multimodal", multimodal_mod), _ModulePatch("core.voice", voice_mod):
        asyncio.run(mod.websocket_voice(ws))

    assert {"transcript": "İlk konuşma", "language": "tr", "provider": "whisper"} in ws.sent
    assert {"voice_interruption": "barge_in", "cancelled": True} in ws.sent
    voice_states = [item for item in ws.sent if item.get("voice_state") == "speech_start"]
    assert voice_states and voice_states[0]["interrupt_ready"] is True
