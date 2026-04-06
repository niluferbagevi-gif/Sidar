"""Global pytest fixtures and test configuration hooks."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def fake_llm_response() -> dict[str, list[dict[str, dict[str, str]]]]:
    """Provide a deterministic fake LLM response payload for unit tests."""
    return {"choices": [{"message": {"content": "Mocked response"}}]}


@pytest.fixture
def fake_event_stream() -> list[dict[str, Any]]:
    """Provide a deterministic in-memory event stream representation."""
    return [
        {"type": "status", "message": "started"},
        {"type": "token", "message": "hello"},
        {"type": "status", "message": "completed"},
    ]
