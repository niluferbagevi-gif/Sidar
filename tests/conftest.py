import base64
import hashlib
import hmac
import importlib.util
import json
import sys
import types

import pytest


if importlib.util.find_spec("jwt") is None:
    _jwt = types.ModuleType("jwt")

    class PyJWTError(Exception):
        pass

    def _b64encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def _b64decode(data: str) -> bytes:
        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode((data + padding).encode("ascii"))

    def encode(payload, secret, algorithm="HS256"):
        if algorithm != "HS256":
            raise PyJWTError("Unsupported algorithm")
        header = {"alg": algorithm, "typ": "JWT"}
        header_part = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_part = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        signature = hmac.new(str(secret).encode("utf-8"), signing_input, hashlib.sha256).digest()
        return f"{header_part}.{payload_part}.{_b64encode(signature)}"

    def decode(token, secret, algorithms):
        if "HS256" not in algorithms:
            raise PyJWTError("Unsupported algorithm")
        try:
            header_part, payload_part, sig_part = token.split(".", 2)
        except ValueError as exc:
            raise PyJWTError("Malformed token") from exc
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        expected = hmac.new(str(secret).encode("utf-8"), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64encode(expected), sig_part):
            raise PyJWTError("Signature verification failed")
        return json.loads(_b64decode(payload_part).decode("utf-8"))

    _jwt.PyJWTError = PyJWTError
    _jwt.encode = encode
    _jwt.decode = decode
    sys.modules["jwt"] = _jwt


# pytest-asyncio >= 0.21+ ile session kapsamlı event loop pytest.ini üzerinden
# `asyncio_default_fixture_loop_scope = session` ayarıyla sağlanır.
# Özel event_loop fixture override'ı artık gerekli değildir ve deprecated'dır.