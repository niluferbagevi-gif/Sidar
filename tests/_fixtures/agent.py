"""Agent factory fixtures shared across unit and integration tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _build_null_agent_dependencies(config: Any) -> Any:
    """Build deterministic SidarAgent dependencies for unit-test factories."""
    from agent.sidar_agent import AgentDependencies

    security = MagicMock()
    security.level_name = getattr(config, "ACCESS_LEVEL", "safe")
    security.set_level.return_value = True

    code = MagicMock()
    code.get_metrics.return_value = {"files_read": 0, "files_written": 0}
    code.read_file.return_value = (False, "")

    health = MagicMock()
    health.full_report.return_value = "System health unavailable in unit fixture."

    github = MagicMock()
    github.is_available.return_value = False
    github.status.return_value = "GitHub: disabled for unit tests"

    memory = MagicMock()
    memory.initialize = AsyncMock(return_value=None)
    memory._ensure_initialized = AsyncMock(return_value=None)
    memory.add = AsyncMock(return_value=None)
    memory.get_history = AsyncMock(return_value=[])
    memory.clear = AsyncMock(return_value=None)
    memory.apply_summary = AsyncMock(return_value=None)
    memory.get_last_file.return_value = None
    memory.__len__.return_value = 0

    llm = MagicMock()
    llm.chat = AsyncMock(return_value="mock-response")

    web = MagicMock()
    web.is_available.return_value = False
    web.status.return_value = "WebSearch: disabled for unit tests"

    pkg = MagicMock()
    pkg.status.return_value = "PackageInfo: disabled for unit tests"

    docs = MagicMock()
    docs.collection = None
    docs.status.return_value = "RAG: disabled for unit tests"
    docs.search = MagicMock(return_value=[])
    docs.add_document = AsyncMock(return_value=None)

    todo = MagicMock()
    todo.__len__.return_value = 0
    todo.list_tasks.return_value = ""

    return AgentDependencies(
        security=security,
        code=code,
        health=health,
        github=github,
        memory=memory,
        llm=llm,
        web=web,
        pkg=pkg,
        docs=docs,
        todo=todo,
    )


@pytest.fixture
def agent_factory(mock_config: Callable[..., Any]) -> Callable[..., Any]:
    """Testler için standartlaştırılmış ajan üretim fabrikası."""

    def _create_agent(agent_class: type, **kwargs: Any) -> Any:
        return agent_class(config=mock_config(), **kwargs)

    return _create_agent


@pytest.fixture
def sidar_agent_factory(mock_config: Callable[..., Any]) -> Callable[..., Any]:
    """SidarAgent için test örneği üreticisi."""

    def _create_agent(**kwargs: Any) -> Any:
        # Config yalnızca cfg/config ile geçirilebilir; diğer override yollarını engelle.
        config = kwargs.pop("cfg", kwargs.pop("config", mock_config()))
        if kwargs:
            raise ValueError(
                "Lütfen config parametrelerini mock_config() üzerinden geçin. "
                "Örn: sidar_agent_factory(cfg=mock_config(USE_GPU=True))"
            )

        from agent.sidar_agent import SidarAgent

        deps = _build_null_agent_dependencies(config)
        return SidarAgent(config=config, deps=deps)

    return _create_agent


@pytest.fixture
def fake_llm_response() -> Callable[..., Any]:
    """LLM istemcisi için deterministik, başarılı bir async yanıt döner."""

    async def _mock_response(
        prompt: str,
        mock_tool_calls: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        mock_tokens = kwargs.pop("mock_tokens", 10)
        _ = kwargs
        response: dict[str, Any] = {
            "content": f"mock-response:{prompt[:32]}",
            "usage": {"total_tokens": mock_tokens},
        }
        if mock_tool_calls:
            response["tool_calls"] = mock_tool_calls
        return response

    return _mock_response


@pytest.fixture
def fake_llm_error() -> Callable[..., Any]:
    """LLM istemcisi için deterministik hata (rate-limit/timeout) döner."""

    async def _mock_error(*args: Any, **kwargs: Any) -> dict[str, Any]:
        _ = (args, kwargs)
        raise RuntimeError("rate limit exceeded")

    return _mock_error


@pytest.fixture
def fake_event_stream() -> Callable[[], Any]:
    """Ajan event stream çıktılarını deterministik ve güncel zamanla simüle eder."""

    async def _stream():
        import time

        from agent.core.event_stream import AgentEvent

        now = time.time()
        yield AgentEvent(ts=now, source="system", message="initializing")
        yield AgentEvent(ts=now + 1.0, source="assistant", message="İşlem tamam.")

    return _stream


@pytest.fixture
def fake_social_api() -> Any:
    """Sosyal medya API çağrıları için ortak asenkron fake adaptör."""
    from unittest.mock import AsyncMock

    api = AsyncMock(
        spec=[
            "fetch_profile",
            "fetch_posts",
            "publish",
            "set_rate_limit_error",
            "set_timeout_error",
        ]
    )
    api.fetch_profile.return_value = {"id": "user-1", "username": "mock_user", "followers": 42}
    api.fetch_posts.return_value = [{"id": "post-1", "text": "mock post", "likes": 7}]
    api.publish.return_value = {"ok": True, "post_id": "published-1"}

    def set_rate_limit_error() -> None:
        api.fetch_profile.side_effect = RuntimeError("API Rate Limit")

    def set_timeout_error() -> None:
        api.fetch_posts.side_effect = TimeoutError("API request timed out")

    api.set_rate_limit_error = set_rate_limit_error
    api.set_timeout_error = set_timeout_error
    return api


@pytest.fixture
def fake_video_stream() -> Any:
    """Video analiz pipeline'ı için deterministik asenkron fake akış."""
    from unittest.mock import AsyncMock

    stream = AsyncMock()
    stream.read_frames = AsyncMock(
        return_value=[
            {"frame_id": 1, "timestamp": 0.0},
            {"frame_id": 2, "timestamp": 0.04},
        ]
    )
    # metadata çoğu stream implementasyonunda property olarak okunur.
    # Bu yüzden dict ataması yapıp testlerde sessizce AsyncMock zincirlenmesini önlüyoruz.
    stream.metadata = {"fps": 25, "duration_sec": 2}
    # Gelecekte metadata async API'ye taşınırsa fixture davranışı uyumlu kalsın.
    stream.get_metadata = AsyncMock(return_value=stream.metadata)
    return stream


@pytest.fixture
def fake_video_stream_error() -> Any:
    """Video analiz pipeline'ı için bozuk akış/hata senaryosu."""
    from unittest.mock import AsyncMock

    stream = AsyncMock()
    stream.read_frames = AsyncMock(side_effect=RuntimeError("corrupted video stream"))
    stream.metadata = {"fps": 0, "duration_sec": 0}
    stream.get_metadata = AsyncMock(return_value=stream.metadata)
    return stream
