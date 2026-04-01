import importlib
import sys
import types


def _install_supervisor_import_stubs() -> None:
    config_mod = types.ModuleType("config")

    class Config:
        MAX_QA_RETRIES = 3
        REACT_TIMEOUT = 60

    config_mod.Config = Config
    sys.modules["config"] = config_mod

    base_agent_mod = types.ModuleType("agent.base_agent")

    class BaseAgent:
        def __init__(self, cfg=None, role_name="base") -> None:
            self.cfg = cfg
            self.role_name = role_name

    base_agent_mod.BaseAgent = BaseAgent
    sys.modules["agent.base_agent"] = base_agent_mod

    contracts_mod = types.ModuleType("agent.core.contracts")

    class DelegationRequest:
        pass

    class TaskEnvelope:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    class TaskResult:
        def __init__(self, task_id, status, summary) -> None:
            self.task_id = task_id
            self.status = status
            self.summary = summary

    contracts_mod.DelegationRequest = DelegationRequest
    contracts_mod.TaskEnvelope = TaskEnvelope
    contracts_mod.TaskResult = TaskResult
    contracts_mod.is_delegation_request = lambda _x: False
    sys.modules["agent.core.contracts"] = contracts_mod

    registry_mod = types.ModuleType("agent.core.registry")

    class ActiveAgentRegistry:
        def register(self, *_args, **_kwargs):
            return None

        def get(self, _name):
            return types.SimpleNamespace(run_task=lambda _goal: "ok")

        def has(self, _name):
            return False

    registry_mod.ActiveAgentRegistry = ActiveAgentRegistry
    sys.modules["agent.core.registry"] = registry_mod

    event_stream_mod = types.ModuleType("agent.core.event_stream")

    class _Bus:
        async def publish(self, *_args, **_kwargs):
            return None

    event_stream_mod.get_agent_event_bus = lambda: _Bus()
    sys.modules["agent.core.event_stream"] = event_stream_mod

    for mod_name, cls_name in [
        ("agent.roles.coder_agent", "CoderAgent"),
        ("agent.roles.researcher_agent", "ResearcherAgent"),
        ("agent.roles.reviewer_agent", "ReviewerAgent"),
        ("agent.roles.poyraz_agent", "PoyrazAgent"),
        ("agent.roles.qa_agent", "QAAgent"),
        ("agent.roles.coverage_agent", "CoverageAgent"),
    ]:
        role_mod = types.ModuleType(mod_name)
        role_mod.__dict__[cls_name] = type(cls_name, (), {"__init__": lambda self, _cfg: None})
        sys.modules[mod_name] = role_mod


_install_supervisor_import_stubs()
SupervisorAgent = importlib.import_module("agent.core.supervisor").SupervisorAgent


def test_intent_routes_expected_keywords() -> None:
    assert SupervisorAgent._intent("Web'de doküman araştır") == "research"
    assert SupervisorAgent._intent("Lütfen pull request incele") == "review"
    assert SupervisorAgent._intent("growth funnel kampanya öner") == "marketing"
    assert SupervisorAgent._intent("pytest coverage için test üret") == "coverage"
    assert SupervisorAgent._intent("yeni özellik yaz") == "code"


def test_review_requires_revision_detects_signals() -> None:
    assert SupervisorAgent._review_requires_revision("Decision=reject") is True
    assert SupervisorAgent._review_requires_revision("Risk: Yüksek") is True
    assert SupervisorAgent._review_requires_revision("all checks passed") is False


def test_is_reject_feedback_payload_parses_plain_and_json() -> None:
    assert SupervisorAgent._is_reject_feedback_payload(None) is False
    assert SupervisorAgent._is_reject_feedback_payload("not-feedback") is False
    assert SupervisorAgent._is_reject_feedback_payload("qa_feedback|decision=reject") is True
    assert SupervisorAgent._is_reject_feedback_payload('qa_feedback|{"decision":"reject"}') is True
    assert SupervisorAgent._is_reject_feedback_payload('qa_feedback|{"decision":"accept"}') is False


def test_max_qa_retries_uses_config_override() -> None:
    supervisor = SupervisorAgent.__new__(SupervisorAgent)
    supervisor.cfg = type("Cfg", (), {"MAX_QA_RETRIES": 7})()
    assert supervisor._max_qa_retries() == 7

    supervisor.cfg = object()
    assert supervisor._max_qa_retries() == SupervisorAgent.MAX_QA_RETRIES
