"""Language Server Protocol framing and URI helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path, PosixPath, PureWindowsPath
from typing import Any
from urllib.parse import quote, unquote, urlparse


class LSPProtocolError(RuntimeError):
    """Raised when a language-server message frame is incomplete."""


def path_to_file_uri(path: Path, *, path_separator: str = os.sep) -> str:
    """Encode an absolute local path as an LSP file URI."""
    resolved = path.resolve()
    return f"file://{quote(str(resolved).replace(path_separator, '/'))}"


def file_uri_to_path(uri: str, *, os_name: str = os.name) -> Path | PureWindowsPath:
    """Decode an LSP file URI using the requested platform semantics."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Desteklenmeyen URI şeması: {uri}")
    raw_path = unquote(parsed.path)
    if os_name == "nt":
        normalized_path = raw_path[1:] if raw_path.startswith("/") else raw_path
        return PureWindowsPath(normalized_path)
    return PosixPath(raw_path)


def encode_lsp_message(payload: dict[str, Any]) -> bytes:
    """Frame a JSON payload for an LSP stdio stream."""
    body = json.dumps(payload).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def decode_lsp_stream(raw: bytes) -> list[dict[str, Any]]:
    """Decode complete JSON payloads from an LSP stdio stream."""
    messages: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(raw):
        header_end = raw.find(b"\r\n\r\n", cursor)
        if header_end == -1:
            break
        header_blob = raw[cursor:header_end].decode("ascii", errors="replace")
        headers = {}
        for line in header_blob.split("\r\n"):
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        content_length = int(headers.get("content-length", "0") or 0)
        cursor = header_end + 4
        body = raw[cursor : cursor + content_length]
        if len(body) < content_length:
            raise LSPProtocolError("Eksik LSP mesaj gövdesi alındı.")
        cursor += content_length
        messages.append(json.loads(body.decode("utf-8")))
    return messages


def lsp_install_hint(language_id: str) -> str:
    """Return the canonical installation hint for a language server."""
    if language_id == "python":
        return "uv tool install pyright  # veya: uv add --dev pyright"
    return "npm install -g typescript-language-server typescript"


def lsp_target_binary(
    command: list[str], *, language_id: str, python_server: str, typescript_server: str
) -> str:
    """Return the wrapped LSP executable name from an uv/uvx command."""
    default = python_server if language_id == "python" else typescript_server
    if not command or Path(command[0]).name.lower() not in {"uv", "uvx"}:
        return default
    skip_next = False
    for token in command[1:]:
        if skip_next:
            skip_next = False
            continue
        if token in {"--from", "--with"}:
            skip_next = True
            continue
        if token in {"run", "--frozen", "tool"} or token.startswith("-"):
            continue
        return token
    return default


def lsp_stderr_indicates_missing_binary(stderr_text: str) -> bool:
    """Return whether wrapper stderr indicates a missing executable."""
    lowered = stderr_text.lower()
    return bool(stderr_text) and any(
        marker in lowered
        for marker in (
            "failed to spawn",
            "no such file or directory",
            "command not found",
            "executable not found",
            "not found in",
        )
    )


def extract_lsp_result(
    messages: list[dict[str, Any]], request_id: int = 2
) -> tuple[Any, list[dict[str, Any]]]:
    """Separate one request result from LSP notifications."""
    result = None
    notifications: list[dict[str, Any]] = []
    for message in messages:
        if message.get("id") == request_id:
            if "error" in message:
                raise RuntimeError(str(message["error"]))
            result = message.get("result")
        elif "method" in message:
            notifications.append(message)
    return result, notifications


def format_lsp_locations(locations: Any, limit: int) -> str:
    """Format Location and LocationLink results for human-readable output."""
    if not locations:
        return "Sonuç bulunamadı."
    normalized = [
        {
            "uri": item["targetUri"],
            "range": item.get("targetSelectionRange") or item.get("targetRange") or {},
        }
        if "targetUri" in item
        else item
        for item in locations
    ]
    lines = []
    for entry in normalized[:limit]:
        start = entry.get("range", {}).get("start", {})
        path = file_uri_to_path(entry.get("uri", ""))
        lines.append(
            f"- {path}: satır {int(start.get('line', 0)) + 1}, "
            f"sütun {int(start.get('character', 0)) + 1}"
        )
    if len(normalized) > limit:
        lines.append(f"... ve {len(normalized) - limit} ek sonuç daha.")
    return "\n".join(lines)


def position_params(path: Path, line: int, character: int) -> dict[str, Any]:
    """Build canonical LSP text-document position parameters."""
    return {
        "textDocument": {"uri": path_to_file_uri(path)},
        "position": {"line": line, "character": character},
    }


__all__ = [
    "LSPProtocolError",
    "decode_lsp_stream",
    "encode_lsp_message",
    "extract_lsp_result",
    "file_uri_to_path",
    "format_lsp_locations",
    "lsp_install_hint",
    "lsp_stderr_indicates_missing_binary",
    "lsp_target_binary",
    "path_to_file_uri",
    "position_params",
]
