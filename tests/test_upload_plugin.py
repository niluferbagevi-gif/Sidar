import asyncio
import importlib
import sys
import types


def _import_upload_agent_with_stubbed_base_agent():
    base_agent_mod = types.ModuleType("agent.base_agent")

    class _BaseAgent:
        pass

    base_agent_mod.BaseAgent = _BaseAgent
    prev = sys.modules.get("agent.base_agent")
    sys.modules["agent.base_agent"] = base_agent_mod
    try:
        mod = importlib.import_module("plugins.upload_agent")
        mod = importlib.reload(mod)
        from plugins.upload_agent import UploadAgent

        return UploadAgent
    finally:
        if prev is None:
            sys.modules.pop("agent.base_agent", None)
        else:
            sys.modules["agent.base_agent"] = prev


def test_upload_agent_run_task_handles_empty_and_normal_prompt():
    UploadAgent = _import_upload_agent_with_stubbed_base_agent()
    agent = object.__new__(UploadAgent)

    none_result = asyncio.run(agent.run_task(None))
    empty_result = asyncio.run(agent.run_task("   "))
    normal_result = asyncio.run(agent.run_task("dosyayı işle"))

    assert none_result == "Boş görev alındı."
    assert empty_result == "Boş görev alındı."
    assert normal_result == "UploadAgent: dosyayı işle"

def test_upload_agent_import_path_via_stubbed_base_agent():
    UploadAgent = _import_upload_agent_with_stubbed_base_agent()
    assert UploadAgent.__module__ == "plugins.upload_agent"
