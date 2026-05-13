"""Shared pytest fixture policy for autonomous test generation prompts."""

from __future__ import annotations

SHARED_PROJECT_FIXTURES: tuple[str, ...] = (
    "mock_config",
    "fake_llm_response",
    "fake_llm_error",
    "fake_event_stream",
    "fake_redis",
    "fake_db_session",
    "frozen_time",
    "agent_factory",
    "sidar_agent_factory",
    "fake_coverage_code_manager",
    "fake_coverage_db_class",
    "fake_llm_tool_sequence",
    "fake_web_search_result",
    "fake_vector_store",
    "respx_mock_router",
    "respx_mock_router_relaxed",
)

SHARED_TEST_FIXTURE_GUIDANCE = (
    "Ortak proje fixture kuralı: test üretirken veya onarırken önce tests/conftest.py "
    "içindeki standart fixture'ları kullan. Kullanılabilir ortak fixture'lar: "
    f"{', '.join(SHARED_PROJECT_FIXTURES)}. "
    "unittest.mock.Mock/MagicMock/AsyncMock veya rastgele ad-hoc fake nesne/class üretme; "
    "mevcut fixture yetmiyorsa yeni ortak fixture ihtiyacını açıkça belirt veya tests/conftest.py "
    "kapsamındaki fixture'ı genişlet."
)
