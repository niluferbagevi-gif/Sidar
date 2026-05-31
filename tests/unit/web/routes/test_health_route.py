from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from web.routes.health import build_health_router


def test_health_router_distinguishes_liveness_and_readiness() -> None:
    readiness_flags: list[bool] = []

    async def _health_response(readiness: bool) -> Any:
        readiness_flags.append(readiness)
        return JSONResponse({"ready": readiness}, status_code=503 if readiness else 200)

    app = FastAPI()
    app.include_router(build_health_router(_health_response))
    client = TestClient(app)

    assert client.get("/health").json() == {"ready": False}
    assert client.get("/healthz").status_code == 200
    readiness = client.get("/readyz")
    assert readiness.status_code == 503
    assert readiness.json() == {"ready": True}
    assert readiness_flags == [False, False, True]
