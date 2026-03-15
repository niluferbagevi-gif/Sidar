import asyncio
from types import SimpleNamespace

from tests.test_auto_handle_runtime import _make_auto
from tests.test_sidar_agent_runtime import SidarAgent


def test_sidar_subtask_unexpected_json_payload_hits_recovery_limit():
    agent = SidarAgent.__new__(SidarAgent)
    agent.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    class _Llm:
        async def chat(self, **kwargs):
            return "{invalid-json"

    async def _exec(_tool, _arg):
        return "ok"

    agent.llm = _Llm()
    agent._execute_tool = _exec

    out = asyncio.run(agent._tool_subtask("hatalı yönlendirme"))
    assert "Maksimum adım" in out


def test_auto_handle_docs_regex_no_match_warning_is_returned(monkeypatch):
    auto = _make_auto()

    async def _docs_search(_query, *_args):
        return True, "⚠ Eşleşme bulunamadı."

    auto.docs.search = _docs_search

    handled, msg = asyncio.run(auto._try_docs_search("depoda ara test", "depoda ara test"))
    assert handled is True
    assert "Eşleşme bulunamadı" in msg
