import importlib
import sys
import types

import tests.unit.plugins.test_aws_management_agent as aws_management_tests


def test_aws_management_test_module_bootstrap_injects_stub_when_base_agent_missing():
    saved_base_agent = sys.modules.get("agent.base_agent")
    fallback_base_agent = types.ModuleType("agent.base_agent")
    fallback_base_agent.BaseAgent = object  # type: ignore[attr-defined]
    sys.modules.pop("agent.base_agent", None)
    reloaded = importlib.reload(aws_management_tests)
    injected = sys.modules.get("agent.base_agent")
    assert isinstance(injected, types.ModuleType)
    assert hasattr(injected, "BaseAgent")
    assert reloaded.AWSManagementAgent is not None
    sys.modules["agent.base_agent"] = saved_base_agent or fallback_base_agent
    importlib.reload(aws_management_tests)
