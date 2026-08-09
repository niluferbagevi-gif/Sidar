import http.client
import importlib.util
import json
import os
import socketserver
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CLI_COMMAND_TIMEOUT_ENV = "SIDAR_CLI_E2E_TIMEOUT_SECONDS"
_CLI_COMMAND_DEFAULT_TIMEOUT_SECONDS = 60
_CLI_COMMAND_WSL_TIMEOUT_SECONDS = 180


def _is_wsl2_environment() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        osrelease = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8")
    except OSError:
        return False
    return "microsoft" in osrelease.casefold()


def _cli_command_timeout_seconds() -> int:
    override = os.environ.get(_CLI_COMMAND_TIMEOUT_ENV)
    if override:
        try:
            timeout = int(override)
        except ValueError:
            timeout = 0
        if timeout > 0:
            return timeout
    if _is_wsl2_environment():
        return _CLI_COMMAND_WSL_TIMEOUT_SECONDS
    return _CLI_COMMAND_DEFAULT_TIMEOUT_SECONDS


_CLI_COMMAND_TIMEOUT_SECONDS = _cli_command_timeout_seconds()

_CLI_ENV_ALLOWLIST = (
    "PATH",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
)


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


def _isolated_cli_env(
    *, tmp_path: Path, mock_ollama_server: _ThreadedTCPServer, memory_encryption_key: str
) -> dict[str, str]:
    """Build a minimal subprocess env so local Ollama/proxy settings cannot leak in."""
    db_path = tmp_path / "sidar_cli_e2e.db"
    env = {key: os.environ[key] for key in _CLI_ENV_ALLOWLIST if key in os.environ}
    env.update(
        {
            "PYTHONPATH": str(PROJECT_ROOT),
            "SIDAR_SKIP_DEFAULT_DOTENV": "1",
            "SIDAR_KEYS_FILE": str(tmp_path / "missing-sidar-keys.env"),
            "USE_GPU": "false",
            "REQUIRE_GPU": "false",
            "OLLAMA_URL": f"http://127.0.0.1:{mock_ollama_server.server_address[1]}",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "MEMORY_ENCRYPTION_KEY": memory_encryption_key,
        }
    )
    return env


@pytest.fixture
def mock_ollama_server():
    server = _ThreadedTCPServer(("127.0.0.1", 0), _MockOllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield server

    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_cli_command_runs_end_to_end_with_real_agent_and_mocked_llm(
    tmp_path: Path, mock_ollama_server
) -> None:
    if importlib.util.find_spec("pydantic") is None:
        pytest.skip("pydantic kurulu değil; gerçek ajan CLI e2e testi atlanıyor.")

    from cryptography.fernet import Fernet

    env = _isolated_cli_env(
        tmp_path=tmp_path,
        mock_ollama_server=mock_ollama_server,
        memory_encryption_key=Fernet.generate_key().decode("utf-8"),
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
        timeout=_CLI_COMMAND_TIMEOUT_SECONDS,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "Sidar >" in result.stdout
    assert result.stdout.strip(), "CLI komutu bir çıktı üretmelidir."


def test_cli_command_timeout_uses_positive_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_CLI_COMMAND_TIMEOUT_ENV, "240")

    assert _cli_command_timeout_seconds() == 240


def test_cli_command_timeout_uses_wsl_default_when_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_CLI_COMMAND_TIMEOUT_ENV, raising=False)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")

    assert _cli_command_timeout_seconds() == _CLI_COMMAND_WSL_TIMEOUT_SECONDS


def test_cli_command_timeout_keeps_linux_default_for_invalid_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_CLI_COMMAND_TIMEOUT_ENV, "not-a-number")
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setattr(Path, "read_text", lambda self, encoding=None: "linux-generic")

    assert _cli_command_timeout_seconds() == _CLI_COMMAND_DEFAULT_TIMEOUT_SECONDS


def test_ollama_response_payload_wraps_argument() -> None:
    payload = _ollama_response_payload("echo-value")
    content = json.loads(payload["message"]["content"])
    assert content["thought"] == "CLI e2e mock response"
    assert content["tool"] == "final_answer"
    assert content["argument"] == "echo-value"


def test_isolated_cli_env_blocks_ambient_ollama_and_proxy_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_ollama_server
) -> None:
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("SIDAR_ENV", "test")
    monkeypatch.setenv("DOTENV_FILE", ".env.test")

    env = _isolated_cli_env(
        tmp_path=tmp_path,
        mock_ollama_server=mock_ollama_server,
        memory_encryption_key="test-fernet-key",
    )

    assert env["OLLAMA_URL"] == f"http://127.0.0.1:{mock_ollama_server.server_address[1]}"
    assert "OLLAMA_HOST" not in env
    assert "HTTP_PROXY" not in env
    assert "SIDAR_ENV" not in env
    assert "DOTENV_FILE" not in env
    assert env["SIDAR_SKIP_DEFAULT_DOTENV"] == "1"
    assert env["NO_PROXY"] == "127.0.0.1,localhost"


def test_cli_command_skips_when_pydantic_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mock_ollama_server
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)

    with pytest.raises(pytest.skip.Exception):
        test_cli_command_runs_end_to_end_with_real_agent_and_mocked_llm(
            tmp_path, mock_ollama_server
        )


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
