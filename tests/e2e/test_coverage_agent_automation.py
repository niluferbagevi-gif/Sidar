"""CoverageAgent ile test üretim sürecini görev olarak otomatikleştirme senaryosu."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from agent.roles.coverage_agent import CoverageAgent
from config import Config


def test_coverage_agent_can_execute_natural_language_test_generation_task():
    async def _run_case() -> None:
        agent = CoverageAgent(cfg=Config())

        agent.code.run_pytest_and_collect = MagicMock(
            return_value={
                "analysis": {
                    "summary": "coverage açıkları bulundu",
                    "findings": [
                        {
                            "finding_type": "coverage_gap",
                            "target_path": "tests/test_agent_definitions.py",
                            "summary": "trivial assertions",
                        }
                    ],
                },
                "output": "pytest output",
            }
        )
        agent._generate_test_candidate = AsyncMock(
            return_value="def test_prompt_contract():\n    assert 'tool' in prompt\n"
        )
        agent.code.write_generated_test = MagicMock(return_value=(True, "ok"))
        agent._record_coverage_task = AsyncMock()

        result = await agent.run_task(
            "Mevcut projede test_agent_definitions.py dosyasını analiz et ve trivial testleri mantıksal testlerle değiştir"
        )
        payload = json.loads(result)

        assert payload["command"] == "pytest -q"
        assert payload["status"] == "tests_written"
        assert payload["target_path"] == "tests/test_agent_definitions.py"
        assert payload["suggested_test_path"].endswith("test_test_agent_definitions_coverage.py")
        agent._generate_test_candidate.assert_awaited_once()

    asyncio.run(_run_case())
