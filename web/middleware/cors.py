from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

LOOPBACK_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$"


def configure_loopback_cors(app: FastAPI) -> None:
    """Allow localhost/loopback browser origins independently of the dev port."""
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=LOOPBACK_ORIGIN_REGEX,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
    )
