"""Multi-agent role paketleri.

Yerleşik rol sınıfları **mutlak (canonical) import** ile yüklenir. ``agent.registry``
modülünde ``BUILTIN_ROLE_CONTRACTS`` üzerinden ``importlib.import_module`` çağrıları
da aynı kanonik modül adını kullanır; göreli import ile karışık çalıştırılırsa
Python ``sys.modules`` önbelleğinde aynı sınıf iki farklı kimlikle eşleşebilir ve
``spec.agent_class is exported_cls`` kontrolleri kırılır. Bu paket ile registry
arasındaki tek doğruluk kaynağını korumak için tüm import'lar aşağıdaki kanonik
yola sabitlenmiştir.
"""

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
