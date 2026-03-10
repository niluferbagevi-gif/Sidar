import asyncio

from agent.roles.researcher_agent import ResearcherAgent


def test_researcher_agent_initializes_with_research_tools():
    a = ResearcherAgent()
    assert set(a.tools.keys()) == {"web_search", "fetch_url", "search_docs", "docs_search"}


def test_researcher_agent_run_task_routes_to_web_search_for_general_query():
    a = ResearcherAgent()

    called = {"query": None}

    async def fake_web_search(query: str) -> str:
        called["query"] = query
        return "Python 3.12: f-string iyileştirmeleri, perf artışları ve typing güncellemeleri."

    a.tools["web_search"] = fake_web_search

    out = asyncio.run(a.run_task("Python 3.12 yenilikleri neler?"))

    assert called["query"] == "Python 3.12 yenilikleri neler?"
    assert "Python 3.12" in out
