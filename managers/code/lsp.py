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


__all__ = [
    "LSPProtocolError",
    "decode_lsp_stream",
    "encode_lsp_message",
    "file_uri_to_path",
    "path_to_file_uri",
]
