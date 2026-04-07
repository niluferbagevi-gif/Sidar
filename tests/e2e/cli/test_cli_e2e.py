import json
import os
import socketserver
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path


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



def test_cli_command_runs_end_to_end_with_real_agent_and_mocked_llm(tmp_path: Path) -> None:
    server = _ThreadedTCPServer(("127.0.0.1", 0), _MockOllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    db_path = tmp_path / "sidar_cli_e2e.db"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(Path(__file__).resolve().parents[3]),
            "USE_GPU": "false",
            "REQUIRE_GPU": "false",
            "OLLAMA_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "MEMORY_ENCRYPTION_KEY": "8Jj8N4_VA8mYk9m97xzx6hQhYBL3J6f8xKqfZxM3VYQ=",
        }
    )

    try:
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
            cwd=Path(__file__).resolve().parents[3],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.returncode == 0, result.stderr
    assert "Sidar >" in result.stdout
    assert result.stdout.strip(), "CLI komutu bir çıktı üretmelidir."
