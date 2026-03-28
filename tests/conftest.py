"""Pytest için minimal ve yeniden kullanılabilir çekirdek fixture seti."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class MockLLMClient:
    """Deterministic davranan basit LLM istemcisi mock'u."""

    default_response: str = "mock-response"
    queued_responses: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        if self.queued_responses:
            return self.queued_responses.pop(0)
        return self.default_response

    def queue(self, *responses: str) -> None:
        self.queued_responses.extend(responses)


@pytest.fixture
def db_session() -> sqlite3.Connection:
    """İzole in-memory SQLite bağlantısı sağlar."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def llm_mock_client() -> MockLLMClient:
    """Testlerde ortak kullanılacak LLM mock istemcisi."""
    return MockLLMClient()


@pytest.fixture
def test_config(tmp_path: Path) -> dict[str, Any]:
    """Sık kullanılan test konfigürasyon değerleri."""
    return {
        "environment": "test",
        "workspace_dir": str(tmp_path),
        "debug": False,
        "llm_timeout_seconds": 10,
    } 