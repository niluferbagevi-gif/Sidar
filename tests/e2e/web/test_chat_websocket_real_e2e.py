"""Genuine end-to-end coverage for the register -> login -> agent -> LLM -> DB -> WebSocket flow.

Unlike tests/integration/web/test_chat_websocket_integration.py (which fakes the
agent/LLM and DB entirely), this test drives the real production wiring at every
stage except the actual Ollama server:

- Real HTTP registration + login against a real ``core.db`` SQLite backend
  (real argon2 password hashing, real JWT issuance).
- A real ``SidarAgent`` instance (not a SimpleNamespace/Mock), running its real
  SupervisorAgent orchestration.
- A real local HTTP server standing in for Ollama's ``/api/chat`` endpoint,
  following the same mock contract already used by
  tests/e2e/cli/test_cli_e2e.py (a single "final_answer" tool-call payload is
  enough to drive one full SupervisorAgent turn to completion).
- A real WebSocket connection/protocol via FastAPI's TestClient.

This closes the gap flagged in review: the test suite's pyramid is heavily
unit-weighted and the login -> agent -> LLM -> DB -> WebSocket flow was
previously only exercised with mocked collaborators.
"""

from __future__ import annotations

import asyncio
import json
import socketserver
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from config import Config

if "opentelemetry.instrumentation.httpx" not in sys.modules:
    fake_httpx_mod = SimpleNamespace(
        HTTPXClientInstrumentor=SimpleNamespace(instrument=lambda *args, **kwargs: None)
    )
    sys.modules["opentelemetry.instrumentation.httpx"] = fake_httpx_mod

import web_server
from agent.sidar_agent import SidarAgent
from web_server import app

_RESPONSE_ARGUMENT = "WS_REAL_E2E_OK"


def _ollama_final_answer_payload(argument: str) -> dict:
    tool_payload = {
        "thought": "Gerçek e2e mock yanıtı",
        "tool": "final_answer",
        "argument": argument,
    }
    return {"message": {"content": json.dumps(tool_payload)}}


class _MockOllamaHandler(BaseHTTPRequestHandler):
    response_argument = _RESPONSE_ARGUMENT

    def do_POST(self) -> None:  # noqa: N802 - stdlib interface
        if self.path != "/api/chat":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length:
            self.rfile.read(content_length)

        payload = _ollama_final_answer_payload(self.response_argument)
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class _ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


@pytest.fixture
def mock_ollama_server():
    server = _ThreadedTCPServer(("127.0.0.1", 0), _MockOllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield server

    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_register_login_and_chat_flow_over_real_agent_and_websocket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_ollama_server: _ThreadedTCPServer,
) -> None:
    """Register a real user, log in for a real JWT, then drive a full chat turn."""
    from cryptography.fernet import Fernet

    cfg = Config()
    cfg.DATABASE_URL = f"sqlite+aiosqlite:///{(tmp_path / 'real_e2e_ws.db').as_posix()}"
    cfg.AI_PROVIDER = "ollama"
    cfg.OLLAMA_URL = f"http://127.0.0.1:{mock_ollama_server.server_address[1]}"
    cfg.JWT_SECRET_KEY = "test-secret-for-real-e2e-ws-flow-not-used-in-prod"
    cfg.JWT_ALGORITHM = "HS256"
    cfg.MEMORY_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")

    real_agent = SidarAgent(cfg)
    asyncio.run(real_agent.initialize())

    async def _get_real_agent():
        return real_agent

    monkeypatch.setattr(web_server, "get_agent", _get_real_agent)

    username = "real_e2e_user"
    password = "s3cure-real-e2e-pass!"

    with TestClient(app) as client:
        register_response = client.post(
            "/auth/register",
            json={"username": username, "password": password, "tenant_id": "default"},
        )
        assert register_response.status_code == 200, register_response.text
        assert register_response.json()["user"]["username"] == username

        login_response = client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        assert login_response.status_code == 200, login_response.text
        token = login_response.json()["access_token"]
        assert token

        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"action": "auth", "token": token})
            assert websocket.receive_json() == {"auth_ok": True}

            # "araştır"/"kaynak" route the Supervisor's intent classifier to the
            # research role, which resolves in one LLM round-trip when the
            # response is a `{"tool": "final_answer", ...}` payload (see
            # ResearcherAgent.run_task) — unlike the default "code" intent,
            # which delegates through Coder/Reviewer and needs a matching
            # multi-step JSON contract the single canned mock response can't
            # satisfy.
            websocket.send_json({"message": "Bu konuyu araştır ve kaynakları özetle."})

            chunks: list[str] = []
            done = False
            while not done:
                event = websocket.receive_json()
                if "chunk" in event:
                    chunks.append(event["chunk"])
                done = bool(event.get("done"))

    assert _RESPONSE_ARGUMENT in "".join(chunks)

    # Confirm the DB leg of the flow is real, not just implied: the user and
    # the credential check both round-tripped through a real SQLite file.
    persisted_user = asyncio.run(
        real_agent.memory.db.authenticate_user(username=username, password=password)
    )
    assert persisted_user is not None
    assert persisted_user.username == username
