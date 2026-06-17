"""Multi-agent role paketleri."""

# Bu modül, yerleşik ajan rolleri için canonical import yollarını kullanır.
# Göreli importlardan kaçınarak modül cache'inin tekil olmasını sağlar.

from agent.roles.coder_agent import CoderAgent
from agent.roles.coverage_agent import CoverageAgent
from agent.roles.poyraz_agent import PoyrazAgent
from agent.roles.qa_agent import QAAgent
from agent.roles.researcher_agent import ResearcherAgent
from agent.roles.reviewer_agent import ReviewerAgent

__all__ = [
    "ResearcherAgent",
    "CoderAgent",
    "ReviewerAgent",
    "PoyrazAgent",
    "QAAgent",
    "CoverageAgent",
]
