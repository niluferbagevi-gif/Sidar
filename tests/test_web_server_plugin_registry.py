import asyncio

import pytest

from tests.test_web_server_runtime import _load_web_server


@pytest.fixture
def mod():
    return _load_web_server()


def test_register_plugin_agent_from_source(mod):
    src = '''
from agent.base_agent import BaseAgent

class DemoAgent(BaseAgent):
    ROLE_NAME = "demo"

    async def run_task(self, task_prompt: str) -> str:
        return f"ok:{task_prompt}"
'''
    result = mod._register_plugin_agent(
        role_name="demo_plugin",
        source_code=src,
        class_name="DemoAgent",
        capabilities=["demo", "tooling"],
        description="Demo plugin",
        version="1.2.3",
    )
    assert result["role_name"] == "demo_plugin"
    assert result["is_builtin"] is False
    assert "demo" in result["capabilities"]


def test_register_plugin_agent_endpoint_and_file_upload(mod):
    src = '''
from agent.base_agent import BaseAgent

class FileAgent(BaseAgent):
    async def run_task(self, task_prompt: str) -> str:
        return task_prompt
'''

    payload = mod._AgentPluginRegisterRequest(
        role_name="json_agent",
        source_code=src,
        class_name="FileAgent",
        capabilities=["x"],
        description="",
        version="1.0.0",
    )
    resp = asyncio.run(mod.register_agent_plugin(payload, _user=object()))
    assert resp.content["success"] is True
    assert resp.content["agent"]["role_name"] == "json_agent"

    class _Upload:
        filename = "upload_agent.py"

        def __init__(self, data: bytes):
            self._data = data
            self.closed = False

        async def read(self):
            return self._data

        async def close(self):
            self.closed = True

    upload_resp = asyncio.run(
        mod.register_agent_plugin_file(
            file=_Upload(src.encode("utf-8")),
            role_name="",
            class_name="FileAgent",
            capabilities="c1,c2",
            description="uploaded",
            version="2.0.0",
            _user=object(),
        )
    )
    assert upload_resp.content["success"] is True
    assert upload_resp.content["agent"]["role_name"] == "upload_agent"
    assert upload_resp.content["agent"]["version"] == "2.0.0"


def test_register_plugin_agent_validation_errors(mod):
    with pytest.raises(mod.HTTPException) as exc:
        mod._register_plugin_agent(
            role_name="bad role",
            source_code="",
            class_name=None,
            capabilities=[],
            description="",
            version="1.0.0",
        )
    assert exc.value.status_code == 400