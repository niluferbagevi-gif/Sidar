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
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


@pytest.fixture(autouse=True)
def _cleanup_logging_handlers():
    """Teste sonra logging handler'larını kapat (ResourceWarning önlemek için)."""
    yield
    import logging
    import gc
    # Tüm handler'ları kapat
    for handler in logging.root.handlers[:]:
        try:
            handler.close()
            logging.root.removeHandler(handler)
        except Exception:
            pass
    # Tüm logger'ları temizle
    for logger_name in list(logging.Logger.manager.loggerDict):
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers[:]:
            try:
                handler.close()
                logger.removeHandler(handler)
            except Exception:
                pass
    # Garbage collection'ı force et
    gc.collect()