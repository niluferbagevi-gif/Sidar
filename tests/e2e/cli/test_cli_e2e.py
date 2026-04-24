import json
import http.client
import importlib.util
import os
import socketserver
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _ollama_response_payload(argument: str) -> dict:
    tool_payload = {
        "thought": "CLI e2e mock response",
        "tool": "final_answer",
        "argument": argument,
    }
    return {"message": {"content": json.dumps(tool_payload)}}


class _MockOllamaHandler(BaseHTTPRequestHandler):
    response_argument = "CLI_E2E_OK"

    def do_POST(self):  # noqa: N802 - stdlib interface
        if self.path != "/api/chat":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length:
            self.rfile.read(content_length)

        payload = _ollama_response_payload(self.response_argument)
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):  # noqa: A003
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


def test_cli_command_runs_end_to_end_with_real_agent_and_mocked_llm(tmp_path: Path, mock_ollama_server) -> None:
    if importlib.util.find_spec("pydantic") is None:
        pytest.skip("pydantic kurulu değil; gerçek ajan CLI e2e testi atlanıyor.")

    db_path = tmp_path / "sidar_cli_e2e.db"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(PROJECT_ROOT),
            "USE_GPU": "false",
            "REQUIRE_GPU": "false",
            "OLLAMA_URL": f"http://127.0.0.1:{mock_ollama_server.server_address[1]}",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "MEMORY_ENCRYPTION_KEY": "8Jj8N4_VA8mYk9m97xzx6hQhYBL3J6f8xKqfZxM3VYQ=",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "cli.py",
            "--provider",
            "ollama",
            "--model",
            "mocked-model",
            "--command",
            "test_echo",
        ],
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "Sidar >" in result.stdout
    assert result.stdout.strip(), "CLI komutu bir çıktı üretmelidir."


def test_ollama_response_payload_wraps_argument() -> None:
    payload = _ollama_response_payload("echo-value")
    content = json.loads(payload["message"]["content"])
    assert content["thought"] == "CLI e2e mock response"
    assert content["tool"] == "final_answer"
    assert content["argument"] == "echo-value"


def test_cli_command_skips_when_pydantic_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_ollama_server) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)

    with pytest.raises(pytest.skip.Exception):
        test_cli_command_runs_end_to_end_with_real_agent_and_mocked_llm(tmp_path, mock_ollama_server)


def test_mock_ollama_handler_returns_404_for_unknown_path(mock_ollama_server) -> None:
    host, port = mock_ollama_server.server_address
    conn = http.client.HTTPConnection(host, port, timeout=3)
    try:
        conn.request("POST", "/not-found")
        response = conn.getresponse()
        response.read()
    finally:
        conn.close()

    assert response.status == 404


def test_mock_ollama_handler_returns_chat_payload_without_request_body(mock_ollama_server) -> None:
    host, port = mock_ollama_server.server_address
    conn = http.client.HTTPConnection(host, port, timeout=3)
    previous_argument = _MockOllamaHandler.response_argument
    _MockOllamaHandler.response_argument = "NO_BODY_ARG"

    try:
        conn.request("POST", "/api/chat")
        response = conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
    finally:
        _MockOllamaHandler.response_argument = previous_argument
        conn.close()

    parsed = json.loads(data["message"]["content"])
    assert response.status == 200
    assert parsed["argument"] == "NO_BODY_ARG"


def test_mock_ollama_handler_returns_chat_payload(mock_ollama_server) -> None:
    host, port = mock_ollama_server.server_address
    previous_argument = _MockOllamaHandler.response_argument
    _MockOllamaHandler.response_argument = "EXPECTED_E2E_ARG"
    conn = http.client.HTTPConnection(host, port, timeout=3)

    try:
        body = json.dumps({"messages": [{"role": "user", "content": "hello"}]})
        conn.request(
            "POST",
            "/api/chat",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
    finally:
        _MockOllamaHandler.response_argument = previous_argument
        conn.close()

    parsed = json.loads(data["message"]["content"])
    assert response.status == 200
    assert parsed["argument"] == "EXPECTED_E2E_ARG"
